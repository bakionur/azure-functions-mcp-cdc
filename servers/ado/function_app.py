"""
Server 1 · "adopilot" — Azure DevOps as an MCP server.
Shows: typed tools (new Python decorators), STRUCTURED CONTENT (dataclass), a WRITE tool,
a prompt trigger (stand-up), a resource trigger (definition of done) — and IDENTITY: the app sits behind built-in
Entra auth and calls Azure DevOps and Microsoft Graph ON BEHALF OF the signed-in user. No PAT, no secret anywhere.
"""
import base64
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List

import azure.functions as func
import requests
from mcp.types import CallToolResult, TextContent

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# ------------------------------------------------------------------ ADO client (as the signed-in user)
ORG = os.environ.get("ADO_ORG_URL", "").rstrip("/")
PROJECT = os.environ.get("ADO_PROJECT", "")
TEAM = os.environ.get("ADO_TEAM", f"{PROJECT} Team")
API = "api-version=7.1"
ADO_SCOPE = "499b84ac-1321-427f-aa17-267ca6975798/.default"  # Azure DevOps resource (same id in every tenant)


class AdoAuthError(Exception):
    """ADO answers an unknown/unauthorised identity with a 302 to sign-out or a 203 HTML page, not a clean 401."""


def _ado(method: str, url: str, token: str, content_type: str = "application/json", **kw) -> dict:
    r = requests.request(method, url, headers={"Authorization": f"Bearer {token}", "Content-Type": content_type},
                         timeout=20, allow_redirects=False, **kw)
    if r.status_code in (203, 302, 401):
        raise AdoAuthError(r.status_code)
    r.raise_for_status()
    return r.json()


def _wiql(token: str, query: str, team_scoped: bool = False) -> List[int]:
    scope = f"{ORG}/{PROJECT}/{TEAM}" if team_scoped else f"{ORG}/{PROJECT}"
    res = _ado("POST", f"{scope}/_apis/wit/wiql?{API}", token, json={"query": query})
    return [w["id"] for w in res.get("workItems", [])][:50]


def _items(token: str, ids: List[int], fields: List[str]) -> List[dict]:
    if not ids:
        return []
    res = _ado("GET", f"{ORG}/{PROJECT}/_apis/wit/workitems?ids={','.join(map(str, ids))}&fields={','.join(fields)}&{API}", token)
    out = []
    for wi in res["value"]:
        f = wi["fields"]
        out.append({
            "id": wi["id"],
            "type": f.get("System.WorkItemType"),
            "title": f.get("System.Title"),
            "state": f.get("System.State"),
            "assigned_to": (f.get("System.AssignedTo") or {}).get("displayName", "unassigned"),
            "priority": f.get("Microsoft.VSTS.Common.Priority"),
            "severity": f.get("Microsoft.VSTS.Common.Severity"),
            "url": f"{ORG}/{PROJECT}/_workitems/edit/{wi['id']}",
        })
    return out


def _fail(tool: str, ex: Exception) -> CallToolResult:
    """The host hides exception text ("An error occurred invoking ..."); tell the model what actually broke."""
    if not (ORG and PROJECT):
        msg = "Azure DevOps is not configured on this server yet (ADO_ORG_URL / ADO_PROJECT). whoami still works."
    elif isinstance(ex, AdoAuthError):
        msg = (f"Azure DevOps did not accept the signed-in user (HTTP {ex}). The user must be a member of {ORG} "
               "(org connected to this Entra tenant) with access to the project.")
    elif isinstance(ex, PermissionError) or type(ex).__name__ == "ClientAuthenticationError":
        msg = f"could not get an Azure DevOps token on behalf of the user: {str(ex)[:200]}"
    else:
        status = getattr(getattr(ex, "response", None), "status_code", None)
        hint = {403: "The signed-in user lacks permission for this in the project.",
                404: "Org, project or team not found: check ADO_ORG_URL / ADO_PROJECT / ADO_TEAM."}.get(status, "")
        msg = f"Azure DevOps returned {status or type(ex).__name__}. {hint}".strip()
    logging.error("%s failed: %s", tool, ex)
    return CallToolResult(is_error=True, content=[TextContent(type="text", text=f"{tool} failed: {msg}")])


# ------------------------------------------------------------------ identity (built-in Entra auth, Demo 3)
def _headers_of(context) -> dict:
    """MCPToolContext → the HTTP headers App Service auth (EasyAuth) put on the request. Never log these."""
    raw = (context or {}).get("transport", {}).get("properties", {}).get("headers", {}) or {}
    return {k.lower(): v for k, v in raw.items()}


