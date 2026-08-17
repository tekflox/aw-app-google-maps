"""This app's backend sub-app, mounted by the runtime at
``/api/apps/google-maps`` behind the workspace's IdentityGuard.

The API key goes to ``ctx.secrets`` via ``POST /settings``, never through the
generic config path — that would land it in plain, cloud-syncable app config.
The ``x-secret`` flag on ``google_maps_api_key`` in the manifest exists only so
the settings UI renders a password field. Same split as aw-app-notion's token.
"""
from __future__ import annotations

from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse, Response

from . import mcp_config
from .mcp import places

SECRET_KEY = "google_maps_api_key"


def build_routes(ctx) -> FastAPI:
    app = FastAPI(title="google-maps")

    @app.get("/status")
    async def status() -> dict:
        key = ctx.secrets.read(SECRET_KEY) or ""
        return {
            # "logged_in" is what windows/main.json's auth_status widget binds to.
            "logged_in": bool(key),
            "configured": bool(key),
            # Enough to tell two keys apart without revealing one.
            "key_hint": f"…{key[-6:]}" if len(key) > 6 else "",
            "tools": [t["name"] for t in places.TOOLS_SCHEMA],
            "mcp_server": mcp_config.SERVER_NAME,
        }

    @app.post("/settings")
    async def save_settings(data: dict = Body(...)) -> dict:
        key = (data.get(SECRET_KEY) or "").strip()
        if not key:
            return JSONResponse({"ok": False, "error": f"{SECRET_KEY} is required"},
                                status_code=400)
        ctx.secrets.write(SECRET_KEY, key)
        # No restart, no gateway reload: places.py resolves the key per call, so
        # the very next tool call already uses it.
        return {"ok": True, "logged_in": True, "configured": True}

    @app.post("/logout")
    async def clear_key() -> dict:
        ctx.secrets.delete(SECRET_KEY)
        return {"ok": True, "logged_in": False, "configured": False}

    @app.post("/test")
    async def test_key(data: dict = Body(default={})) -> dict:
        """Run a real search against Google so a saved key is proved, not assumed.

        Worth its own route: a key can be present and still fail — wrong project,
        Places API (New) not enabled, referer restrictions. All of those look
        identical to "configured" until something actually calls out.
        """
        if not places.configured():
            return JSONResponse({"ok": False, "error": "no API key saved"}, status_code=400)
        query = (data.get("query") or "coffee near Copacabana, Rio de Janeiro").strip()
        text, is_error = places._search_places({"query": query})
        return {"ok": not is_error, "query": query, "result": text[:1500]}

    @app.get("/mcp.json")
    async def mcp_json() -> dict:
        return {"mcpServers": mcp_config.build_mcp_servers()}

    # ------------------------------------------------------------------
    # MCP — Streamable HTTP, auto-discovered by aw-mcp-gateway's app-scan.
    # ------------------------------------------------------------------

    @app.post("/mcp")
    async def mcp_post(data: dict | list = Body(...)):
        from .mcp.http_handler import handle_request

        messages = data if isinstance(data, list) else [data]
        responses = []
        for m in messages:
            r = await handle_request(m)
            if r is not None:
                responses.append(r)
        if not responses:
            return Response(status_code=202)
        return JSONResponse(responses if isinstance(data, list) else responses[0])

    @app.get("/mcp")
    async def mcp_get():
        return Response(status_code=405)

    return app
