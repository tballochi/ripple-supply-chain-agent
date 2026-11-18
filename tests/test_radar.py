"""Checks on the risk radar."""

from datetime import date

import pytest

from ripple import db, queries, radar


@pytest.fixture(scope="module")
def conn():
    connection = db.connect()
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def rows(conn):
    return radar.scan(conn)


def test_ranked_by_value_beyond_tolerance(rows):
    values = [r["value_beyond_tolerance_usd"] for r in rows]
    assert rows and values == sorted(values, reverse=True)
    assert rows[0]["port_names"] == ["Rotterdam"]


def test_only_what_is_left_of_an_alert_is_simulated(rows):
    ningbo_strike = next(r for r in rows if r["id"] == "A036")  # 72-hour strike from 29 November
    assert ningbo_strike["days_total"] == 3 and ningbo_strike["days_remaining"] == 1
    assert all(r["days_remaining"] > 0 for r in rows)
    assert "A051" not in {r["id"] for r in rows}  # Port Said, 28 November, 3 days: over


def test_an_alert_with_two_ports_is_one_combined_event(conn, rows):
    typhoon = next(r for r in rows if r["id"] == "A049")
    assert sorted(typhoon["port_codes"]) == ["CNNGB", "CNSHA"]
    combined = queries.combine([queries.port_closure(conn, c, 3, date(2026, 12, 1)) for c in typhoon["port_codes"]])
    assert typhoon["shipments"] == combined["shipments"]


def test_each_row_carries_a_question_ripple_understands(conn, rows):
    from ripple import agent
    out = agent.answer(conn, rows[0]["question"], use_llm=False)
    assert out["results"][0]["summary"]["shipments"] == rows[0]["shipments"]
