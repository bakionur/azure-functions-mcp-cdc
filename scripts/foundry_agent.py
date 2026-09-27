"""
Demo 4 · the SAME Functions MCP servers, consumed by an Azure AI Foundry agent (no client-specific code).

  python scripts/foundry_agent.py setup                 # key connections + agent version (idempotent, run after azd up)
  python scripts/foundry_agent.py ask "What is flying over Hanau, and name a pizza place after the nearest airline?"
  python scripts/foundry_agent.py ask --yes "…"        # auto-approve (testing only)
  python scripts/foundry_agent.py cleanup               # delete the agent (connections stay)

Reads everything from `azd env get-values`. Keys never touch git: the mcp_extension system key of each app is
fetched from ARM at setup time and stored in a Foundry project connection (category RemoteTool, CustomKeys),
which the agent references by name — the recommended pattern (store shared credentials in a project connection).
Needs: pip install -r scripts/requirements.txt ; az login (DefaultAzureCredential) with Foundry Project Manager.
"""
import subprocess
import sys

import requests
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MCPTool, MCPToolFilter, MCPToolRequireApproval, PromptAgentDefinition
from azure.identity import DefaultAzureCredential
from openai.types.responses.response_input_param import McpApprovalResponse

AGENT = "cdc-skywatch-domainforge"
ARM = "https://management.azure.com"
CONN_API = "2026-07-01"
cred = DefaultAzureCredential()


def azd_env() -> dict:
    out = subprocess.run(["azd", "env", "get-values"], capture_output=True, text=True, check=True).stdout
    return {k: v.strip().strip('"') for k, v in (ln.split("=", 1) for ln in out.splitlines() if "=" in ln)}


def arm(method: str, path: str, api: str, body: dict | None = None) -> dict:
    token = cred.get_token(f"{ARM}/.default").token
    for attempt in range(3):  # venue Wi-Fi: retry transient resets
        try:
            r = requests.request(method, f"{ARM}{path}?api-version={api}", json=body, timeout=60,
                                 headers={"Authorization": f"Bearer {token}"})
            break
        except requests.ConnectionError:
            if attempt == 2:
                raise
    if r.status_code >= 400:
        sys.exit(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
    return r.json() if r.text else {}


def servers(env: dict) -> list[dict]:
    return [
        {"label": "skywatch", "url": env["MCP_SKYWATCH_URL"], "app": env["APP_SKYWATCH"],
         "approve": [], "free": ["flights_overhead", "find_flight", "radar_image"]},
        # reserve_domain writes a blob → the agent must ask first (human-in-the-loop); reads run freely
        {"label": "domainforge", "url": env["MCP_DOMAINFORGE_URL"], "app": env["APP_DOMAINFORGE"],
         "approve": ["reserve_domain"], "free": ["brainstorm_domains", "check_domains"]},
    ]


def setup(env: dict) -> None:
    rg = f"/subscriptions/{env['AZURE_SUBSCRIPTION_ID']}/resourceGroups/{env['RESOURCE_GROUP']}"
    tools = []
    for s in servers(env):
        if s["label"] == "skywatch" and env.get("APIM_GATEWAY_URL"):
            # optional gateway path: the agent only holds an APIM subscription key; APIM injects the Functions key + rate-limits
            s["url"] = env["APIM_GATEWAY_URL"]
            header = {"Ocp-Apim-Subscription-Key": arm("POST", f"{env['APIM_SUBSCRIPTION_ID']}/listSecrets", "2024-05-01")["primaryKey"]}
        else:
            header = {"x-functions-key": arm("POST", f"{rg}/providers/Microsoft.Web/sites/{s['app']}/host/default/listkeys", "2024-04-01")["systemKeys"]["mcp_extension"]}
        conn = f"{s['label']}-key"
        arm("PUT", f"{env['FOUNDRY_PROJECT_ID']}/connections/{conn}", CONN_API, {"properties": {
            "category": "RemoteTool", "target": s["url"], "authType": "CustomKeys",
            "credentials": {"keys": header}, "isSharedToAll": True}})
        print(f"connection {conn} -> {s['url']}")
        # unlisted tools default to "always" → list the read-only ones explicitly under never
        approval = (MCPToolRequireApproval(always=MCPToolFilter(tool_names=s["approve"]), never=MCPToolFilter(tool_names=s["free"]))
                    if s["approve"] else "never")
        tools.append(MCPTool(server_label=s["label"], server_url=s["url"], project_connection_id=conn, require_approval=approval))

    project = AIProjectClient(endpoint=env["FOUNDRY_PROJECT_ENDPOINT"], credential=cred)
    agent = project.agents.create_version(agent_name=AGENT, definition=PromptAgentDefinition(
        model=env.get("FOUNDRY_MODEL", "gpt-5.4-mini"),
        instructions=("You are the CDC-Germany 2026 demo agent in Hanau. Use skywatch for anything about aircraft "
                      "overhead and domainforge for business names and domains. Keep answers under 120 words. "
                      "When the user asks you to reserve a domain, call reserve_domain directly — the platform asks the human to "
                      "approve that call, so do not ask for confirmation in text first."),
        tools=tools))
    print(f"agent {agent.name} v{agent.version} ready in Foundry (model {env.get('FOUNDRY_MODEL', 'gpt-5.4-mini')})")


def ask(env: dict, question: str, auto: bool = False) -> None:
    project = AIProjectClient(endpoint=env["FOUNDRY_PROJECT_ENDPOINT"], credential=cred)
    oai = project.get_openai_client()
    ref = {"agent_reference": {"name": AGENT, "type": "agent_reference"}}
    resp = oai.responses.create(conversation=oai.conversations.create().id, input=question, extra_body=ref)
    while True:
        for item in resp.output:
            if item.type == "mcp_call":
                print(f"  → {item.server_label}.{item.name}({item.arguments})")
        pending = [i for i in resp.output if i.type == "mcp_approval_request"]
        if not pending:
            break
        answers = []
        for item in pending:  # human-in-the-loop
            prompt = f"  ? approve {item.server_label}.{item.name}({item.arguments}) [Y/n] "
            ok = print(prompt + "y (--yes)") is None if auto else input(prompt).strip().lower() != "n"
            answers.append(McpApprovalResponse(type="mcp_approval_response", approve=ok, approval_request_id=item.id))
        resp = oai.responses.create(input=answers, previous_response_id=resp.id, extra_body=ref)
    print("\n" + resp.output_text)


def cleanup() -> None:
    env = azd_env()
    project = AIProjectClient(endpoint=env["FOUNDRY_PROJECT_ENDPOINT"], credential=cred)
    project.agents.delete(agent_name=AGENT)
    print(f"deleted agent {AGENT}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "setup"
    if cmd == "setup":
        setup(azd_env())
    elif cmd == "ask":
        words = [w for w in sys.argv[2:] if w != "--yes"]
        ask(azd_env(), " ".join(words) or "What is flying over Hanau right now?", auto="--yes" in sys.argv)
    elif cmd == "cleanup":
        cleanup()
    else:
        sys.exit(__doc__)