def _caller(context) -> str:
    return _headers_of(context).get("x-ms-client-principal-name", "")


def _obo_token(context, scope: str) -> str:
    """On-behalf-of: swap the caller's token for one to a downstream API — as THE USER, no secret anywhere.
    The app proves who it is with its managed identity (federated credential), not a client secret."""
    from azure.identity import ManagedIdentityCredential, OnBehalfOfCredential
    h = _headers_of(context)
    user_token = h.get("x-ms-token-aad-access-token") or h.get("authorization", "").removeprefix("Bearer ").strip()
    if not user_token:
        raise PermissionError("no user token: built-in auth is off (key mode) or the token store is disabled")
    principal = json.loads(base64.b64decode(h.get("x-ms-client-principal", "e30=")))
    tenant = next((c["val"] for c in principal.get("claims", [])
                   if c.get("typ") in ("tid", "http://schemas.microsoft.com/identity/claims/tenantid")),
                  os.environ.get("WEBSITE_AUTH_AAD_ALLOWED_TENANTS", ""))
    mi = ManagedIdentityCredential(client_id=os.environ["OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID"])
    audience = os.environ.get("TokenExchangeAudience", "api://AzureADTokenExchange")
    obo = OnBehalfOfCredential(tenant_id=tenant, client_id=os.environ["WEBSITE_AUTH_CLIENT_ID"], user_assertion=user_token,
                               client_assertion_func=lambda: mi.get_token(f"{audience}/.default").token)
    return obo.get_token(scope).token


def _ado_token(context) -> str:
    """Azure DevOps token FOR THE CALLER (on-behalf-of). Locally (`func start`, no EasyAuth) use your `az login`."""
    if _caller(context) or _headers_of(context).get("authorization"):
        return _obo_token(context, ADO_SCOPE)
    if os.environ.get("AZURE_FUNCTIONS_ENVIRONMENT") == "Development":
        from azure.identity import AzureCliCredential
        return AzureCliCredential().get_token(ADO_SCOPE).token
    raise PermissionError("no signed-in user: this server needs built-in Entra auth to call Azure DevOps as the user")


FIELDS = ["System.Id", "System.WorkItemType", "System.Title", "System.State", "System.AssignedTo",
          "Microsoft.VSTS.Common.Priority", "Microsoft.VSTS.Common.Severity"]


# ------------------------------------------------------------------ structured content
@dataclass
@func.mcp_content
class BoardSnapshot:
    """A snapshot of the team board for the current sprint."""
    project: str
    team: str
    taken_at: str
    by_state: dict = field(default_factory=dict)
    items: List[dict] = field(default_factory=list)


# ------------------------------------------------------------------ tools
@app.mcp_tool()
@app.mcp_tool_property(arg_name="state", description="Optional filter. Leave EMPTY for the whole board (usual case). 'active'/'open'/'in progress' = everything in flight; or an exact state like New, Committed, Done.", is_required=False)
def sprint_board(context: func.MCPToolContext, state: str = "") -> BoardSnapshot:
    """Returns the team's board for the CURRENT sprint: work items grouped by state, with assignee and priority."""
    logging.info("sprint_board state=%r", state)
    try:
        # Agile says Active, Scrum says Committed/In Progress: map the model's natural words to both processes
        in_flight = ("Active", "Committed", "In Progress", "Approved", "To Do")
        if state.strip().lower() in ("active", "open", "in progress", "in-progress", "ongoing", "current"):
            state_clause = " AND [System.State] IN (" + ", ".join(f"'{x}'" for x in in_flight) + ")"
        else:
            state_clause = f" AND [System.State] = '{state.replace("'", "''")}'" if state else ""  # WIQL-escape model input
        token = _ado_token(context)
        ids = _wiql(token,
                    "SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project "
                    "AND [System.IterationPath] UNDER @CurrentIteration AND [System.State] <> 'Removed'" + state_clause +
                    " ORDER BY [Microsoft.VSTS.Common.Priority] ASC",
                    team_scoped=True)
        items = _items(token, ids, FIELDS)
        by_state: dict = {}
        for it in items:
            by_state[it["state"]] = by_state.get(it["state"], 0) + 1
        if not items and state:  # help the model self-correct instead of reporting an "empty" board
            return CallToolResult(content=[TextContent(type="text", text=(
                f"No items in state '{state}' this sprint. Call sprint_board with no state to see the whole board "
                "(states in this project include New, Committed, In Progress, To Do, Done)."))])
        return BoardSnapshot(project=PROJECT, team=TEAM, taken_at=datetime.now(timezone.utc).isoformat(),
                             by_state=by_state, items=items)
    except (requests.RequestException, AdoAuthError, PermissionError, ValueError) as ex:
        return _fail("sprint_board", ex)


