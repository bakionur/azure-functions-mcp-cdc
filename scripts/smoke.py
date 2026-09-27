"""
Smoke test: every remote server answers MCP initialize + tools/list. Run it before a demo (it also warms the apps).
  python scripts/smoke.py          (reads azd env; needs az login for the keys)
ado in Entra mode is EXPECTED to answer 401 + a protected-resource-metadata pointer without a token.
"""
import os
import subprocess
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_probe import Probe  # noqa: E402


def sh(*cmd: str) -> str:
    return subprocess.run(list(cmd), capture_output=True, text=True, shell=sys.platform == "win32").stdout.strip()


env = {k: v.strip('"') for k, v in (ln.split("=", 1) for ln in sh("azd", "env", "get-values").splitlines() if "=" in ln)}
rg = env["RESOURCE_GROUP"]
def key(app: str, q: str) -> str:
    for _ in range(3):  # az occasionally returns nothing on a flaky network → retry before calling it a failure
        k = sh("az", "functionapp", "keys", "list", "-g", rg, "-n", app, "--query", q, "-o", "tsv")
        if k:
            return k
    return ""
checks = [
    ("concierge", env["MCP_CONCIERGE_URL"], key(env["APP_CONCIERGE"], "functionKeys.default")),
    ("ado", env["MCP_ADO_URL"], "" if env.get("ADO_AUTH_MODE") == "entra" else key(env["APP_ADO"], "systemKeys.mcp_extension")),
    ("skywatch", env["MCP_SKYWATCH_URL"], key(env["APP_SKYWATCH"], "systemKeys.mcp_extension")),
    ("domainforge", env["MCP_DOMAINFORGE_URL"], key(env["APP_DOMAINFORGE"], "systemKeys.mcp_extension")),
]
ok = True
for name, url, k in checks:
    try:
        if name == "ado" and not k:
            r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, timeout=60,
                              headers={"Accept": "application/json, text/event-stream"})
            prm = r.headers.get("WWW-Authenticate", "")
            good = r.status_code == 401 and "resource_metadata" in prm
            print(f"{'OK ' if good else 'BAD'} {name:<12} HTTP {r.status_code} without token (Entra) → PRM advertised")
            ok &= good
            # …and signed in as you (Azure CLI is pre-authorized): whoami must reach Graph via on-behalf-of
            scope = requests.get(url.split("/runtime/")[0] + "/.well-known/oauth-protected-resource", timeout=30).json()["scopes_supported"][0]
            p = Probe(url)
            p.h["Authorization"] = "Bearer " + sh("az", "account", "get-access-token", "--scope", scope, "--query", "accessToken", "-o", "tsv")
            p.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "1"}})
            me = p.rpc("tools/call", {"name": "whoami", "arguments": {}}).get("structuredContent", {})
            good = "graph_me" in me
            print(f"{'OK ' if good else 'BAD'} {name:<12} signed in as {me.get('caller')} · OBO→Graph {'ok' if good else me.get('graph_error', '')[:120]}")
            ok &= good
            continue
        p = Probe(url, k)
        init = p.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "1"}})
        tools = [t["name"] for t in p.rpc("tools/list")["tools"]]
        print(f"OK  {name:<12} {init['serverInfo']['name']} · {len(tools)} tools: {', '.join(tools)}")
    except Exception as ex:  # noqa: BLE001
        ok = False
        print(f"BAD {name:<12} {url}  {str(ex)[:160]}")
if env.get("APIC_REGISTRY_URL"):
    print(f"\nAPI Center portal:   {env.get('APIC_PORTAL_URL')}\nMCP registry (v0.1): {env['APIC_REGISTRY_URL']}")
sys.exit(0 if ok else 1)
