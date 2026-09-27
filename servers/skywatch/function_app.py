"""
Server 2 · "skywatch" — what is flying over Hanau RIGHT NOW.
Shows: public API wrapped as a tool, IMAGE content (a rendered radar PNG for any client),
and an MCP APP (interactive radar widget rendered inline in VS Code, M365 Copilot and other MCP Apps hosts).
Data: adsb.lol public ADS-B API (no key). Fallback: OpenSky Network anonymous API.
"""
import base64
import io
import json
import logging
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Union

import azure.functions as func
import requests
from mcp.types import CallToolResult, ImageContent, TextContent

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

HOME_LAT = float(os.environ.get("HOME_LAT", "50.1329"))
HOME_LON = float(os.environ.get("HOME_LON", "8.9169"))
HOME_NAME = os.environ.get("HOME_NAME", "Congress Park Hanau")

RADAR_UI_URI = "ui://skywatch/radar.html"
TOOL_METADATA = json.dumps({"ui": {"resourceUri": RADAR_UI_URI}})
RESOURCE_METADATA = json.dumps({"ui": {"prefersBorder": True}})


# ------------------------------------------------------------------ data
def _fetch_adsb(lat: float, lon: float, radius_nm: int) -> List[dict]:
    """adsb.lol v2: aircraft within radius (nautical miles) of a point."""
    r = requests.get(f"https://api.adsb.lol/v2/point/{lat}/{lon}/{int(radius_nm)}",
                     headers={"User-Agent": "cdc-skywatch-mcp/1.0"}, timeout=10)
    r.raise_for_status()
    out = []
    for ac in r.json().get("ac", []):
        if ac.get("lat") is None or ac.get("lon") is None:
            continue
        out.append({
            "callsign": (ac.get("flight") or "").strip() or ac.get("r") or ac.get("hex"),
            "registration": ac.get("r"),
            "type": ac.get("t"),
            "altitude_ft": ac.get("alt_baro") if isinstance(ac.get("alt_baro"), (int, float)) else 0,
            "ground_speed_kt": ac.get("gs"),
            "track_deg": ac.get("track"),
            "lat": ac["lat"],
            "lon": ac["lon"],
            "distance_km": round(_haversine_km(lat, lon, ac["lat"], ac["lon"]), 1),
            "bearing_deg": round(_bearing(lat, lon, ac["lat"], ac["lon"])),
        })
    return sorted(out, key=lambda a: a["distance_km"])


def _fetch_opensky(lat: float, lon: float, radius_nm: int) -> List[dict]:
    d = radius_nm * 1.852 / 111.0  # degrees, rough
    r = requests.get("https://opensky-network.org/api/states/all",
                     params={"lamin": lat - d, "lamax": lat + d, "lomin": lon - d, "lomax": lon + d}, timeout=10)
    r.raise_for_status()
    out = []
    for s in r.json().get("states") or []:
        if s[6] is None or s[5] is None:
            continue
        out.append({
            "callsign": (s[1] or "").strip() or s[0], "registration": None, "type": None,
            "altitude_ft": round((s[7] or 0) * 3.281), "ground_speed_kt": round((s[9] or 0) * 1.944),
            "track_deg": s[10], "lat": s[6], "lon": s[5],
            "distance_km": round(_haversine_km(lat, lon, s[6], s[5]), 1),
            "bearing_deg": round(_bearing(lat, lon, s[6], s[5])),
        })
    return sorted(out, key=lambda a: a["distance_km"])


