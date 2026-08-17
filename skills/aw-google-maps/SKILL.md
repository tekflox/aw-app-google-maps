---
name: aw-google-maps
description: Find places and answer location questions — restaurants, bars, cafés and points of interest with ratings, review counts, price level, opening hours and recent reviews; full details for a place; address-to-coordinates geocoding; and live-traffic travel time between two points. Backed by Google Maps Platform through the aw-google-maps MCP server contributed by aw-app-google-maps. Use for any "where can I…", "is it open", "how long to get there", "what's the address" question.
---

# aw-google-maps — places, geocoding and ETAs

Four tools, gateway-prefixed `aw__aw_google_maps__*`. Ported from
agentic-workspace's `src/mcp/google_maps.py` (2026-08-17) with the request
formatting untouched — results look exactly as they did there.

**This is the Yelp-shaped tool.** There is no Yelp integration in this
workspace and none is needed: Google Places API (New) returns rating, review
count, price level, opening hours, phone, website and recent review text, which
covers the "find me a good X near Y, open now" question end to end.

## Which tool answers which question

| Question | Tool |
|---|---|
| "good sushi in Copacabana", "cafés near me" | `search_places` |
| "is it open, what's the phone, what do reviews say" | `get_place_details` |
| "what are the coordinates of this address" | `geocode_address` |
| "how long from here to there" | `get_route_eta` |

### The two-step flow that matters

`search_places` returns a `place_id` per result but only a summary — rating,
review count, price level, address, open-now. The good stuff (weekly hours,
phone, website, editorial summary, review text) is **only** in
`get_place_details`, which takes that `place_id`.

So the normal shape is two calls: search, pick, then details. Do not try to
answer "what time does it close on Sunday" from a search result — that field
isn't in the response at all, and guessing it is how a confident wrong answer
happens.

### Location bias is optional and worth using

`search_places` takes `lat`/`lon`/`radius_m` (default 5000 m). Without them
Google interprets the query text alone, which is fine for "sushi in Niterói RJ"
and poor for "sushi near me". If you have coordinates, pass them.

### `get_route_eta` needs coordinates, not names

All four of `origin_lat`, `origin_lon`, `dest_lat`, `dest_lon` are required.
Run `geocode_address` or `search_places` first if you only have an address or a
place name. `mode` is `driving` (default), `walking`, `bicycling` or `transit`;
driving uses live traffic and also reports the no-traffic baseline when the two
differ by 3+ minutes.

## Setup and failure modes

The key lives in the app's own secret store (Settings → Google Maps). It is a
plain **API key** — no OAuth, no consent screen, no expiry. That is the whole
reason this app works while the Google Workspace one waits on a consent flow.

The key's project needs three APIs enabled, and each maps to specific tools:

| API | Tools that break without it |
|---|---|
| **Places API (New)** | `search_places`, `get_place_details` |
| Geocoding API | `geocode_address` |
| Routes API | `get_route_eta` |

Note the **(New)**. The legacy Places API is a separate product; a key with only
that enabled fails every place call. This bit the monolith during setup, along
with Geocoding simply never having been switched on.

| Symptom | Cause |
|---|---|
| Every tool answers "No Google Maps API key configured" | No key saved. Settings → Google Maps. |
| Search fails but geocoding works (or vice versa) | That specific API isn't enabled on the key's project — see the table above. |
| Everything 403s with a working-looking key | Usually an HTTP-referer restriction. Calls come from this server, not a browser; restrict by API instead. |

`POST /api/apps/google-maps/test` runs a real search and returns what came
back — use it before concluding a key is fine, because a saved key and a
working key are not the same thing.
