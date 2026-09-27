"""
Seeds the demo Azure DevOps project with a believable backlog: the project IS this talk.
No PAT — your own Entra sign-in (az login).      python scripts/seed_ado.py
Idempotent (matches titles tagged cdc-germany-2026): 3 sprints, epics → features → backlog items → tasks, real bugs
found while building the demo, and a few jokes. Works with Scrum (PBI) and Agile (User Story).
"""
import subprocess
import sys
from urllib.parse import quote

import requests

API = "api-version=7.1"
TAG = "cdc-germany-2026"
ME = None  # resolved below: the signed-in user
SPRINTS = [  # name, start, finish — adjust the dates to your own sprint
    ("Sprint 41 · Foundations", "2026-09-07", "2026-09-20"),
    ("CDC-Germany 2026", "2026-09-21", "2026-10-09"),
    ("Sprint 43 · Hardening", "2026-10-12", "2026-10-23"),
]
S41, CDC, S43, BACKLOG = SPRINTS[0][0], SPRINTS[1][0], SPRINTS[2][0], None

# (key, type, title, parent_key, sprint, state, priority, effort/remaining, assigned, extra)
# type: Epic | Feature | Story | Task | Bug.  state: New | Progress | Done | Removed.  extra: description / criteria / repro / severity
BACKLOG_ITEMS = [
    # ── Epic A ─────────────────────────────────────────────────────────────────────────────────────────────
    ("A", "Epic", "Agents that reach real tools", None, None, "Progress", 1, None, True,
     {"desc": "An agent is only as useful as the tools it can reach. Host the team's tools as remote MCP servers on Azure Functions: cheap, boring, scalable."}),
    ("A1", "Feature", "SkyWatch: live aircraft over the venue as an MCP App", "A", None, "Progress", 2, None, True,
     {"desc": "Public ADS-B data wrapped as tools, rendered as an interactive radar inside the chat (MCP Apps), PNG fallback for other clients."}),
    ("A1a", "Story", "Radar widget renders inline in VS Code and other MCP Apps hosts", "A1", S41, "Done", 1, 8, True,
     {"crit": "- flights_overhead declares _meta.ui.resourceUri\n- ui:// resource served as text/html;profile=mcp-app\n- Renders in VS Code stable and a second MCP Apps host"}),
    ("A1b", "Story", "Radar refreshes itself every 15 s without a model round-trip", "A1", CDC, "Done", 2, 3, True,
     {"crit": "- Widget calls flights_overhead via callServerTool\n- No tokens spent on refresh\n- Timestamp visible in the widget"}),
    ("A1c", "Story", "Fall back to OpenSky when adsb.lol is down", "A1", S41, "Done", 2, 3, True,
     {"crit": "- 5xx or timeout from adsb.lol → OpenSky anonymous API\n- Source pill shows which provider answered"}),
    ("A1d", "Story", "Show the aircraft type silhouette next to each callsign", "A1", BACKLOG, "New", 4, 5, False,
     {"crit": "- A320/A321/B738/A359 silhouettes as inline SVG\n- Unknown type → generic icon"}),
    ("A2", "Feature", "DomainForge: from pun to booked domain in one chat", "A", None, "Progress", 2, None, True,
     {"desc": "Brainstorm → live availability → picker widget → Reserve button that calls back into the server; the booking is a Functions output binding."}),
    ("A2a", "Story", "Live availability for .de via DNS when RDAP has no answer", "A2", CDC, "Done", 1, 5, True,
     {"crit": "- RDAP 404 only counts after a redirect to the registry\n- Otherwise DNS-over-HTTPS NS lookup\n- Unknown TLD → grey badge"}),
    ("A2b", "Story", "Reserve button writes a ticket to Blob via output binding", "A2", S41, "Done", 2, 3, True,
     {"crit": "- reserve_domain uses @app.blob_output\n- reservations/<domain>.json with owner and timestamp"}),
    ("A2c", "Story", "Hand off to a registrar with a pre-filled search link", "A2", CDC, "Progress", 3, 2, True,
     {"crit": "- reserve_domain returns a ResourceLink\n- Link opens the registrar search for the exact domain"}),
    ("A2d", "Story", "German pun dictionary v2 (Bäckerei, Kneipe, Biergarten)", "A2", BACKLOG, "New", 4, 3, False,
     {"crit": "- 5 new business themes\n- Seeded RNG keeps results deterministic"}),
    ("A3", "Feature", "AdoPilot: the team's board as an MCP server", "A", None, "Progress", 2, None, True,
     {"desc": "Board, bugs and pipelines as typed tools, the stand-up as a prompt, the Definition of Done as a resource."}),
    ("A3a", "Story", "/standup prompt reads board, bugs, pipelines and the Definition of Done", "A3", CDC, "Progress", 2, 5, True,
     {"crit": "- Prompt trigger with optional focus argument\n- Answer under 150 words, ends with one decision"}),
    ("A3b", "Story", "Turn a Teams complaint into a bug without opening Azure DevOps", "A3", CDC, "Progress", 1, 3, True,
     {"crit": "- Agent proposes title, repro steps, priority and asks to confirm\n- create_bug files it in the current sprint as the signed-in user"}),
    ("A3c", "Story", "pipeline_health flags failed runs from the last 24 h", "A3", S43, "New", 3, 3, False,
     {"crit": "- Failed runs in 24 h listed first\n- Includes who triggered the run"}),

    # ── Epic B ─────────────────────────────────────────────────────────────────────────────────────────────
    ("B", "Epic", "Identity everywhere, secrets nowhere", None, None, "Progress", 1, None, True,
     {"desc": "Keys are for func start. The moment a second human connects, it's Entra: built-in MCP auth, on-behalf-of, managed identity."}),
    ("B1", "Feature", "Built-in Entra auth on MCP endpoints", "B", None, "Progress", 1, None, True,
     {"desc": "401 → protected resource metadata → Entra sign-in in the client; the server acts on behalf of the user downstream."}),
    ("B1a", "Story", "VS Code signs in automatically from the 401 + PRM document", "B1", CDC, "Done", 1, 5, True,
     {"crit": "- WEBSITE_AUTH_PRM_DEFAULT_WITH_SCOPES set\n- VS Code client pre-authorized\n- No key in mcp.json for adopilot"}),
    ("B1b", "Story", "Call Microsoft Graph and Azure DevOps on behalf of the signed-in user", "B1", CDC, "Done", 1, 8, True,
     {"crit": "- OnBehalfOfCredential with the app's managed identity as client assertion (no secret)\n- Work items show the human as Created By"}),
    ("B1c", "Story", "Remove the last PAT from the platform", "B1", CDC, "Done", 1, 2, True,
     {"crit": "- No ADO_PAT app setting, azd variable or Key Vault secret\n- Seeder and tools use Entra tokens"}),
    ("B1d", "Story", "Foundry agents call adopilot with OAuth identity passthrough", "B1", S43, "New", 2, 8, False,
     {"crit": "- Custom OAuth connection against the adopilot app registration\n- User consents once via consent_link"}),
    ("B2", "Feature", "Managed identity for storage and telemetry", "B", None, "Done", 2, None, True,
     {"desc": "allowSharedKeyAccess=false, deployment containers and App Insights via the user-assigned identity."}),
    ("B2a", "Story", "Storage account without shared keys", "B2", S41, "Done", 2, 3, True,
     {"crit": "- AzureWebJobsStorage__credential=managedidentity\n- Flex deployment container uses the UAMI"}),
    ("B2b", "Story", "App Insights ingestion with Entra authentication", "B2", S41, "Done", 3, 2, True,
     {"crit": "- APPLICATIONINSIGHTS_AUTHENTICATION_STRING uses the UAMI\n- Monitoring Metrics Publisher role"}),

    # ── Epic C ─────────────────────────────────────────────────────────────────────────────────────────────
    ("C", "Epic", "Discover, govern, reuse", None, None, "Progress", 2, None, True,
     {"desc": "Two hundred developers need to find the tools, and every agent platform should reuse them: registry, gateway, Foundry."}),
    ("C1", "Feature", "Private MCP registry in API Center", "C", None, "Progress", 2, None, True,
     {"desc": "All MCP servers registered with kind mcp; the v0.1 registry API feeds VS Code, GitHub Copilot and Foundry's tool catalog."}),
    ("C1a", "Story", "Register all four MCP servers from Bicep", "C1", CDC, "Done", 2, 3, True,
     {"crit": "- apis with kind mcp, versions, deployments with runtimeUri\n- Sample API removed"}),
    ("C1b", "Story", "Registry readable with Entra only (no anonymous access)", "C1", CDC, "Progress", 2, 2, True,
     {"crit": "- Azure API Center Data Reader for people and the Foundry project identity\n- curl with a bearer token returns the server list"}),
    ("C1c", "Story", "Allow only registry servers in VS Code via org policy", "C1", S43, "New", 3, 3, False,
     {"crit": "- McpGalleryServiceUrl policy points at the registry\n- ChatMCP=registry on managed devices"}),
    ("C2", "Feature", "Foundry agents on our MCP servers", "C", None, "Progress", 2, None, True,
     {"desc": "The same Functions MCP servers used by a Foundry Agent Service agent, with human approval for writes."}),
    ("C2a", "Story", "Agent asks for approval before reserve_domain, reads run freely", "C2", CDC, "Done", 1, 3, True,
     {"crit": "- require_approval always: reserve_domain, never: read-only tools\n- Keys stored in project connections, not in code"}),
    ("C2b", "Story", "Route the agent through an APIM gateway with rate limits", "C2", S43, "New", 3, 5, False,
     {"crit": "- APIM injects the Functions key\n- 5 calls / 30 s per subscription → 429"}),
    ("C2c", "Story", "Evaluation set for the demo agent (10 questions, expected tools)", "C2", BACKLOG, "New", 3, 5, False,
     {"crit": "- Tool-call accuracy ≥ 90 %\n- Runs nightly"}),

    # ── Tasks in the current sprint ────────────────────────────────────────────────────────────────────────
    ("T1", "Task", "Record short demo videos for the docs", "A3b", CDC, "New", 2, 3, True, {}),
    ("T2", "Task", "Dry-run the end-to-end demo with a timer", "A3a", CDC, "Progress", 1, 2, True, {}),
    ("T3", "Task", "Add job title and office to Entra profiles (whoami shows them)", "B1b", CDC, "Done", 3, 0, True, {}),
    ("T4", "Task", "Portal: configure identity provider for the API Center portal", "C1b", CDC, "New", 2, 1, True, {}),
    ("T5", "Task", "Pick the funniest available domain for the live Reserve click", "A2c", CDC, "New", 3, 1, True, {}),
    ("T6", "Task", "Run smoke.py before every demo (also warms the apps)", "A3a", CDC, "New", 1, 1, True, {}),

    # ── Bugs: real ones found while building the demo (27 Sep) + open ones ─────────────────────────────────
    ("X1", "Bug", "check_domains marks every .de domain as available", "A2", CDC, "Done", 1, 2, True,
     {"sev": "2 - High", "repro": "1. check_domains [\"spiegel.de\"]\n2. Result: available\nCause: rdap.org answers 404 both for 'not registered' and 'TLD has no RDAP'."}),
    ("X2", "Bug", "Prompt arguments silently dropped after the azure-functions 2.x upgrade", "A3", CDC, "Done", 1, 1, True,
     {"sev": "2 - High", "repro": "1. /standup focus:\"release readiness\"\n2. Focus missing from the prompt\nCause: prompts receive PromptInvocationContext, json.loads raised and was swallowed."}),
    ("X3", "Bug", "radar_image returns a Python repr instead of a PNG", "A1", CDC, "Done", 2, 1, True,
     {"sev": "3 - Medium", "repro": "1. Call radar_image\n2. Text block contains \"[TextContent(type='text'...\"\nCause: bare -> List return annotation."}),
    ("X4", "Bug", "Foundry agent asks approval for read-only domainforge tools", "C2", CDC, "Done", 2, 1, True,
     {"sev": "3 - Medium", "repro": "1. Ask the agent to name a business\n2. Approval prompt for brainstorm_domains\nCause: tools not listed under 'always' default to 'always'."}),
    ("X5", "Bug", "Flex Consumption plans fail when created in parallel", None, CDC, "Done", 2, 1, True,
     {"sev": "3 - Medium", "repro": "1. azd up with four Flex apps\n2. Two plans fail with InternalServerError\nFix: @batchSize(1) on plans and apps."}),
    ("X6", "Bug", "First tool call after 20 minutes idle takes ~6 s", "A", CDC, "New", 2, 3, True,
     {"sev": "3 - Medium", "repro": "1. Leave the apps idle for 20 minutes\n2. Call flights_overhead\n3. ~6 s instead of <1 s\nQuestion: are MCP triggers in the 'http' always-ready group?"}),
    ("X7", "Bug", "Radar plots FRA ground traffic at 0 ft as if it were overhead", "A1", S43, "New", 3, 2, False,
     {"sev": "4 - Low", "repro": "1. flights_overhead radius 25 NM\n2. Taxiing aircraft at EDDF shown with altitude 0\nExpected: filter or grey out ground traffic."}),
    ("X8", "Bug", "flights_overhead returns 0 aircraft during Lufthansa strike", "A1", BACKLOG, "New", 1, 1, False,
     {"sev": "2 - High", "repro": "1. Wait for a strike\n2. Ask what is flying\n3. Nothing. Working as designed?"}),
    ("X9", "Bug", 'Coffee tool reports "fresh" at 16:45. It is not fresh.', None, CDC, "Progress", 1, 1, True,
     {"sev": "1 - Critical", "repro": "1. coffee_check at 16:45\n2. 'Fresh pot at the Track 5 station'\n3. It is not fresh."}),
    ("X10", "Bug", "Agent assigned itself all the P1s", None, CDC, "New", 2, 1, False,
     {"sev": "3 - Medium", "repro": "1. Ask the agent to triage\n2. Every P1 is assigned to 'Agent'\n3. The agent is not on the team."}),
]
# titles to move to 'Removed' on rerun (e.g. leftovers from earlier test runs)
RETIRE: list = []


