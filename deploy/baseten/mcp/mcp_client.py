#!/usr/bin/env python3
"""Minimal MCP (streamable HTTP) client for Baseten's hosted MCP servers.

Usage:
  python3 mcp_client.py list-tools [--docs]
  python3 mcp_client.py call <tool_name> '<json_args>' [--docs]

Auth: BASETEN_API_KEY env var (backend server only). Never printed.
"""
import json
import os
import sys
import urllib.request

BACKEND = "https://api.baseten.co/mcp"
DOCS = "https://docs.baseten.co/mcp"


class McpClient:
    def __init__(self, url, auth=None):
        self.url = url
        self.auth = auth
        self.session_id = None
        self._id = 0

    def _post(self, payload, expect_response=True):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.auth:
            headers["Authorization"] = f"Bearer {self.auth}"
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(
            self.url, data=json.dumps(payload).encode(), headers=headers
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            sid = resp.headers.get("Mcp-Session-Id")
            if sid:
                self.session_id = sid
            body = resp.read().decode()
            ctype = resp.headers.get("Content-Type", "")
        if not expect_response:
            return None
        if "text/event-stream" in ctype:
            # parse SSE: take last data: line that is valid JSON-RPC response
            result = None
            for line in body.splitlines():
                if line.startswith("data:"):
                    try:
                        msg = json.loads(line[5:].strip())
                        if "id" in msg:
                            result = msg
                    except json.JSONDecodeError:
                        pass
            return result
        return json.loads(body) if body.strip() else None

    def rpc(self, method, params=None, notification=False):
        if notification:
            payload = {"jsonrpc": "2.0", "method": method}
            if params:
                payload["params"] = params
            return self._post(payload, expect_response=False)
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            payload["params"] = params
        msg = self._post(payload)
        if msg is None:
            raise RuntimeError(f"no response for {method}")
        if "error" in msg:
            raise RuntimeError(f"MCP error for {method}: {msg['error']}")
        return msg["result"]

    def initialize(self):
        r = self.rpc(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "baseten-mvp-session", "version": "1.0"},
            },
        )
        self.rpc("notifications/initialized", notification=True)
        return r


def main():
    args = [a for a in sys.argv[1:] if a != "--docs"]
    use_docs = "--docs" in sys.argv
    url = DOCS if use_docs else BACKEND
    auth = None if use_docs else os.environ["BASETEN_API_KEY"]
    c = McpClient(url, auth)
    info = c.initialize()
    server = info.get("serverInfo", {})
    print(f"# connected: {server.get('name')} {server.get('version')}", file=sys.stderr)

    cmd = args[0]
    if cmd == "list-tools":
        tools = c.rpc("tools/list").get("tools", [])
        for t in tools:
            props = list(t.get("inputSchema", {}).get("properties", {}).keys())
            ann = t.get("annotations", {}) or {}
            ro = ann.get("readOnlyHint")
            print(f"{t['name']}  readonly={ro}  args={props}")
            desc = (t.get("description") or "").strip().split("\n")[0][:150]
            print(f"    {desc}")
    elif cmd == "call":
        name = args[1]
        tool_args = json.loads(args[2]) if len(args) > 2 else {}
        result = c.rpc("tools/call", {"name": name, "arguments": tool_args})
        print(json.dumps(result, indent=2))
    else:
        print(f"unknown command {cmd}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