@app.mcp_tool()
@app.mcp_tool_property(arg_name="max_priority", description="Only bugs with priority <= this (1 = highest). Default 2.", is_required=False)
def open_bugs(context: func.MCPToolContext, max_priority: int = 2) -> CallToolResult:
    """Lists open bugs ordered by priority and severity. Use this before deciding what the team should fix first."""
    logging.info("open_bugs max_priority=%s", max_priority)
    try:
        token = _ado_token(context)
        ids = _wiql(
            token,
            "SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project "
            "AND [System.WorkItemType] = 'Bug' AND [System.State] NOT IN ('Closed', 'Resolved', 'Done', 'Removed') "  # Agile + Scrum end states
            f"AND [Microsoft.VSTS.Common.Priority] <= {int(max_priority)} "
            "ORDER BY [Microsoft.VSTS.Common.Priority] ASC, [Microsoft.VSTS.Common.Severity] ASC")
        bugs = _items(token, ids, FIELDS)
        summary = f"{len(bugs)} open bug(s) with priority <= {max_priority}."
        return CallToolResult(
            content=[TextContent(type="text", text=summary + "\n" + json.dumps(bugs, indent=2))],
            structured_content={"count": len(bugs), "bugs": bugs},
        )
    except (requests.RequestException, AdoAuthError, PermissionError, ValueError) as ex:
        return _fail("open_bugs", ex)


@app.mcp_tool(use_result_schema=True)  # dict → JSON text + structuredContent (without it: Python repr)
@app.mcp_tool_property(arg_name="title", description="Short bug title.", is_required=True)
@app.mcp_tool_property(arg_name="repro_steps", description="Steps to reproduce, as plain text or markdown.", is_required=True)
@app.mcp_tool_property(arg_name="priority", description="1 (highest) to 4. Default 2.", is_required=False)
@app.mcp_tool_property(arg_name="assign_to", description="Display name or email of the assignee. Optional.", is_required=False)
def create_bug(context: func.MCPToolContext, title: str, repro_steps: str, priority: int = 2, assign_to: str = "") -> dict:
    """Creates a Bug work item in the current sprint. ALWAYS confirm title and priority with the user before calling."""
    caller = _caller(context)  # the signed-in human (Entra)
    logging.info("create_bug title=%r priority=%s assign_to=%r caller=%r", title, priority, assign_to, caller)
    if caller:
        repro_steps += f"\n\nReported via MCP by {caller}"
    try:
        patch = [
            {"op": "add", "path": "/fields/System.Title", "value": title},
            {"op": "add", "path": "/fields/Microsoft.VSTS.TCM.ReproSteps", "value": repro_steps.replace("\n", "<br>")},
            {"op": "add", "path": "/fields/Microsoft.VSTS.Common.Priority", "value": int(priority)},
            {"op": "add", "path": "/fields/System.Tags", "value": "created-by-mcp; cdc-germany-2026" + (f"; by {caller}" if caller else "")},
        ]
        if assign_to:
            patch.append({"op": "add", "path": "/fields/System.AssignedTo", "value": assign_to})
        token = _ado_token(context)
        current = _ado("GET", f"{ORG}/{PROJECT}/{TEAM}/_apis/work/teamsettings/iterations?$timeframe=current&{API}", token).get("value", [])
        if current:  # file it in the team's current sprint, not the project root
            patch.append({"op": "add", "path": "/fields/System.IterationPath", "value": current[0]["path"]})
        # created AS THE CALLER (on-behalf-of) → ADO shows them as "Created By", with their permissions
        wi = _ado("POST", f"{ORG}/{PROJECT}/_apis/wit/workitems/$Bug?{API}", token, "application/json-patch+json", json=patch)
        logging.info("Created bug %s via MCP", wi["id"])
        return {"id": wi["id"], "title": title, "created_by": wi["fields"]["System.CreatedBy"]["displayName"],
                "sprint": wi["fields"]["System.IterationPath"], "url": f"{ORG}/{PROJECT}/_workitems/edit/{wi['id']}"}
    except (requests.RequestException, AdoAuthError, PermissionError, ValueError) as ex:
        return _fail("create_bug", ex)