def _haversine_km(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = 0.5 - math.cos((lat2 - lat1) * p) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2
    return 12742 * math.asin(math.sqrt(a))


def _bearing(lat1, lon1, lat2, lon2):
    y = math.sin(math.radians(lon2 - lon1)) * math.cos(math.radians(lat2))
    x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(math.radians(lon2 - lon1))
    return (math.degrees(math.atan2(y, x)) + 360) % 360


# ------------------------------------------------------------------ routes (ADS-B has positions, not routes)
_ROUTE_CACHE: dict = {}          # callsign -> (fetched_at, route | None); a callsign's route rarely changes within a day
_ROUTE_TTL = 6 * 3600


def _route(callsign: str):
    """Origin/destination by callsign from adsbdb.com (free, no key). Best effort: None when unknown or slow."""
    cs = (callsign or "").strip().upper()
    if not cs or " " in cs or len(cs) < 3:
        return None
    hit = _ROUTE_CACHE.get(cs)
    if hit and time.time() - hit[0] < _ROUTE_TTL:
        return hit[1]
    route = None
    try:
        r = requests.get(f"https://api.adsbdb.com/v0/callsign/{cs}", timeout=4, headers={"User-Agent": "cdc-skywatch-mcp/1.1"})
        fr = r.json().get("response", {}).get("flightroute") if r.ok else None
        if isinstance(fr, dict):
            o, d = fr.get("origin") or {}, fr.get("destination") or {}
            route = {"airline": (fr.get("airline") or {}).get("name"),
                     "from": o.get("iata_code") or o.get("icao_code"), "from_city": o.get("municipality"),
                     "to": d.get("iata_code") or d.get("icao_code"), "to_city": d.get("municipality")}
    except Exception as ex:  # noqa: BLE001
        logging.info("route lookup %s failed: %s", cs, ex)
    _ROUTE_CACHE[cs] = (time.time(), route)
    return route


def _with_routes(aircraft: List[dict], n: int = 15) -> List[dict]:
    """Adds airline + from/to to the n nearest aircraft (parallel, ~1 s cold, instant when cached)."""
    head = aircraft[:n]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for a, route in zip(head, pool.map(lambda a: _route(a["callsign"]), head)):
            a.update(route or {"airline": None, "from": None, "from_city": None, "to": None, "to_city": None})
    return aircraft


def _route_text(a: dict) -> str:
    if not a.get("from") and not a.get("to"):
        return ""
    return f", {a.get('from_city') or a.get('from') or '?'} → {a.get('to_city') or a.get('to') or '?'}"


def _overhead(lat, lon, radius_nm):
    try:
        return _fetch_adsb(lat, lon, radius_nm), "adsb.lol"
    except Exception as ex:  # noqa: BLE001
        logging.warning("adsb.lol failed (%s), falling back to OpenSky", ex)
        return _fetch_opensky(lat, lon, radius_nm), "opensky"


# ------------------------------------------------------------------ tools
@app.mcp_tool(metadata=TOOL_METADATA)
@app.mcp_tool_property(arg_name="radius_nm", description="Search radius in nautical miles (default 25, max 100).", is_required=False)
@app.mcp_tool_property(arg_name="lat", description="Latitude. Defaults to the conference venue.", is_required=False)
@app.mcp_tool_property(arg_name="lon", description="Longitude. Defaults to the conference venue.", is_required=False)
def flights_overhead(radius_nm: int = 25, lat: float = None, lon: float = None) -> CallToolResult:
    """What is flying over us right now? Live ADS-B positions within a radius of a point, with airline and route (from → to) for the nearest aircraft. Renders an interactive radar when the client supports MCP Apps."""
    lat = HOME_LAT if lat is None else float(lat)
    lon = HOME_LON if lon is None else float(lon)
    radius_nm = max(5, min(int(radius_nm or 25), 100))
    logging.info("flights_overhead radius_nm=%s lat=%s lon=%s", radius_nm, lat, lon)
    aircraft, source = _overhead(lat, lon, radius_nm)
    aircraft = _with_routes(aircraft)
    payload = {
        "center": {"name": HOME_NAME if (lat, lon) == (HOME_LAT, HOME_LON) else "custom", "lat": lat, "lon": lon},
        "radius_nm": radius_nm, "source": source, "count": len(aircraft), "aircraft": aircraft[:60],
    }
    nearest = aircraft[0] if aircraft else None
    text = (f"{len(aircraft)} aircraft within {radius_nm} NM of {payload['center']['name']} (source: {source})."
            + (f" Nearest: {nearest.get('airline') or nearest['callsign']} {nearest['callsign']} ({nearest['type'] or 'unknown type'}{_route_text(nearest)}) "
               f"at {nearest['altitude_ft']} ft, {nearest['distance_km']} km away, bearing {nearest['bearing_deg']}°." if nearest else "")
            + " Routes (from/to) come from adsbdb.com by callsign and can be outdated for charter or ad-hoc flights.")
    return CallToolResult(content=[TextContent(type="text", text=text)], structured_content=payload)


@app.mcp_tool()
@app.mcp_tool_property(arg_name="radius_nm", description="Radius in nautical miles (default 25).", is_required=False)
def radar_image(radius_nm: int = 25) -> List[Union[TextContent, ImageContent]]:  # typed list → real content blocks
    """Renders a radar-style PNG of aircraft around the venue. For clients that cannot show MCP Apps."""
    from PIL import Image, ImageDraw
    radius_nm = max(5, min(int(radius_nm or 25), 100))
    logging.info("radar_image radius_nm=%s", radius_nm)
    aircraft, source = _overhead(HOME_LAT, HOME_LON, radius_nm)
    size, c, r = 640, 320, 290
    img = Image.new("RGB", (size, size), (28, 17, 8))
    d = ImageDraw.Draw(img)
    for k in (1, 2, 3, 4):
        rr = r * k / 4
        d.ellipse([c - rr, c - rr, c + rr, c + rr], outline=(212, 70, 12), width=1)
    d.line([c, c - r, c, c + r], fill=(90, 50, 30)); d.line([c - r, c, c + r, c], fill=(90, 50, 30))
    max_km = radius_nm * 1.852
    for a in aircraft:
        rad = math.radians(a["bearing_deg"]); dist = min(a["distance_km"], max_km) / max_km * r
        x, y = c + dist * math.sin(rad), c - dist * math.cos(rad)
        d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(240, 138, 75))
        d.text((x + 6, y - 6), a["callsign"], fill=(251, 244, 236))
    d.text((10, 10), f"{HOME_NAME} · {radius_nm} NM · {len(aircraft)} aircraft · {source}", fill=(251, 244, 236))
    buf = io.BytesIO(); img.save(buf, format="PNG")
    return [
        TextContent(type="text", text=f"Radar: {len(aircraft)} aircraft within {radius_nm} NM."),
        ImageContent(type="image", data=base64.b64encode(buf.getvalue()).decode(), mimeType="image/png"),
    ]


