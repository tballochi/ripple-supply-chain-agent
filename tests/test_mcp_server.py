"""Checks on the MCP tools, called as plain Python functions."""

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from ripple import mcp_server


@pytest.fixture(autouse=True)
def fulltext_only(monkeypatch):
    monkeypatch.setenv("RIPPLE_NO_EMBEDDINGS", "1")


def test_port_closure_tool_returns_paths():
    out = mcp_server.port_closure_impact("Rotterdam", days=3, limit=2)
    assert out["summary"]["shipments"] > 0
    assert out["impacted_shipments"][0]["path"].startswith("Rotterdam")


def test_port_can_be_given_by_code():
    assert mcp_server.port_closure_impact("nlrtm", days=3)["disruption"]["name"] == "Rotterdam"


def test_analyze_disruption_from_free_text():
    out = mcp_server.analyze_disruption("the ransomware attack in Korea", limit=1)
    assert out["analyses"][0]["disruption"]["name"] == "Busan"


def test_schema_hides_the_embedding():
    schema = mcp_server.get_schema()
    assert "embedding" not in schema["nodes"]["Alert"]
    assert "(:Shipment)-[:ON_VESSEL]->(:Vessel)" in schema["relationships"]


def test_read_cypher_limits_rows():
    out = mcp_server.read_cypher("MATCH (p:Port) RETURN p.name AS name ORDER BY name", limit=3)
    assert len(out["rows"]) == 3 and out["truncated"]


@pytest.mark.parametrize("call", [
    lambda: mcp_server.port_closure_impact("Atlantis"),
    lambda: mcp_server.vessel_outage_impact("MV Nowhere"),
    lambda: mcp_server.read_cypher("CREATE (:X)"),
    lambda: mcp_server.read_cypher("MATCH (n RETURN n"),
])
def test_errors_reach_the_caller_with_a_message(call):
    with pytest.raises(ToolError) as error:
        call()
    assert str(error.value)


def test_compare_with_plain_rag_tool():
    out = mcp_server.compare_with_plain_rag("Port of Rotterdam closed for 3 days", k=10)
    assert out["graph"]["shipments"] > out["plain_rag"]["shipments_found"]
    assert len(out["documents"]) == 10


def test_simulate_diversion_tool():
    out = mcp_server.simulate_diversion("Rotterdam", "Hamburg", days=3, limit=3)
    assert out["fallback"]["name"] == "Hamburg" and len(out["shipments"]) == 3
    assert out["after"]["sla_breaches"] <= out["before"]["sla_breaches"]


def test_simulate_diversion_rejects_a_far_port():
    with pytest.raises(ToolError):
        mcp_server.simulate_diversion("Rotterdam", "Los Angeles")
