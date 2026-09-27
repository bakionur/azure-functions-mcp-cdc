"""
Server 3 · "domainforge" — funny domain names for a business in a location, with live availability
and a one-click "reserve" (the booking step) that lands in Blob Storage via an OUTPUT BINDING.
Shows: a tool that returns candidates, a tool that calls a public API in parallel (RDAP),
an MCP APP picker with buttons that call BACK into the server, and a write tool with a Functions binding.
"""
import json
import logging
import re
import random
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Union

import azure.functions as func
import requests
from mcp.types import CallToolResult, ResourceLink, TextContent

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

PICKER_UI_URI = "ui://domainforge/picker.html"
TOOL_METADATA = json.dumps({"ui": {"resourceUri": PICKER_UI_URI}})
RESOURCE_METADATA = json.dumps({"ui": {"prefersBorder": True}})

# ------------------------------------------------------------------ the "creative engine" (deterministic, so the demo repeats)
PUNS = {
    "pizza": ["crust", "slice", "dough", "margherita", "oven", "topping"],
    "bakery": ["knead", "loaf", "rise", "crumb", "crust", "proof"],
    "coffee": ["brew", "bean", "grind", "roast", "espresso", "latte"],
    "gym": ["flex", "gains", "sweat", "rep", "iron", "lift"],
    "barber": ["fade", "clipper", "trim", "shear", "beard"],
    "cloud": ["nimbus", "cumulus", "uptime", "stack", "tenant", "byte"],
    "consulting": ["advise", "insight", "pivot", "roadmap", "synergy"],
    "beer": ["hop", "brew", "stein", "pint", "lager", "foam"],
    "ai": ["neuron", "prompt", "token", "agent", "vector", "latent"],
}
TLDS = {
    "pizza": ["pizza", "de", "restaurant", "lol"], "bakery": ["de", "cafe", "shop", "lol"],
    "coffee": ["coffee", "cafe", "de", "wtf"], "gym": ["fit", "gym", "de", "lol"],
    "barber": ["salon", "de", "style", "wtf"], "cloud": ["cloud", "io", "dev", "de"],
    "consulting": ["consulting", "de", "io", "wtf"], "beer": ["beer", "bar", "de", "lol"],
    "ai": ["ai", "io", "dev", "lol"],
}
TEMPLATES = ["{pun}{loc}", "{loc}{pun}", "{pun}-{loc}", "{loc}-{pun}s", "der{pun}", "{pun}haus", "{pun}hub{loc}", "{loc}{pun}werk"]


def _slug(s: str) -> str:
    s = s.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]", "", s)


@app.mcp_tool(use_result_schema=True)  # dict → JSON text + structuredContent (without it: Python repr)
@app.mcp_tool_property(arg_name="business", description="What the business does, e.g. 'pizza', 'cloud consulting', 'craft beer'.", is_required=True)
@app.mcp_tool_property(arg_name="location", description="City or region, e.g. 'Hanau'.", is_required=True)
@app.mcp_tool_property(arg_name="count", description="How many candidates (default 12, max 30).", is_required=False)
def brainstorm_domains(business: str, location: str, count: int = 12) -> dict:
    """Generates pun-heavy domain name candidates for a business in a location. Returns names only; call check_domains next."""
    logging.info("brainstorm_domains business=%r location=%r count=%s", business, location, count)
    key = next((k for k in PUNS if k in business.lower()), None) or random.choice(list(PUNS))
    loc = _slug(location)
    rng = random.Random(f"{business}|{location}")  # same input → same jokes, repeatable demos
    # the obvious names first: they're (almost) always taken → red badges next to the green puns
    biz = _slug(business)
    obvious = [f"{biz}{loc}.de", f"{biz}-{loc}.de"] + ([f"pizzeria-{loc}.de"] if key == "pizza" else [])
    seen, out = set(obvious), list(obvious)
    tries = 0
    while len(out) < min(int(count or 12), 30) + len(obvious) and tries < 300:
        tries += 1
        name = rng.choice(TEMPLATES).format(pun=rng.choice(PUNS[key]), loc=loc)
        tld = rng.choice(TLDS[key])
        d = f"{name}.{tld}"
        if d not in seen and len(name) <= 24:
            seen.add(d); out.append(d)
    return {"business": business, "location": location, "theme": key, "candidates": out,
            "note": f"The first {len(obvious)} are the obvious names (usually taken); the rest are puns."}


def _rdap(domain: str) -> dict:
    """RDAP first. rdap.org answers 404 both for 'not registered' AND for 'this TLD has no RDAP' (e.g. .de, .io),
    so a 404 only counts when rdap.org redirected us to the registry's own RDAP server. Otherwise ask DNS."""
    try:
        r = requests.get(f"https://rdap.org/domain/{domain}", timeout=8, allow_redirects=True,
                         headers={"User-Agent": "cdc-domainforge-mcp/1.0"})
        if r.status_code == 200:
            return {"domain": domain, "status": "taken", "via": "rdap"}
        if r.status_code == 404 and "rdap.org" not in r.url:
            return {"domain": domain, "status": "available", "via": "rdap"}
    except Exception as ex:  # noqa: BLE001
        logging.warning("rdap %s failed: %s", domain, ex)
    return _dns(domain)


