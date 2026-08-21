---
repo: architecture
path: docs/architecture/aw-app-google-maps.md
source: generated
edited: false
checksum: sha256:f109f0ba615b57d6cbc895e2478212da307c925d6bb539ecbf7377a2925bd0d7
---
# Google Maps

- **repo**: aw-app-google-maps
- **layer**: app
- **technologies**: python
- **health** (derived): planned

Ports agentic-workspace's aw-google-maps MCP into aw-workspace: place search with ratings, reviews, price level and opening hours (the Yelp-shaped question — 'a good sushi place near here, open now'), plus full place details, address geocoding and live-traffic route ETAs. Google Maps Platform via a plain API key — no OAuth, no consent screen, nothing that expires.

## Connections
- `http` → **aw-workspace** — routes mounted at /api/apps/google-maps
- `stdio-mcp` → **mcp-gateway** — MCP surface aggregated by the gateway

## MCP tools
- `geocode_address`
- `get_place_details`
- `get_route_eta`
- `search_places`

## Requirements
_none documented_
