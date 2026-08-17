# aw-app-google-maps

Place search, place details, address geocoding and live-traffic route ETAs for
every agent in this workspace.

Ports agentic-workspace's `aw-google-maps` MCP server (`src/mcp/google_maps.py`).
4 tools, gateway-prefixed `aw__aw_google_maps__*`.

**This is the Yelp-shaped tool.** Google Places API (New) returns rating, review
count, price level, opening hours, phone, website and recent review text — which
covers "find me a good X near Y, open now" end to end. No Yelp integration
exists in this workspace and none is needed.

## Install

```bash
aw-workspace-cli marketplace install google-maps
```

Then open **Google Maps** in the Apps grid and save a Maps Platform API key.

## The key

A plain **API key** — no OAuth, no consent screen, nothing that expires. That is
the whole reason this app works standalone while aw-app-google-workspace-mcp
waits on a Google consent flow.

Its project needs three APIs enabled, and each maps to specific tools:

| API | Tools |
|---|---|
| **Places API (New)** | `search_places`, `get_place_details` |
| Geocoding API | `geocode_address` |
| Routes API | `get_route_eta` |

Note the *(New)* — the legacy Places API is a different product, and a key with
only that one fails every place call.

Restrict the key by API, **not** by HTTP referer: the calls come from this
server, not a browser.

## Routes

Under `/api/apps/google-maps`, behind the workspace IdentityGuard.

| Route | Purpose |
|---|---|
| `GET /status` | Configured, key hint, tool list. |
| `POST /settings` | Save the API key (secret store). Effective on the next call — no restart. |
| `POST /logout` | Forget the key. |
| `POST /test` | Run a real search, so a saved key is proved rather than assumed. |
| `POST /mcp` | The MCP server itself (Streamable HTTP), scanned by MCP Gateway. |
| `GET /mcp.json` | What the gateway will see. |

## Tests

```bash
python3 tests/validate_manifest.py aw-app.json
python3 -m pytest tests -q
```
