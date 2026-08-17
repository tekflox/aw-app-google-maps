"""Entrypoint referenced by aw-app.json's ``runtime.entrypoint``
("google_maps_app.plugin:GoogleMapsAppPlugin").

Three things on activate, and the order is not interesting here — unlike the
Workspace MCP app there is no subprocess, no venv and no port. The tools are
plain HTTPS calls to Google Maps Platform, served in-process.

The key is resolved through a callable rather than read once, so saving one in
Settings takes effect on the next tool call with no restart and no gateway
reload. See ``mcp/places.py``.
"""
from __future__ import annotations

import logging
import os

from . import mcp_config, routes as routes_mod
from .mcp import places

log = logging.getLogger("aw_apps.google-maps")


class GoogleMapsAppPlugin:
    async def activate(self, ctx) -> None:
        self.ctx = ctx

        places.set_api_key_resolver(lambda: ctx.secrets.read(routes_mod.SECRET_KEY) or "")

        ctx.routes.register(routes_mod.build_routes(ctx))

        port = int(os.environ.get("AW_PORT") or 9030)
        # Rebuilt every boot rather than persisted: the entry embeds this
        # process's hostname and API key, both of which change when the
        # workspace container is recreated.
        doc = mcp_config.write_mcp_json(ctx.package_dir, port)

        log.info(
            "aw-app-google-maps activated: mcp server=%s, tools=%s, api key=%s",
            sorted(doc["mcpServers"]),
            len(places.TOOLS_SCHEMA),
            "saved" if places.configured() else "NOT SET (tools will explain how)",
        )

    async def deactivate(self) -> None:
        log.info("aw-app-google-maps deactivated")