@app.mcp_tool(use_result_schema=True)
@app.mcp_tool_property(arg_name="top", description="How many recent runs per pipeline. Default 3.", is_required=False)
def pipeline_health(context: func.MCPToolContext, top: int = 3) -> dict:
    """Recent pipeline runs and their results — who broke the build?"""
    logging.info("pipeline_health top=%s", top)
    try:
        token = _ado_token(context)
        out = []
        for p in _ado("GET", f"{ORG}/{PROJECT}/_apis/pipelines?{API}", token).get("value", [])[:10]:
            runs = _ado("GET", f"{ORG}/{PROJECT}/_apis/pipelines/{p['id']}/runs?$top={int(top)}&{API}", token).get("value", [])
            out.append({
                "pipeline": p["name"],
                "runs": [{"id": x["id"], "state": x.get("state"), "result": x.get("result"),
                          "finished": x.get("finishedDate")} for x in runs],
            })
        return {"project": PROJECT, "pipelines": out}
    except (requests.RequestException, AdoAuthError, PermissionError, ValueError) as ex:
        return _fail("pipeline_health", ex)


@app.mcp_tool(use_result_schema=True)
def whoami(context: func.MCPToolContext) -> dict:
    """Who is calling this server? Returns the signed-in user as seen by the server (Entra ID via built-in auth) and,
    via on-behalf-of, their Microsoft Graph profile. Use it when the user asks who they are signed in as."""
    caller = _caller(context)
    logging.info("whoami caller=%r", caller)
    if not caller:
        return {"signed_in": False, "mode": "function key", "hint": "Built-in Entra auth is off for this app: anyone with the key is 'anonymous'."}
    out = {"signed_in": True, "mode": "Entra ID (built-in MCP auth)", "caller": caller}
    try:
        me = requests.get("https://graph.microsoft.com/v1.0/me?$select=displayName,jobTitle,officeLocation,userPrincipalName",
                          headers={"Authorization": f"Bearer {_obo_token(context, 'https://graph.microsoft.com/.default')}"}, timeout=15)
        me.raise_for_status()
        out["graph_me"] = {k: v for k, v in me.json().items() if not k.startswith("@")}
        out["how"] = "on-behalf-of: the server called Microsoft Graph AS YOU, with no secret in the app"
    except Exception as ex:  # noqa: BLE001 — consent missing, FIC still propagating (AADSTS50013 → restart app), ...
        logging.warning("whoami OBO failed: %s", ex)
        out["graph_error"] = str(ex)[:300]
    return out


# ------------------------------------------------------------------ prompt + resource
DEFINITION_OF_DONE = """# Definition of Done
- Code reviewed by one other human (agents may review, humans approve)
- Pipeline green on main, no skipped tests
- Repro steps or acceptance criteria updated on the work item
- Telemetry: at least one custom event or metric for the feature
- Deployed to the demo environment and smoke-tested
"""

@app.mcp_prompt_trigger(
    arg_name="context",
    prompt_name="standup",
    description="Run the daily stand-up the way this team does it: board, blockers, bugs, one decision.",
    prompt_arguments=[func.PromptArgument("focus", "Optional focus, e.g. 'release readiness'.", required=False)],
)
def standup_prompt(context: func.PromptInvocationContext) -> str:
    focus = context.arguments.get("focus", "") or ""  # azure-functions 2.x hands prompts a PromptInvocationContext, not JSON
    logging.info("prompt standup focus=%r", focus)
    return f"""You are running the daily stand-up for the {TEAM}. {('Focus: ' + focus) if focus else ''}
1. Call sprint_board and summarise progress by state in two sentences.
2. Call open_bugs (max_priority 1) and name the single most urgent bug with its owner.
3. Call pipeline_health and flag any failed run in the last 24h.
4. Check whether the Done items actually meet the team's Definition of Done (also served as the MCP resource ado://team/definition-of-done):
{DEFINITION_OF_DONE}
5. End with exactly one recommended decision for today. Keep the whole thing under 150 words.
Answer in German if the user writes in German."""


@app.mcp_resource_trigger(
    arg_name="context",
    uri="ado://team/definition-of-done",
    resource_name="Definition of Done",
    description="The team's Definition of Done. Agents should read this before marking anything as finished.",
    mime_type="text/markdown",
)
def definition_of_done(context) -> str:
    logging.info("resource ado://team/definition-of-done")
    return DEFINITION_OF_DONE
