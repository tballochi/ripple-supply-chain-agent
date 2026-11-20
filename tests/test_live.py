"""Live mode, without the network: parsing, port matching, storage, radar."""

from datetime import date

import pytest

from ripple import db, live

TODAY = date(2026, 11, 20)

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Dockers walk out at Rotterdam, terminals closed - Example Wire</title>
  <link>https://example.org/a</link><pubDate>Thu, 19 Nov 2026 08:00:00 GMT</pubDate>
  <source url="https://example.org">Example Wire</source></item>
<item><title>Strike threat looms at the ports of Los Angeles and Long Beach - Example Wire</title>
  <link>https://example.org/b</link><pubDate>Wed, 18 Nov 2026 08:00:00 GMT</pubDate></item>
<item><title>Rotterdam port opens a new visitor centre - Example Wire</title>
  <link>https://example.org/c</link><pubDate>Thu, 19 Nov 2026 08:00:00 GMT</pubDate></item>
<item><title>Old strike at Antwerp, terminals closed - Example Wire</title>
  <link>https://example.org/d</link><pubDate>Mon, 02 Nov 2026 08:00:00 GMT</pubDate></item>
</channel></rss>"""


@pytest.fixture
def conn():
    c = db.connect()
    yield c
    c.close()


@pytest.mark.parametrize("title,ports,severity", [
    ("Dockers walk out at Rotterdam, terminals closed - Wire", ["NLRTM"], "high"),
    ("Possible strike looms over ports of LA, Long Beach", ["USLAX"], "medium"),
    ("Watchmen strike at L.A., Long Beach ports appearing more likely", ["USLAX"], "medium"),
    ("Santos Port Authority details cyber incident to terminals", ["BRSSZ"], "high"),
    ("Suez Canal convoys suspended for 2 days", ["EGPSD"], "high"),
])
def test_headlines_name_ports_and_sound_serious(title, ports, severity):
    found = live.classify(title)
    assert found["ports"] == ports and found["severity"] == severity


@pytest.mark.parametrize("title", ["Rotterdam port opens a new visitor centre",  # no disruption
                                   "Port strike in Durban"])                     # not a port of the graph
def test_other_headlines_are_ignored(title):
    assert live.classify(title) is None


def test_duration_is_read_from_the_headline():
    assert live.classify("Suez Canal convoys suspended for 2 days")["days"] == 2
    assert live.classify("Rotterdam terminals closed by a strike")["days"] == 3  # high: default


def test_rss_keeps_recent_disruptions_only():
    alerts = live.headlines_from_rss(RSS, TODAY)
    assert [(a["ports"], a["severity"], a["url"]) for a in alerts] == [
        (["NLRTM"], "high", "https://example.org/a"),
        (["USLAX"], "medium", "https://example.org/b")]
    assert alerts[0]["text"] == "Dockers walk out at Rotterdam, terminals closed"  # publisher dropped


def gdacs_event(level, kind, lon, lat, event_id=1):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"eventtype": kind, "eventid": event_id, "alertlevel": level, "name": "Test event",
                           "htmldescription": f"{level} {kind} test", "fromdate": "2026-11-18T00:00:00",
                           "todate": "2026-11-19T12:00:00", "url": {"report": "https://www.gdacs.org/x"}}}


def test_gdacs_hazards_touch_the_ports_within_their_radius(conn):
    payload = {"features": [
        gdacs_event("Red", "TC", 122.0, 30.5, 1),      # typhoon off Shanghai and Ningbo
        gdacs_event("Green", "TC", 122.0, 30.5, 2),    # routine: ignored
        gdacs_event("Orange", "EQ", -150.0, -40.0, 3),  # in the middle of the ocean: no port
    ]}
    alerts = live.hazards_from_gdacs(payload, conn)
    assert len(alerts) == 1
    assert set(alerts[0]["ports"]) == {"CNSHA", "CNNGB"} and alerts[0]["severity"] == "high"
    assert alerts[0]["days"] == 2


def test_live_alerts_are_stored_in_the_workspace_and_ranked(conn):
    live.store(live.headlines_from_rss(RSS, TODAY))
    live.store(live.headlines_from_rss(RSS, TODAY))  # fetching twice does not duplicate
    assert len(live.stored(TODAY)) == 2
    rows = live.scan(conn, TODAY)
    assert [r["port_names"] for r in rows] == [["Rotterdam"], ["Los Angeles"]]
    rotterdam = rows[0]
    assert rotterdam["shipments"] == 29 and rotterdam["days_total"] == 3  # same as the scenario question
    assert rotterdam["question"] == "Port of Rotterdam closed for 3 days"
    assert rotterdam["headlines"][0]["url"] == "https://example.org/a"


def test_fetch_survives_the_network_failing(conn, monkeypatch):
    import requests

    def offline(*args, **kwargs):
        raise requests.ConnectionError("offline")
    monkeypatch.setattr(live.requests, "get", offline)
    alerts, problems = live.fetch(conn, TODAY)
    assert alerts == [] and problems == ["GDACS: ConnectionError", "Google News: ConnectionError"]
