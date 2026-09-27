"""
Tiny MCP Streamable-HTTP probe (no SDK): initialize -> tools/prompts/resources list, optional calls.
  python scripts/mcp_probe.py http://localhost:7071/runtime/webhooks/mcp
  python scripts/mcp_probe.py <url> --key <mcp_extension key> --call flights_overhead '{"radius_nm":30}'
  python scripts/mcp_probe.py <url> --read ui://skywatch/radar.html
  python scripts/mcp_probe.py <url> --prompt standup '{"focus":"release"}'
"""
import argparse
import json
import sys

import requests


class Probe:
    def __init__(self, url: str, key: str = ""):
        self.url, self.n, self.session = url, 0, None
        self.h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if key:
            self.h["x-functions-key"] = key

    def rpc(self, method: str, params: dict | None = None, notify: bool = False):
        body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            self.n += 1
            body["id"] = self.n
        h = dict(self.h)
        if self.session:
            h["Mcp-Session-Id"] = self.session
        r = requests.post(self.url, headers=h, json=body, timeout=60)
        self.session = r.headers.get("Mcp-Session-Id", self.session)
        if notify:
            return r.status_code
        r.raise_for_status()
        text = r.text
        if "text/event-stream" in r.headers.get("Content-Type", ""):
            data = [ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")]
            text = data[-1] if data else "{}"
        msg = json.loads(text)
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error']}")
        return msg["result"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--key", default="")
    ap.add_argument("--call", nargs=2, metavar=("TOOL", "JSON_ARGS"))
    ap.add_argument("--read", metavar="URI")
    ap.add_argument("--prompt", nargs=2, metavar=("NAME", "JSON_ARGS"))
    ap.add_argument("--full", action="store_true", help="print full JSON instead of a summary")
    a = ap.parse_args()

    p = Probe(a.url, a.key)
    init = p.rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                "clientInfo": {"name": "cdc-probe", "version": "1.0"}})
    p.rpc("notifications/initialized", notify=True)
    print(f"server: {init['serverInfo']}  protocol: {init['protocolVersion']}  caps: {sorted(init['capabilities'])}")

    tools = p.rpc("tools/list")["tools"]
    print(f"tools ({len(tools)}):", ", ".join(t["name"] for t in tools))
    if a.full:
        print(json.dumps(tools, indent=2))
    if "prompts" in init["capabilities"]:
        prompts = p.rpc("prompts/list")["prompts"]
        print(f"prompts ({len(prompts)}):", ", ".join(x["name"] for x in prompts))
    if "resources" in init["capabilities"]:
        res = p.rpc("resources/list")["resources"]
        print(f"resources ({len(res)}):", ", ".join(x["uri"] for x in res))

    out = None
    if a.call:
        out = p.rpc("tools/call", {"name": a.call[0], "arguments": json.loads(a.call[1])})
    elif a.read:
        out = p.rpc("resources/read", {"uri": a.read})
    elif a.prompt:
        out = p.rpc("prompts/get", {"name": a.prompt[0], "arguments": json.loads(a.prompt[1])})
    if out is not None:
        s = json.dumps(out, indent=2, ensure_ascii=False)
        print(s if a.full or len(s) < 4000 else s[:4000] + f"\n… ({len(s)} chars)")


if __name__ == "__main__":
    sys.exit(main())
