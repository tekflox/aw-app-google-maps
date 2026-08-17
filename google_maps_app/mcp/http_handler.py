"""The ``aw-google-maps`` MCP server, over Streamable HTTP (``POST /mcp``).

The monolith served these same four tools over **stdio**, as a subprocess its
gateway respawned. That shape does not port: aw-mcp-gateway spawns stdio
children inside its own container, which has neither this app's code nor its
secret store. Serving MCP from this app's own already-authenticated route
sidesteps both — the gateway just makes an HTTP call. Same mechanism as
aw-app-notion's ``aw-kanban`` server.

The tool logic itself is untouched (see ``places.py``); this module is only the
JSON-RPC envelope around it.
"""
from __future__ import annotations

import logging

from fastapi.concurrency import run_in_threadpool

from . import places

log = logging.getLogger("aw_apps.google-maps")

SERVER_NAME = "aw-google-maps"
SERVER_VERSION = "1.0.0"

TOOLS_SCHEMA = places.TOOLS_SCHEMA

_DISPATCH = {
    "search_places": places._search_places,
    "get_place_details": places._get_place_details,
    "geocode_address": places._geocode_address,
    "get_route_eta": places._get_route_eta,
}

_NO_KEY = (
    "No Google Maps API key configured. Open the Google Maps app's Settings in "
    "this workspace and save one (Google Cloud → APIs & Services → Credentials). "
    "The key needs Places API (New), Geocoding API and Routes API enabled."
)


def _result(req_id, text: str, is_error: bool) -> dict:
    return {"jsonrpc": "2.0", "id": req_id,
            "result": {"content": [{"type": "text", "text": text}],
                       "isError": is_error}}


async def handle_request(request: dict) -> dict | None:
    method = request.get("method", "")
    req_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS_SCHEMA}}
    if method != "tools/call":
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": f"Unknown method: {method}"}}

    params = request.get("params") or {}
    name = params.get("name", "")
    args = params.get("arguments") or {}

    handler = _DISPATCH.get(name)
    if not handler:
        return _result(req_id, f"Unknown tool: {name}", True)

    # Checked here rather than in each handler: without a key every Google call
    # comes back as a generic 403, which reads like an API-not-enabled problem
    # and sends people to the wrong page.
    if not places.configured():
        return _result(req_id, _NO_KEY, True)

    try:
        # The handlers use blocking urllib, so they must not run on the event
        # loop — a slow Google response would stall every other app route in
        # this process.
        text, is_error = await run_in_threadpool(handler, args)
    except Exception as exc:  # noqa: BLE001 — last resort, must not 500 the route
        log.exception("google-maps MCP tool %s failed", name)
        return _result(req_id, f"{name} failed: {exc}", True)

    return _result(req_id, text, is_error)
