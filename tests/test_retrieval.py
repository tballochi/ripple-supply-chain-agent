"""Checks on retrieval: free text -> alerts -> graph entities."""

import pytest

from ripple import db, embeddings, retrieval


@pytest.fixture(scope="module")
def conn():
    connection = db.connect()
    yield connection
    connection.close()


@pytest.fixture
def fulltext_only(monkeypatch):
    monkeypatch.setenv("RIPPLE_NO_EMBEDDINGS", "1")


def port_names(result):
    return [p["name"] for p in result["ports"]]


# These work with or without the embedding model.
@pytest.mark.parametrize("text,expected", [
    ("Port of Rotterdam closed for 3 days", ["Rotterdam"]),
    ("Typhoon near Shanghai", ["Shanghai"]),
    ("strike in the Netherlands", ["Rotterdam"]),
    ("ports in China closed for 2 days", ["Ningbo", "Shanghai", "Shenzhen"]),
    ("the ransomware attack in Korea", ["Busan"]),
    ("oil leak near Gibraltar", ["Algeciras", "Tanger Med"]),
])
def test_resolves_ports_without_embeddings(conn, fulltext_only, text, expected):
    result = retrieval.resolve(conn, text)
    assert result["mode"] == "fulltext"
    assert port_names(result) == expected


def test_resolves_a_vessel_by_name(conn, fulltext_only):
    result = retrieval.resolve(conn, "MV Silver Spirit has an engine failure")
    assert [v["name"] for v in result["vessels"]] == ["MV Silver Spirit"]
    assert result["ports"] == []


@pytest.mark.parametrize("text", ["what is the weather like today", "strike", "port closed", "fuel prices"])
def test_vague_or_unrelated_text_matches_nothing(conn, fulltext_only, text):
    result = retrieval.resolve(conn, text)
    assert result["ports"] == [] and result["vessels"] == []


def test_alert_match_records_the_alert_it_came_from(conn, fulltext_only):
    port = retrieval.resolve(conn, "the ransomware attack in Korea")["ports"][0]
    assert port["matched_by"].startswith("alert ") and "Ransomware" in port["alert"]


needs_model = pytest.mark.skipif(embeddings.embed(["probe"]) is None,
                                 reason="embedding model not available")


# No word in common with the alert: only the vector side can find these.
@needs_model
@pytest.mark.parametrize("text,expected", [
    ("hackers took down a terminal's computer systems", ["Busan"]),
    ("Dutch dockers on strike", ["Rotterdam"]),
    ("storm about to hit the Chinese coast", ["Ningbo", "Shanghai"]),
])
def test_hybrid_search_finds_alerts_by_meaning(conn, text, expected):
    result = retrieval.resolve(conn, text)
    assert result["mode"] == "hybrid"
    assert port_names(result) == expected


@needs_model
@pytest.mark.parametrize("text", ["what is the weather like today", "strike", "port closed",
                                  "how are my shipments doing"])
def test_hybrid_search_does_not_guess(conn, text):
    result = retrieval.resolve(conn, text)
    assert result["ports"] == [] and result["vessels"] == []


@pytest.mark.parametrize("text,expected", [
    ("storm within 500 km of Singapore", ["Singapore", "Port Klang"]),
    ("typhoon in the South China Sea", ["Ho Chi Minh City", "Hong Kong", "Shenzhen"]),
    ("storm in the North Sea for 2 days", ["Bremerhaven", "Felixstowe", "Rotterdam", "Hamburg", "Antwerp"]),
])
def test_geography_selects_ports_by_distance(conn, fulltext_only, text, expected):
    assert port_names(retrieval.resolve(conn, text)) == expected  # nearest first


def test_area_without_ports_reports_the_nearest_one(conn, fulltext_only):
    result = retrieval.resolve(conn, "hurricane in the Gulf of Mexico")
    assert result["ports"] == [] and result["area"]["name"] == "Gulf of Mexico"
    assert result["area"]["nearest_port"] == "Savannah" and result["area"]["nearest_km"] > 900


@pytest.mark.parametrize("text,km", [("within 500 km of", 500), ("300 miles around", 483), ("1,200 km", 1200),
                                     ("closed for 3 days", None)])
def test_parse_radius(text, km):
    assert retrieval.parse_radius_km(text) == km