def _dns(domain: str) -> dict:
    """Fallback via DNS-over-HTTPS: NS records = taken; NXDOMAIN inside an existing TLD = (very likely) free."""
    try:
        j = requests.get("https://dns.google/resolve", params={"name": domain, "type": "NS"}, timeout=8).json()
        if j.get("Status") == 0 and j.get("Answer"):
            return {"domain": domain, "status": "taken", "via": "dns"}
        zone = (j.get("Authority") or [{}])[0].get("name", ".")
        if j.get("Status") == 3 and zone.strip(".") == domain.rsplit(".", 1)[-1]:
            return {"domain": domain, "status": "available", "via": "dns"}
        return {"domain": domain, "status": "unknown", "via": "dns"}
    except Exception as ex:  # noqa: BLE001
        return {"domain": domain, "status": "unknown", "error": str(ex)[:80]}


@app.mcp_tool(metadata=TOOL_METADATA)
@app.mcp_tool_property(arg_name="domains", description="Array of domain names to check, e.g. [\"crusthanau.pizza\", \"hanaubrew.coffee\"].", is_required=True, as_array=True)
def check_domains(domains: List[str]) -> CallToolResult:  # List[str] → JSON-schema array, not string
    """Checks live availability of domain names via RDAP (no registrar API key needed). Renders a picker when the client supports MCP Apps."""
    logging.info("check_domains domains=%s", domains)
    if isinstance(domains, str):
        domains = json.loads(domains)
    domains = [d.strip().lower() for d in domains][:30]
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(_rdap, domains))
    available = [r["domain"] for r in results if r["status"] == "available"]
    text = f"{len(available)}/{len(results)} look available: {', '.join(available) or 'none'}"
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content={"checked_at": datetime.now(timezone.utc).isoformat(), "results": results,
                            "note": "via rdap = registry answer; via dns = no DNS delegation (very likely free, e.g. .de has no public RDAP); unknown = check with the registry."},
    )


@app.mcp_tool()
@app.mcp_tool_property(arg_name="domain", description="The domain to reserve, e.g. crusthanau.pizza", is_required=True)
@app.mcp_tool_property(arg_name="owner", description="Who is reserving it (name or email).", is_required=True)
@app.blob_output(arg_name="ticket", connection="AzureWebJobsStorage", path="reservations/{mcptoolargs.domain}.json")
def reserve_domain(ticket: func.Out[str], domain: str, owner: str) -> List[Union[TextContent, ResourceLink]]:
    """Reserves a domain on the team's shortlist (writes a reservation ticket) and returns registrar links to complete the purchase. Confirm with the user first."""
    domain = domain.strip().lower()
    logging.info("reserve_domain domain=%s owner=%s", domain, owner)
    record = {"domain": domain, "owner": owner, "reserved_at": datetime.now(timezone.utc).isoformat(),
              "status": "reserved-pending-purchase", "event": "CDC-Germany 2026"}
    ticket.set(json.dumps(record, indent=2))  # ← the Functions output binding IS the booking system
    buy = f"https://www.namecheap.com/domains/registration/results/?domain={domain}"
    return [
        TextContent(type="text", text=f"Reserved {domain} for {owner}. Ticket written to blob storage. Complete the purchase at the registrar link."),
        ResourceLink(type="resource_link", uri=buy, name=f"Buy {domain}", description="Registrar search pre-filled with the domain"),
    ]


# ------------------------------------------------------------------ MCP App + prompt
@app.mcp_resource_trigger(
    arg_name="context",
    uri=PICKER_UI_URI,
    resource_name="DomainForge Picker",
    description="Interactive domain picker (MCP App) for the check_domains tool.",
    mime_type="text/html;profile=mcp-app",
    metadata=RESOURCE_METADATA,
)
def picker_widget(context) -> str:
    logging.info("resource %s", PICKER_UI_URI)
    f = Path(__file__).parent / "app" / "dist" / "index.html"
    if f.exists():
        return f.read_text(encoding="utf-8")
    return "<html><body><p>Widget not built. Run <code>npm run build</code> in servers/domainforge/app.</p></body></html>"


@app.mcp_prompt_trigger(
    arg_name="context",
    prompt_name="name_my_business",
    description="End-to-end: brainstorm → check → shortlist → reserve, for a business in a city.",
    prompt_arguments=[
        func.PromptArgument("business", "What the business does.", required=True),
        func.PromptArgument("location", "City or region.", required=True),
    ],
)
def name_my_business(context: func.PromptInvocationContext) -> str:
    args = context.arguments  # azure-functions 2.x hands prompts a PromptInvocationContext, not JSON
    logging.info("prompt name_my_business args=%s", args)
    return f"""Help me name a {args.get('business', 'business')} in {args.get('location', 'Hanau')}.
1. Call brainstorm_domains (it starts with the obvious names), then add 5 candidates of your own that are funnier.
2. Call check_domains with all of them.
3. Say in one line which obvious names are already taken, then present the available ones ranked by how much they would make a German laugh, with a one-line pitch each.
4. Ask which one to reserve; only then call reserve_domain."""
