"""
Demo 1 · ONE file, two lives — the CDC-Germany 2026 concierge.
  - On my laptop: VS Code starts it as a child process over stdio. Zero infrastructure, exactly ONE user — me.
  - On Azure Functions: the SAME file, unchanged, deployed with `azd deploy concierge` as a self-hosted MCP server.
    The Functions host starts it (host.json: configurationProfile mcp-custom-handler) and proxies /mcp to it.
Data: the live conference agenda (run.events public API), 10-minute cache, optional local snapshot (cdc_agenda.json) when the Wi-Fi dies.
"""
import json
import os
import random
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from mcp.server.mcpserver import MCPServer  # mcp 2.x: FastMCP was renamed MCPServer

mcp = MCPServer("cdc-concierge", instructions=(
    "Concierge for the Cloud & Datacenter Conference Germany 2026 (30 Sep – 1 Oct, Congress Park Hanau). "
    "Use find_session for 'where/when is X', whats_on for 'what's happening now/at 14:00', breaks for lunch/coffee/"
    "evening event, speaker_info for people, plan_my_day for recommendations. Times are Europe/Berlin."))

TZ = ZoneInfo("Europe/Berlin")
API = "https://api.runevents.net/api"
SLUG = "cloud-datacenter-conference-germany"
MY_SESSION = os.environ.get("MY_SESSION_TITLE", "")  # exact title of YOUR talk in the agenda (optional)
_cache: dict = {"at": 0.0, "data": None, "source": ""}


# ------------------------------------------------------------------ data
def _get(path: str):
    with urllib.request.urlopen(f"{API}/{path}?eventSlug={SLUG}", timeout=6) as r:
        return json.load(r)["data"]


def _data() -> dict:
    """Live agenda from the conference system (cached 10 min); optional local snapshot if the API/Wi-Fi is down."""
    if _cache["data"] and time.time() - _cache["at"] < 600:
        return _cache["data"]
    try:
        sessions = _get("sessions-and-speakers/external-sessions")
        data = {
            "agenda": _get("agenda/external-agenda"),
            "sessions": [{"id": s["id"], "title": s["title"], "abstract": s.get("abstract") or "", "roomName": s["roomName"],
                          "speakers": [x["name"] for x in s["speakers"]], "labels": [lb["name"] for lb in s["labels"]]} for s in sessions],
            "breaks": _get("agenda/external-agenda-non-content-blocks"),
            "speakers": [{"name": p["name"], "tagline": p.get("tagline"), "company": p.get("company"), "bio": p.get("biography") or ""}
                         for p in _get("sessions-and-speakers/external-speakers")],
        }
        _cache.update(at=time.time(), data=data, source="live (run.events)")
    except Exception:  # noqa: BLE001 — venue Wi-Fi: fall back to a local snapshot if you saved one
        snap = Path(__file__).parent / "cdc_agenda.json"  # optional: save the API responses here for offline use
        if not snap.exists():
            raise RuntimeError("agenda API unreachable and no local snapshot (cdc_agenda.json)")
        data = json.loads(snap.read_text(encoding="utf-8"))
        _cache.update(at=time.time(), data=data, source=f"snapshot {data.get('snapshot', '')}")
    return data


def _local(ts: str) -> datetime:
    # the API writes local conference time with a trailing Z; the event's timeZone is Europe/Berlin
    return datetime.fromisoformat(ts.rstrip("Z")).replace(tzinfo=TZ)


def _slots() -> list[dict]:
    """Every agenda slot, resolved: session or break, with local start/end, room, speakers, track."""
    d = _data()
    sessions = {s["id"]: s for s in d["sessions"]}
    breaks = {b["id"]: b for b in d["breaks"]}
    out = []
    for a in d["agenda"]:
        start, end = _local(a["startDate"]), _local(a["endDate"])
        base = {"day": start.strftime("%a %d %b"), "start": start.strftime("%H:%M"), "end": end.strftime("%H:%M"),
                "room": a["roomName"], "_start": start, "_end": end}
        if a.get("sessionId") in sessions:
            s = sessions[a["sessionId"]]
            out.append({**base, "kind": "session", "title": s["title"], "speakers": s["speakers"], "track": ", ".join(s["labels"])})
        elif a.get("agendaNonContentBlockId") in breaks:
            out.append({**base, "kind": "break", "title": breaks[a["agendaNonContentBlockId"]]["name"]})
    return sorted(out, key=lambda x: (x["_start"], x["room"]))


def _public(slots: list[dict]) -> list[dict]:
    return [{k: v for k, v in s.items() if not k.startswith("_")} for s in slots]