def sh(*cmd: str) -> str:
    return subprocess.run(list(cmd), capture_output=True, text=True, check=True, shell=sys.platform == "win32").stdout.strip()


env = {k: v.strip('"') for k, v in (ln.split("=", 1) for ln in sh("azd", "env", "get-values").splitlines() if "=" in ln)}
ORG, PROJECT = env["ADO_ORG_URL"].rstrip("/"), env["ADO_PROJECT"]
TEAM = env.get("ADO_TEAM") or f"{PROJECT} Team"
# resource-URI form → a fresh token even if az cached one from before the org was connected to Entra
TOKEN = sh("az", "account", "get-access-token", "--resource", "https://app.vssps.visualstudio.com", "--query", "accessToken", "-o", "tsv")
H = {"Authorization": f"Bearer {TOKEN}"}


def ado(method: str, path: str, body=None, ct: str = "application/json", ok=(200, 201)) -> dict:
    r = requests.request(method, f"{ORG}/{path}", json=body, headers={**H, "Content-Type": ct}, timeout=30, allow_redirects=False)
    if r.status_code in (203, 302, 401):
        sys.exit(f"Azure DevOps rejected your sign-in (HTTP {r.status_code}). Are you a member of {ORG} in this tenant?")
    if r.status_code not in ok:
        raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
    return r.json() if r.text else {}