@app.mcp_tool(use_result_schema=True)  # dict → JSON text + structuredContent (without it: Python repr)
@app.mcp_tool_property(arg_name="callsign", description="Flight callsign, e.g. DLH400, or a registration like D-AIXC.", is_required=True)
def find_flight(callsign: str) -> dict:
    """Locate one aircraft by callsign or registration (within 250 NM of the venue)."""
    logging.info("find_flight callsign=%s", callsign)
    aircraft, source = _overhead(HOME_LAT, HOME_LON, 250)
    key = callsign.strip().upper().replace("-", "")
    for a in aircraft:
        if key in (a["callsign"] or "").upper().replace("-", "") or key == (a.get("registration") or "").upper().replace("-", ""):
            return {"found": True, "source": source, **_with_routes([a], 1)[0]}
    return {"found": False, "source": source, "searched": len(aircraft), "hint": "Try the ICAO callsign (DLH, not LH)."}


# ------------------------------------------------------------------ MCP App UI + resources + prompt
@app.mcp_resource_trigger(
    arg_name="context",
    uri=RADAR_UI_URI,
    resource_name="SkyWatch Radar",
    description="Interactive radar widget for the flights_overhead tool (MCP App).",
    mime_type="text/html;profile=mcp-app",
    metadata=RESOURCE_METADATA,
)
def radar_widget(context) -> str:
    logging.info("resource %s", RADAR_UI_URI)
    f = Path(__file__).parent / "app" / "dist" / "index.html"
    if f.exists():
        return f.read_text(encoding="utf-8")
    return "<html><body><p>Widget not built. Run <code>npm run build</code> in servers/skywatch/app.</p></body></html>"


NEARBY_AIRPORTS = [
    {"icao": "EDDF", "iata": "FRA", "name": "Frankfurt am Main", "lat": 50.0333, "lon": 8.5706, "note": "Most traffic overhead is FRA arrivals on 07/25 or departures."},
    {"icao": "EDFH", "iata": "HHN", "name": "Frankfurt-Hahn", "lat": 49.9487, "lon": 7.2639},
    {"icao": "EDFE", "iata": None, "name": "Frankfurt-Egelsbach", "lat": 49.9600, "lon": 8.6414, "note": "General aviation."},
    {"icao": "ETOU", "iata": "WIE", "name": "Wiesbaden Army Airfield", "lat": 50.0498, "lon": 8.3254},
]


@app.mcp_resource_trigger(
    arg_name="context",
    uri="airports://nearby",
    resource_name="Nearby airports",
    description="Airports around the venue with ICAO/IATA codes, for interpreting what you see overhead.",
    mime_type="application/json",
)
def nearby_airports(context) -> str:
    return json.dumps(NEARBY_AIRPORTS)


@app.mcp_prompt_trigger(
    arg_name="context",
    prompt_name="plane_spotter",
    description="Turn the live radar into a 30-second plane-spotting commentary for the audience.",
)
def plane_spotter(context: func.PromptInvocationContext) -> str:
    logging.info("prompt plane_spotter")
    return f"""You are a witty plane-spotting commentator at a tech conference in Hanau.
1. Call flights_overhead with radius_nm 30.
2. Use the routes (from → to) in the result, and these nearby airports (also the MCP resource airports://nearby), to say where the three nearest aircraft are coming from or going to:
{json.dumps(NEARBY_AIRPORTS)}
3. Give a 30-second commentary: nearest aircraft, highest, fastest, and one fun fact about the aircraft type.
Keep it light; the audience is drinking coffee."""
