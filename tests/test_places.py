"""The ported tool layer: key resolution, dispatch, and the failure modes that
otherwise reach a user as a confusing Google error.

Deliberately no network: every test that would call out stubs urlopen.
"""
from __future__ import annotations

import asyncio
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google_maps_app import mcp_config  # noqa: E402
from google_maps_app.mcp import http_handler, places  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_key():
    places.set_api_key_resolver(lambda: "")
    yield
    places.set_api_key_resolver(lambda: "")


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_all_four_monolith_tools_survived_the_port():
    names = {t["name"] for t in places.TOOLS_SCHEMA}
    assert names == {"search_places", "get_place_details",
                     "geocode_address", "get_route_eta"}
    # Every advertised tool must actually dispatch somewhere.
    assert names == set(http_handler._DISPATCH)


def test_key_is_resolved_per_call_not_captured_at_import():
    """The monolith read the key once at process start because it was a
    short-lived subprocess. Here the module lives in a long-running process, so
    a key saved in Settings has to take effect without a restart."""
    box = {"k": ""}
    places.set_api_key_resolver(lambda: box["k"])
    assert not places.configured()
    box["k"] = "AIza-later"
    assert places.configured()
    assert places.api_key() == "AIza-later"


def test_api_key_survives_a_broken_resolver():
    places.set_api_key_resolver(lambda: 1 / 0)
    assert places.api_key() == ""
    assert not places.configured()


def test_whitespace_only_key_is_not_configured():
    places.set_api_key_resolver(lambda: "   ")
    assert not places.configured()


def test_missing_key_is_reported_before_calling_google(monkeypatch):
    """Without this, every call returns a generic 403 that reads like an
    API-not-enabled problem and sends people to the wrong console page."""
    called = []
    monkeypatch.setattr(places.urllib.request, "urlopen",
                        lambda *a, **k: called.append(1))
    resp = _run(http_handler.handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "search_places", "arguments": {"query": "sushi"}}}))
    assert resp["result"]["isError"] is True
    assert "No Google Maps API key configured" in resp["result"]["content"][0]["text"]
    assert not called, "must not reach Google without a key"


def test_unknown_tool_is_an_error_not_a_crash():
    resp = _run(http_handler.handle_request({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "nope", "arguments": {}}}))
    assert resp["result"]["isError"] is True
    assert "Unknown tool" in resp["result"]["content"][0]["text"]


def test_initialize_and_tools_list():
    init = _run(http_handler.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"}))
    assert init["result"]["serverInfo"]["name"] == "aw-google-maps"
    listed = _run(http_handler.handle_request(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}))
    assert len(listed["result"]["tools"]) == 4


def test_initialized_notification_gets_no_response():
    """A JSON-RPC notification has no id; answering one is a protocol error."""
    assert _run(http_handler.handle_request(
        {"jsonrpc": "2.0", "method": "notifications/initialized"})) is None


def test_unknown_method_is_a_jsonrpc_error():
    resp = _run(http_handler.handle_request(
        {"jsonrpc": "2.0", "id": 3, "method": "resources/list"}))
    assert resp["error"]["code"] == -32601


def test_handler_exception_becomes_a_tool_error(monkeypatch):
    places.set_api_key_resolver(lambda: "AIza-x")
    monkeypatch.setitem(http_handler._DISPATCH, "search_places",
                        lambda args: (_ for _ in ()).throw(RuntimeError("boom")))
    resp = _run(http_handler.handle_request({
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "search_places", "arguments": {"query": "x"}}}))
    assert resp["result"]["isError"] is True
    assert "boom" in resp["result"]["content"][0]["text"]


def test_search_places_formats_a_real_response(monkeypatch):
    places.set_api_key_resolver(lambda: "AIza-x")
    payload = {"places": [{
        "id": "PID1",
        "displayName": {"text": "Toruk Sushi"},
        "formattedAddress": "Av. Atlântica, Rio",
        "rating": 4.6, "userRatingCount": 5413,
        "priceLevel": "PRICE_LEVEL_MODERATE",
        "currentOpeningHours": {"openNow": True},
    }]}
    monkeypatch.setattr(places.urllib.request, "urlopen",
                        lambda *a, **k: _fake(payload))
    text, is_error = places._search_places({"query": "sushi"})
    assert is_error is False
    assert "Toruk Sushi" in text and "PID1" in text
    assert "4.6" in text and "5413 reviews" in text
    assert "$$" in text  # price level mapped, not leaked as PRICE_LEVEL_MODERATE
    assert "Open now" in text


def test_search_places_requires_a_query():
    places.set_api_key_resolver(lambda: "AIza-x")
    text, is_error = places._search_places({})
    assert is_error is True and "query is required" in text


def test_get_place_details_requires_a_place_id():
    places.set_api_key_resolver(lambda: "AIza-x")
    text, is_error = places._get_place_details({})
    assert is_error is True and "place_id is required" in text


def test_route_eta_rejects_a_bad_mode_and_missing_points():
    places.set_api_key_resolver(lambda: "AIza-x")
    text, is_error = places._get_route_eta({"origin_lat": 1, "origin_lon": 2,
                                            "dest_lat": 3, "dest_lon": 4,
                                            "mode": "teleport"})
    assert is_error is True and "mode must be one of" in text
    text, is_error = places._get_route_eta({"origin_lat": 1})
    assert is_error is True and "required" in text


def test_mcp_json_names_the_server_the_monolith_used(tmp_path):
    doc = mcp_config.write_mcp_json(str(tmp_path), 9030)
    entry = doc["mcpServers"]["aw-google-maps"]
    assert entry["type"] == "http"
    assert entry["url"].endswith(":9030/api/apps/google-maps/mcp")


def test_mcp_json_write_is_skipped_when_unchanged(tmp_path):
    """The gateway reloads on mtime, and each reload briefly drops every tool it
    proxies — an unconditional rewrite per activate is a reload loop."""
    mcp_config.write_mcp_json(str(tmp_path), 9030)
    before = (tmp_path / "mcp.json").stat().st_mtime_ns
    mcp_config.write_mcp_json(str(tmp_path), 9030)
    assert (tmp_path / "mcp.json").stat().st_mtime_ns == before
    mcp_config.write_mcp_json(str(tmp_path), 9999)
    assert (tmp_path / "mcp.json").stat().st_mtime_ns != before


class _fake:
    def __init__(self, payload): self._b = json.dumps(payload).encode()
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): return False