team = quote(TEAM)
ME = ado("GET", "_apis/connectionData")["authenticatedUser"]["properties"]["Account"]["$value"]

# 1) sprints, subscribed by the team
subscribed = {i["id"] for i in ado("GET", f"{PROJECT}/{team}/_apis/work/teamsettings/iterations?{API}").get("value", [])}
for name, start, finish in SPRINTS:
    attrs = {"startDate": f"{start}T00:00:00Z", "finishDate": f"{finish}T00:00:00Z"}
    ado("POST", f"{PROJECT}/_apis/wit/classificationnodes/iterations?{API}", {"name": name, "attributes": attrs}, ok=(200, 201, 409))
    node = ado("PATCH", f"{PROJECT}/_apis/wit/classificationnodes/iterations/{quote(name)}?{API}", {"attributes": attrs})
    if node["identifier"] not in subscribed:
        ado("POST", f"{PROJECT}/{team}/_apis/work/teamsettings/iterations?{API}", {"id": node["identifier"]})
    print(f"sprint   {name:<26} {start} → {finish}")

# 2) process mapping (Scrum vs Agile)
types = {t["name"] for t in ado("GET", f"{PROJECT}/_apis/wit/workitemtypes?{API}")["value"]}
scrum = "Product Backlog Item" in types
TYPE = {"Epic": "Epic", "Feature": "Feature", "Story": "Product Backlog Item" if scrum else "User Story", "Task": "Task", "Bug": "Bug"}
STATE = {  # logical → per type
    "New": {"Task": "To Do" if scrum else "New"},
    "Progress": {"Epic": "In Progress" if scrum else "Active", "Feature": "In Progress" if scrum else "Active",
                 "Story": "Committed" if scrum else "Active", "Bug": "Committed" if scrum else "Active", "Task": "In Progress" if scrum else "Active"},
    "Done": {"Epic": "Done" if scrum else "Closed", "Feature": "Done" if scrum else "Closed", "Story": "Done" if scrum else "Closed",
             "Bug": "Done" if scrum else "Closed", "Task": "Done" if scrum else "Closed"},
    "Removed": {},
}

