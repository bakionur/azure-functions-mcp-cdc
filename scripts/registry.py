"""
Demo 4 · read the private MCP registry in API Center — with Entra, no anonymous access.
  python scripts/registry.py            # browser sign-in (cached after the first time)
  python scripts/registry.py --device   # device code (no browser on this machine)
  python scripts/registry.py --json     # raw registry JSON (the v0.1 MCP registry API)
Only people/identities with "Azure API Center Data Reader" see the list; everyone else gets 403.
"""
import json
import subprocess
import sys

import requests
from azure.identity import DeviceCodeCredential, InteractiveBrowserCredential, TokenCachePersistenceOptions

env = {k: v.strip('"') for k, v in (ln.split("=", 1) for ln in subprocess.run(
    ["azd", "env", "get-values"], capture_output=True, text=True, shell=sys.platform == "win32").stdout.splitlines() if "=" in ln)}
cache = TokenCachePersistenceOptions(name="cdc-apic-registry", allow_unencrypted_storage=True)
kw = dict(client_id=env["APIC_CLIENT_ID"], tenant_id=env["AZURE_TENANT_ID"], cache_persistence_options=cache)
cred = DeviceCodeCredential(**kw) if "--device" in sys.argv else InteractiveBrowserCredential(redirect_uri="http://localhost:8400", **kw)
token = cred.get_token("https://azure-apicenter.net/user_impersonation").token

r = requests.get(env["APIC_REGISTRY_URL"], headers={"Authorization": f"Bearer {token}"}, timeout=30)
r.raise_for_status()
data = r.json()
if "--json" in sys.argv:
    print(json.dumps(data, indent=2))
    sys.exit()
print(f"MCP registry · {env['APIC_REGISTRY_URL']}\n")
for entry in data.get("servers", []):
    s = entry.get("server", entry)
    urls = ", ".join(x.get("url", "") for x in s.get("remotes", []))
    print(f"  {s.get('name', '?'):<16} {s.get('description', '')[:70]}\n  {'':<16} {urls}\n")
