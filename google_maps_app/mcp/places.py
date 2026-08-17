"""Google Maps Platform tool logic, ported verbatim from agentic-workspace's
``src/mcp/google_maps.py`` (2026-08-17).

Two deliberate changes from the monolith, both about *where the key comes from*:

* The monolith read ``GOOGLE_MAPS_API_KEY`` into a module-level ``_API_KEY`` at
  import time, because it was a short-lived stdio subprocess the gateway
  respawned. Here the module is imported once into a long-running process, so
  the key is resolved **per call** through a callable the plugin installs
  (:func:`set_api_key_resolver`). A key saved in Settings therefore takes effect
  immediately, with no restart.
* The key lives in the app's secret store, not in a plaintext config file. The
  monolith kept it inline in ``src/config/mcp.json``.

The request/response formatting is untouched — same field masks, same output
text — so an agent that learned these tools on the monolith sees identical
results here.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

_api_key_resolver: Callable[[], str] = lambda: ""


def set_api_key_resolver(resolver: Callable[[], str]) -> None:
    """Install the callable that yields the current API key. Called once from
    ``plugin.activate``; every request below reads through it."""
    global _api_key_resolver
    _api_key_resolver = resolver


def api_key() -> str:
    try:
        return (_api_key_resolver() or "").strip()
    except Exception:
        return ""


def configured() -> bool:
    return bool(api_key())


_PLACES_BASE = "https://places.googleapis.com/v1"

_TRAVEL_MODES = {
    "driving": "DRIVE",
    "walking": "WALK",
    "bicycling": "BICYCLE",
    "transit": "TRANSIT",
}

_SEARCH_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.rating,"
    "places.userRatingCount,places.priceLevel,places.currentOpeningHours.openNow"
)
_DETAILS_FIELD_MASK = (
    "id,displayName,formattedAddress,nationalPhoneNumber,rating,userRatingCount,"
    "priceLevel,currentOpeningHours.weekdayDescriptions,websiteUri,googleMapsUri,"
    "editorialSummary,reviews"
)

_PRICE_LEVELS = {
    "PRICE_LEVEL_FREE": "free",
    "PRICE_LEVEL_INEXPENSIVE": "$",
    "PRICE_LEVEL_MODERATE": "$$",
    "PRICE_LEVEL_EXPENSIVE": "$$$",
    "PRICE_LEVEL_VERY_EXPENSIVE": "$$$$",
}


def _places_post(path: str, body: dict, field_mask: str) -> tuple[dict, bool]:
    req = urllib.request.Request(
        f"{_PLACES_BASE}{path}",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key(),
            "X-Goog-FieldMask": field_mask,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read()), False
    except urllib.error.HTTPError as exc:
        try:
            err = json.loads(exc.read())
        except Exception:
            err = {"error": {"message": str(exc)}}
        return {"detail": err.get("error", {}).get("message", str(exc))}, True
    except Exception as exc:
        return {"detail": str(exc)}, True


def _places_get(path: str, field_mask: str) -> tuple[dict, bool]:
    req = urllib.request.Request(
        f"{_PLACES_BASE}{path}",
        headers={"X-Goog-Api-Key": api_key(), "X-Goog-FieldMask": field_mask},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read()), False
    except urllib.error.HTTPError as exc:
        try:
            err = json.loads(exc.read())
        except Exception:
            err = {"error": {"message": str(exc)}}
        return {"detail": err.get("error", {}).get("message", str(exc))}, True
    except Exception as exc:
        return {"detail": str(exc)}, True


def _get(url: str, params: dict) -> tuple[dict, bool]:
    params = {**params, "key": api_key()}
    full_url = f"{url}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(full_url, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return {"detail": str(exc)}, True
    except Exception as exc:
        return {"detail": str(exc)}, True

    status = data.get("status")
    if status not in ("OK", "ZERO_RESULTS"):
        return {"detail": data.get("error_message") or status}, True
    return data, False


def _search_places(args: dict) -> tuple[str, bool]:
    query = (args.get("query") or "").strip()
    if not query:
        return "query is required", True

    body = {"textQuery": query}
    lat = args.get("lat")
    lon = args.get("lon")
    if lat is not None and lon is not None:
        body["locationBias"] = {
            "circle": {
                "center": {"latitude": lat, "longitude": lon},
                "radius": float(args.get("radius_m") or 5000),
            }
        }

    data, is_error = _places_post("/places:searchText", body, _SEARCH_FIELD_MASK)
    if is_error:
        return f"Places search failed: {data.get('detail', data)}", True

    results = data.get("places") or []
    if not results:
        return f"No places found for '{query}'.", False

    lines = [f"Results for '{query}':"]
    for place in results[:10]:
        name = place.get("displayName", {}).get("text", "?")
        rating = place.get("rating")
        ratings_total = place.get("userRatingCount")
        price = place.get("priceLevel")
        line = f"- {name} (place_id: {place.get('id')})"
        if rating is not None:
            line += f" — {rating}★"
            if ratings_total:
                line += f" ({ratings_total} reviews)"
        if price and price in _PRICE_LEVELS:
            line += f" — {_PRICE_LEVELS[price]}"
        if place.get("formattedAddress"):
            line += f"\n  {place['formattedAddress']}"
        open_now = place.get("currentOpeningHours", {}).get("openNow")
        if open_now is not None:
            line += f"\n  {'Open now' if open_now else 'Closed now'}"
        lines.append(line)
    return "\n".join(lines), False


def _get_place_details(args: dict) -> tuple[str, bool]:
    place_id = (args.get("place_id") or "").strip()
    if not place_id:
        return "place_id is required", True

    data, is_error = _places_get(f"/places/{place_id}", _DETAILS_FIELD_MASK)
    if is_error:
        return f"Place details failed: {data.get('detail', data)}", True

    if not data:
        return f"No details found for place_id '{place_id}'.", False

    lines = [data.get("displayName", {}).get("text", "?")]
    if data.get("formattedAddress"):
        lines.append(f"Address: {data['formattedAddress']}")
    if data.get("nationalPhoneNumber"):
        lines.append(f"Phone: {data['nationalPhoneNumber']}")
    if data.get("rating") is not None:
        lines.append(f"Rating: {data['rating']}★ ({data.get('userRatingCount', 0)} reviews)")
    price = data.get("priceLevel")
    if price and price in _PRICE_LEVELS:
        lines.append(f"Price level: {_PRICE_LEVELS[price]}")
    hours = data.get("currentOpeningHours", {}).get("weekdayDescriptions")
    if hours:
        lines.append("Hours:\n  " + "\n  ".join(hours))
    if data.get("websiteUri"):
        lines.append(f"Website: {data['websiteUri']}")
    if data.get("googleMapsUri"):
        lines.append(f"Google Maps: {data['googleMapsUri']}")
    if data.get("editorialSummary", {}).get("text"):
        lines.append(f"Summary: {data['editorialSummary']['text']}")
    reviews = data.get("reviews") or []
    if reviews:
        lines.append("Recent reviews:")
        for review in reviews[:5]:
            author = review.get("authorAttribution", {}).get("displayName", "?")
            text = review.get("text", {}).get("text", "")[:200]
            lines.append(f"  - {review.get('rating')}★ {author}: {text}")
    return "\n".join(lines), False


def _geocode_address(args: dict) -> tuple[str, bool]:
    address = (args.get("address") or "").strip()
    if not address:
        return "address is required", True

    data, is_error = _get(_GEOCODE_URL, {"address": address})
    if is_error:
        return f"Geocoding failed: {data.get('detail', data)}", True

    results = data.get("results") or []
    if not results:
        return f"No geocoding results for '{address}'.", False

    result = results[0]
    location = result.get("geometry", {}).get("location", {})
    return (
        f"Address: {result.get('formatted_address')}\n"
        f"Coordinates: {location.get('lat')}, {location.get('lng')}"
    ), False


def _get_route_eta(args: dict) -> tuple[str, bool]:
    origin_lat, origin_lon = args.get("origin_lat"), args.get("origin_lon")
    dest_lat, dest_lon = args.get("dest_lat"), args.get("dest_lon")
    if None in (origin_lat, origin_lon, dest_lat, dest_lon):
        return "origin_lat/origin_lon/dest_lat/dest_lon are all required.", True

    mode = (args.get("mode") or "driving").strip().lower()
    if mode not in _TRAVEL_MODES:
        return f"mode must be one of: {', '.join(_TRAVEL_MODES)}", True

    body = {
        "origin": {"location": {"latLng": {"latitude": origin_lat, "longitude": origin_lon}}},
        "destination": {"location": {"latLng": {"latitude": dest_lat, "longitude": dest_lon}}},
        "travelMode": _TRAVEL_MODES[mode],
    }
    if mode == "driving":
        body["routingPreference"] = "TRAFFIC_AWARE"

    req = urllib.request.Request(
        _ROUTES_URL,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key(),
            "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.staticDuration",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            err = json.loads(exc.read())
        except Exception:
            err = {"error": {"message": str(exc)}}
        return f"Route ETA failed: {err.get('error', {}).get('message', str(exc))}", True
    except Exception as exc:
        return f"Route ETA failed: {exc}", True

    routes = data.get("routes") or []
    if not routes:
        return f"No route found for {mode} between those points.", False

    route = routes[0]
    duration_s = int((route.get("duration") or "0s").rstrip("s"))
    distance_m = route.get("distanceMeters", 0)
    mins = round(duration_s / 60)
    km = round(distance_m / 1000, 1)
    lines = [f"{mode.capitalize()} ETA: ~{mins} min ({km} km)"]
    static_s = route.get("staticDuration")
    if static_s:
        static_mins = round(int(static_s.rstrip("s")) / 60)
        if mode == "driving" and abs(static_mins - mins) >= 3:
            lines.append(f"(no traffic: ~{static_mins} min)")
    return " ".join(lines), False


TOOLS_SCHEMA = [
    {
        "name": "search_places",
        "description": (
            "Search for places (restaurants, bars, points of interest) by free-text "
            "query, e.g. 'sushi bars in Niterói RJ' or 'coffee shops near Copacabana'. "
            "Returns name, rating, review count, price level, address, and place_id "
            "for each result. Optionally bias results toward a lat/lon."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text search query."},
                "lat": {"type": "number", "description": "Optional latitude to bias results toward."},
                "lon": {"type": "number", "description": "Optional longitude to bias results toward."},
                "radius_m": {"type": "number", "description": "Bias radius in meters (default 5000)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_place_details",
        "description": (
            "Get full details for a place by its place_id (from search_places): "
            "address, phone, rating, price level, opening hours, website, and recent "
            "reviews."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "place_id": {"type": "string", "description": "The place_id returned by search_places."},
            },
            "required": ["place_id"],
        },
    },
    {
        "name": "geocode_address",
        "description": "Convert a free-text address into a formatted address and lat/lon coordinates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "description": "Free-text address to geocode."},
            },
            "required": ["address"],
        },
    },
    {
        "name": "get_route_eta",
        "description": (
            "Get the estimated travel time and distance between two points via "
            "Google's Routes API. Driving mode uses live traffic and also reports "
            "the no-traffic baseline when it differs meaningfully. Takes "
            "coordinates, not names — run geocode_address or search_places first "
            "if you only have an address or a place name."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "origin_lat": {"type": "number", "description": "Origin latitude."},
                "origin_lon": {"type": "number", "description": "Origin longitude."},
                "dest_lat": {"type": "number", "description": "Destination latitude."},
                "dest_lon": {"type": "number", "description": "Destination longitude."},
                "mode": {
                    "type": "string",
                    "enum": ["driving", "walking", "bicycling", "transit"],
                    "description": "Travel mode (default: driving).",
                },
            },
            "required": ["origin_lat", "origin_lon", "dest_lat", "dest_lon"],
        },
    },
]