# 3) what already exists (by title, our tag)
ids = [w["id"] for w in ado("POST", f"{PROJECT}/_apis/wit/wiql?{API}", {
    "query": f"SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project AND [System.Tags] CONTAINS '{TAG}'"}).get("workItems", [])]
existing = {}
for i in range(0, len(ids), 200):
    for w in ado("POST", f"_apis/wit/workitemsbatch?{API}", {"ids": ids[i:i + 200], "fields": ["System.Title", "System.State"]})["value"]:
        existing[w["fields"]["System.Title"]] = w["id"]

for title in RETIRE:  # retire items you no longer want on the board
    if title in existing:
        try:
            ado("PATCH", f"{PROJECT}/_apis/wit/workitems/{existing[title]}?{API}",
                [{"op": "add", "path": "/fields/System.State", "value": "Removed"}], ct="application/json-patch+json")
            print(f"removed  #{existing[title]:<5} {title}")
        except RuntimeError as ex:
            print(f"(could not remove #{existing[title]}: {str(ex)[:80]})")

# 4) create in order (parents first), then set state (new items always start in the initial state)
key_id = {}
for key, typ, title, parent, sprint, state, prio, effort, assigned, extra in BACKLOG_ITEMS:
    wtype = TYPE[typ]
    if title in existing:
        key_id[key] = existing[title]
        print(f"exists   #{existing[title]:<5} {wtype:<20} {title}")
        continue
    f = {"System.Title": title, "System.Tags": TAG, "Microsoft.VSTS.Common.Priority": prio,
         "System.IterationPath": f"{PROJECT}\\{sprint}" if sprint else PROJECT}
    if assigned:
        f["System.AssignedTo"] = ME
    if extra.get("desc"):
        f["System.Description"] = extra["desc"]
    if extra.get("crit"):
        f["Microsoft.VSTS.Common.AcceptanceCriteria"] = extra["crit"].replace("\n", "<br>")
    if extra.get("repro"):
        f["Microsoft.VSTS.TCM.ReproSteps"] = extra["repro"].replace("\n", "<br>")
    if extra.get("sev"):
        f["Microsoft.VSTS.Common.Severity"] = extra["sev"]
    if effort is not None and typ in ("Story", "Bug"):
        f["Microsoft.VSTS.Scheduling.Effort" if scrum else "Microsoft.VSTS.Scheduling.StoryPoints"] = effort
    if effort is not None and typ == "Task":
        f["Microsoft.VSTS.Scheduling.RemainingWork"] = effort
    patch = [{"op": "add", "path": f"/fields/{k}", "value": v} for k, v in f.items()]
    if parent:
        patch.append({"op": "add", "path": "/relations/-", "value": {
            "rel": "System.LinkTypes.Hierarchy-Reverse", "url": f"{ORG}/_apis/wit/workItems/{key_id[parent]}"}})
    wi = ado("POST", f"{PROJECT}/_apis/wit/workitems/${quote(wtype)}?{API}", patch, ct="application/json-patch+json")
    key_id[key] = wi["id"]
    target = STATE.get(state, {}).get(typ)
    if target:
        try:
            ado("PATCH", f"{PROJECT}/_apis/wit/workitems/{wi['id']}?{API}",
                [{"op": "add", "path": "/fields/System.State", "value": target}], ct="application/json-patch+json")
        except RuntimeError:
            target = "(initial)"
    print(f"created  #{wi['id']:<5} {wtype:<20} {(target or 'New'):<11} {title}")

print(f"\nBoard: {ORG}/{PROJECT}/_sprints/taskboard/{team}/{quote(PROJECT)}/{quote(CDC)}")
print(f"Backlog: {ORG}/{PROJECT}/_backlogs/backlog/{team}/Epics")
