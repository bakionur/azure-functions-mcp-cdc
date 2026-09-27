# Azure Functions as MCP Servers — four demos, one `azd up`

Four remote [Model Context Protocol](https://modelcontextprotocol.io) servers on **Azure Functions (Flex Consumption)**,
from "a script on my laptop" to "an Entra-protected, discoverable tool platform that any agent can use":

| # | Server | Hosting model | What it shows |
|---|---|---|---|
| 1 | **concierge** (`local/`) | **Self-hosted** MCP SDK server | The *same* Python file runs over stdio on your laptop and as a remote server on Functions (`host.json` → `mcp-custom-handler`). Tools over a live conference agenda. |
| 2 | **skywatch** (`servers/skywatch`) | Functions **MCP extension** | Live aircraft (ADS-B) with airline and route, rendered as an **MCP App** (interactive radar inside the chat that refreshes itself); PNG fallback; resource + prompt |
| 2 | **domainforge** (`servers/domainforge`) | Functions MCP extension | Pun domain names, live availability (RDAP → DNS fallback), an **MCP App** picker whose *Reserve* button calls back into the server, which writes a ticket via a **Blob output binding** |
| 3 | **adopilot** (`servers/ado`) | MCP extension + **built-in Entra auth** | 401 → protected resource metadata → Entra sign-in; the server calls **Microsoft Graph and Azure DevOps on behalf of the signed-in user** — no PAT, no client secret |
| 4 | *all of them* | **API Center** + **Foundry** (+ optional **APIM**) | A private, Entra-only MCP registry, and a Foundry agent that uses the same servers with human approval for writes |

One MCP endpoint per function app (`/runtime/webhooks/mcp`, self-hosted: `/mcp`), so each server scales, is secured
and is deleted on its own.

## Architecture

```
 VS Code / Copilot · Foundry agent · any MCP client
        │  Streamable HTTP  (key, or Entra token)
        ▼
 ┌─────────────── Azure Functions · Flex Consumption (Python 3.13) ────────────────┐
 │ concierge (self-hosted SDK)   skywatch (MCP App)   domainforge (MCP App)   ado   │
 └──────┬──────────────────────────────┬───────────────────┬────────────────────┬──┘
        │ event agenda API             │ adsb.lol, adsbdb   │ RDAP, DNS, Blob    │ Graph, Azure DevOps (OBO)
        ▼                              ▼                    ▼                    ▼
 User-assigned managed identity · storage without shared keys · App Insights (Entra auth)
 API Center (MCP registry, Entra-only) · Foundry project + model · optional APIM gateway
```

## Prerequisites

- Azure subscription where you can create resources **and** register apps in Entra ID (the adopilot demo creates an
  app registration with the Microsoft Graph Bicep extension)
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli), [Azure Developer CLI](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd) ≥ 1.34, Python 3.13, Node.js 20+
- Optional: an Azure DevOps organization **connected to the same Entra tenant** (for adopilot's board tools)
- VS Code with GitHub Copilot (agent mode) to try the MCP Apps widgets

## Quick start

```bash
git clone https://github.com/bakionur/azure-functions-mcp-cdc && cd azure-functions-mcp-cdc
cp settings.env.sample settings.env        # fill in subscription, tenant, optional ADO org/project
python3.13 -m venv .venv && source .venv/bin/activate      # PowerShell: ./.venv/bin/Activate.ps1
pip install -r scripts/requirements.txt -r local/requirements.txt
az login --tenant <your-tenant-id>
azd auth login --tenant-id <your-tenant-id>
./scripts/up.sh                            # PowerShell: ./scripts/up.ps1
```

`up` pushes `settings.env` into an azd environment, runs `azd up` (≈ 10 min the first time) and a smoke test.
The `postdeploy` hook writes `.vscode/mcp.json` (gitignored — it contains function keys) and creates the Foundry agent.
Optional: `python scripts/seed_ado.py` seeds a sprint and a small backlog in your Azure DevOps project (Entra sign-in, no PAT).

Change a setting later: edit `settings.env`, then `./scripts/apply-settings.sh --provision`.
Tear down: `azd down --purge` (the Entra app registrations remain; delete them in Entra if you like).

## Try it in VS Code (Copilot Chat, agent mode)

| Server | Ask |
|---|---|
| concierge | "Where and when is lunch?" · "What's on right now?" · "Plan my Thursday: AI, security, Azure." · "Give me a buzzword bingo card." |
| skywatch | "What's flying over us right now?" → the radar renders in the chat · "Where are the three nearest planes going?" |
| domainforge | `/name_my_business` → pizza, Hanau → picker widget → click **Reserve** → a JSON ticket appears in the `reservations` container |
| adopilot | "Who am I signed in as?" · "What's on our sprint board?" · "What are the open P1 bugs?" · `/standup` |

Foundry: `python scripts/foundry_agent.py ask "What is flying over Hanau, and name a pizza place after the nearest airline?"`
API Center registry (Entra sign-in): `python scripts/registry.py`

## Security model

- **No secrets in the repo, in app settings or in the client for the Entra path.** Storage and telemetry use a
  user-assigned managed identity; Entra's app registration uses that identity as a federated credential instead of a
  client secret; adopilot calls Graph and Azure DevOps **on behalf of the user**.
- Function keys (concierge, skywatch, domainforge) are for demos. They live only in the generated, gitignored
  `.vscode/mcp.json` and in Foundry project connections. Anything shared should use Entra (see `infra/modules/entra.bicep`).
- The API Center registry is readable with Entra only (Azure API Center Data Reader), no anonymous access.

## Lessons learned (all fixed in this repo)

- `azure-functions` 2.x: prompt triggers receive `PromptInvocationContext` (use `context.arguments`); tools returning a
  plain `dict` need `@app.mcp_tool(use_result_schema=True)`; a bare `-> List` return annotation is serialised with
  `str()`; `mcp_tool_property(as_array=True)` for array parameters.
- `mcp` 2.x renamed `FastMCP` to `MCPServer`; for self-hosting on Functions disable the localhost DNS-rebinding check.
- VS Code sends an RFC 8707 `resource` parameter (the server URL) with the `api://…` scope: add the server URLs as
  identifier URIs of the Entra app, or Entra answers AADSTS9010010.
- VS Code agents can't read MCP resources on their own — prompts that depend on a resource should include its content.
- `rdap.org` returns 404 both for "not registered" and "TLD has no RDAP" (e.g. `.de`) → confirm with DNS.
- Flex plans created in parallel in one resource group can fail → `@batchSize(1)`.
- Scrum projects have no "Active" state: map natural-language filters to each process's states.

## Repository layout

```
azure.yaml            azd: 4 services + hooks (widget build, mcp.json, Foundry agent)
infra/                main.bicep + modules: entra (Graph extension), apicenter, apicenter-client, foundry, apim (optional)
local/                concierge: server.py (stdio locally, self-hosted on Functions) + host.json
servers/skywatch/     flights_overhead (MCP App), radar_image, find_flight, airports://nearby, /plane_spotter, app/
servers/domainforge/  brainstorm_domains, check_domains (MCP App), reserve_domain (blob), /name_my_business, app/
servers/ado/          whoami, sprint_board, open_bugs, create_bug, pipeline_health, /standup, ado://team/definition-of-done
scripts/              up · apply-settings · smoke · foundry_agent · registry · seed_ado · mcp_probe · write-mcp-json
settings.env.sample   every setting in one file (copy to settings.env, which is gitignored)
```

## Useful links

- Remote MCP servers on Azure Functions: <https://aka.ms/remote-mcp>
- Azure Functions MCP extension: <https://github.com/Azure/azure-functions-mcp-extension>
- Tutorial: <https://learn.microsoft.com/azure/azure-functions/functions-mcp-tutorial>
- Self-hosted MCP servers on Functions: <https://learn.microsoft.com/azure/azure-functions/self-hosted-mcp-servers>
- MCP Apps: <https://modelcontextprotocol.io/extensions/apps/overview>

Demo code — use at your own risk; review costs (Foundry, always-ready instances, optional APIM) before deploying.

## License

MIT — see [LICENSE](LICENSE).