def _now(at: str = "") -> datetime:
    """'' = real time. For planning/testing: '11:10' (Thursday 1 Oct), 'wed 14:00', or an ISO timestamp."""
    if not at:
        return datetime.now(TZ)
    at = at.strip().lower()
    day = datetime(2026, 10, 1, tzinfo=TZ)
    if at[:3] in ("wed", "mi ", "mit", "tue"):
        day, at = datetime(2026, 9, 30, tzinfo=TZ), at.split(" ", 1)[-1]
    elif at[:3] in ("thu", "do ", "don"):
        at = at.split(" ", 1)[-1]
    try:
        if "t" in at or "-" in at:
            return datetime.fromisoformat(at).replace(tzinfo=TZ)
        h, m = (int(x) for x in at.replace(".", ":").split(":"))
        return day.replace(hour=h, minute=m)
    except ValueError:
        return datetime.now(TZ)


def _mins(delta: timedelta) -> int:
    return int(delta.total_seconds() // 60)


# ------------------------------------------------------------------ tools
@mcp.tool()
def find_session(query: str) -> dict:
    """Where and when is a session? Search the CDC-Germany 2026 agenda by speaker name, title words or track
    (AI, CLOUD, HYBRID, SECURITY, ON-PREMISES, INSIGHTS). Returns day, time, room, speakers and track."""
    q = query.lower().strip()
    hits = [s for s in _slots() if s["kind"] == "session"
            and (q in s["title"].lower() or any(q in sp.lower() for sp in s["speakers"]) or q in s["track"].lower()
                 or all(w in (s["title"] + " " + " ".join(s["speakers"])).lower() for w in q.split()))]
    return {"query": query, "matches": _public(hits[:12]), "count": len(hits), "data": _cache["source"]}


@mcp.tool()
def whats_on(at: str = "") -> dict:
    """What's happening right now (or at a given time) and what's next, room by room. `at` is optional for
    planning or testing: '14:00' (Thursday), 'wed 11:15' or an ISO timestamp."""
    now, slots = _now(at), _slots()
    running = [s for s in slots if s["_start"] <= now < s["_end"]]
    upcoming = [s for s in slots if s["_start"] > now]
    nxt = [s for s in upcoming if s["_start"] == upcoming[0]["_start"]] if upcoming else []
    note = ""
    if now < slots[0]["_start"]:
        note = f"The conference hasn't started yet: doors open {slots[0]['day']} {slots[0]['start']} ({_mins(slots[0]['_start'] - now) // 1440} days to go)."
    elif not upcoming and not running:
        note = "CDC-Germany 2026 is over. See you next year!"
    return {"time": now.strftime("%a %d %b %H:%M"), "now": _public(running), "next": _public(nxt), "note": note, "data": _cache["source"]}


@mcp.tool()
def breaks(kind: str = "") -> dict:
    """Lunch, coffee, the evening event, the whisky-tasting Q&A, opening, closing & raffle: when and where.
    kind: 'lunch', 'coffee', 'evening', 'whisky', 'closing', or empty for all. Also says how long until the next one."""
    alias = {"lunch": "mittag", "mittag": "mittag", "food": "mittag", "coffee": "kaffee", "kaffee": "kaffee",
             "evening": "abend", "party": "abend", "dinner": "abend", "whisky": "wisky", "whiskey": "wisky",
             "raffle": "verlosung", "closing": "closing", "opening": "opening", "panel": "podium"}
    key = alias.get(kind.lower().strip(), kind.lower().strip())
    now = _now()
    items = [s for s in _slots() if s["kind"] == "break" and (not key or key in s["title"].lower())]
    upcoming = [s for s in items if s["_end"] > now]
    nxt = upcoming[0] if upcoming else None
    return {"breaks": _public(items), "next": _public([nxt])[0] if nxt else None,
            "minutes_until_next": max(0, _mins(nxt["_start"] - now)) if nxt else None,
            "note": "The official agenda lists breaks under the Paul-Hindemith Saal (plenary hall); for the exact catering spot ask the registration desk."}


@mcp.tool()
def speaker_info(name: str) -> dict:
    """Who is this speaker? Tagline, company, short bio and their sessions (time + room)."""
    n = name.lower().strip()
    people = [p for p in _data()["speakers"] if n in p["name"].lower()]
    sessions = [s for s in _slots() if s["kind"] == "session" and any(n in sp.lower() for sp in s["speakers"])]
    return {"speakers": [{**p, "bio": p["bio"][:400]} for p in people[:5]], "sessions": _public(sessions)}


@mcp.tool()
def plan_my_day(interests: str, day: str = "thu") -> dict:
    """Builds a personal agenda: for every time slot of the day, the session that best matches your interests
    (free text, e.g. 'AI agents, security, Azure'). day: 'wed' (30 Sep) or 'thu' (1 Oct)."""
    date = "30" if day.lower().startswith(("wed", "mi", "30")) else "01"
    words = [w.strip().lower() for w in interests.replace(",", " ").split() if len(w) > 2]
    by_time: dict = {}
    for s in _slots():
        if s["_start"].strftime("%d") == date:
            by_time.setdefault(s["start"], []).append(s)
    plan = []
    for start, options in sorted(by_time.items()):
        sessions = [o for o in options if o["kind"] == "session"]
        if not sessions:
            plan.append(_public(options[:1])[0])
            continue
        score = lambda o: sum(w in (o["title"] + " " + o["track"]).lower() for w in words) + (3 if o["title"] == MY_SESSION else 0)  # noqa: E731
        plan.append(_public([max(sessions, key=score)])[0])
    return {"interests": interests, "day": "Wed 30 Sep" if date == "30" else "Thu 01 Oct", "plan": plan}


@mcp.tool()
def session_status() -> dict:
    """Where are we in THIS session (the talk named in MY_SESSION_TITLE)? Minutes left, minutes until lunch, where it runs."""
    now = datetime.now(TZ)
    mine = next((s for s in _slots() if s.get("title") == MY_SESSION), None)
    lunch = next((s for s in _slots() if "mittag" in s["title"].lower() and s["_end"] > now), None)
    return {
        "session": MY_SESSION or "(set MY_SESSION_TITLE to your talk's title)", "speakers": mine["speakers"] if mine else [],
        "when": f"{mine['day']} {mine['start']}–{mine['end']}" if mine else "?", "room": mine["room"] if mine else "?",
        "local_time": now.strftime("%H:%M"),
        "minutes_left_in_talk": max(0, _mins(mine["_end"] - now)) if mine and mine["_start"] <= now < mine["_end"] else None,
        "minutes_until_lunch": max(0, _mins(lunch["_start"] - now)) if lunch else None,
        "running_on": "Azure Functions" if os.environ.get("WEBSITE_SITE_NAME") else "my laptop",
    }


@mcp.tool()
def coffee_check() -> str:
    """Is the coffee outside still drinkable? (Highly scientific; knows the official coffee breaks.)"""
    now = datetime.now(TZ)
    brk = next((s for s in _slots() if "kaffee" in s["title"].lower() and s["_start"] <= now < s["_end"]), None)
    if brk:
        return f"Official coffee break until {brk['end']}. Fresh pots in the foyer. Go now, walk, don't run."
    return random.choice([
        "Fresh pot just arrived. Go now.",
        "Lukewarm. Acceptable for a demo, not for a keynote.",
        "Empty. Someone from the VMware panel took the last cup. We know who you are.",
        "Excellent — but the queue is longer than a Terraform plan.",
    ])


@mcp.tool()
def applause(level: int = 3) -> str:
    """Request applause from the audience. level 1–5."""
    return "👏" * max(1, min(level, 5)) + f"  (level {level} applause requested)"


@mcp.tool()
def buzzword_bingo(seed: str = "") -> dict:
    """A fresh 3×3 conference buzzword-bingo card (shout BINGO in the Q&A). Same seed = same card."""
    words = ["MCP", "agentic", "Copilot", "it depends", "zero trust", "VMware", "sovereign cloud", "Azure Arc",
             "hallucination", "tokens", "RAG", "Kubernetes", "\"works on my machine\"", "managed identity", "PAT",
             "scale to zero", "Entra", "cold start", "AI Foundry", "\"in preview\"", "Bicep", "on-prem", "FinOps"]
    rng = random.Random(seed or time.time())
    card = rng.sample(words, 9)
    card[4] = "FREE: \"Can you see my screen?\""
    return {"card": [card[0:3], card[3:6], card[6:9]], "rule": "Three in a row, then shout BINGO during the Q&A."}


if __name__ == "__main__":
    if "FUNCTIONS_CUSTOMHANDLER_PORT" in os.environ or "--http" in sys.argv:
        # Azure Functions (self-hosted MCP): stateless streamable HTTP behind the Functions host proxy.
        from mcp.server.transport_security import TransportSecuritySettings
        mcp.run(transport="streamable-http", host="127.0.0.1",
                port=int(os.environ.get("FUNCTIONS_CUSTOMHANDLER_PORT", "8000")),
                streamable_http_path="/mcp", stateless_http=True, json_response=True,
                # the host proxies with the public Host header → skip the localhost-only DNS-rebinding check
                transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    else:
        mcp.run()  # stdio
