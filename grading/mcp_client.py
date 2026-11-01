"""Thin async client for the davinci-resolve MCP server (stdio).

Every pipeline step talks to Resolve through this, so the same code works on any machine
that has the MCP server installed. The server entry is read from an MCP client config
(.mcp.json / claude_desktop_config.json style): {"mcpServers": {"davinci-resolve": {...}}}.
"""
from __future__ import annotations

import base64
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def load_server(mcp_config: str | Path, name: str = "davinci-resolve") -> dict:
    cfg = json.loads(Path(mcp_config).read_text(encoding="utf-8"))
    servers = cfg.get("mcpServers") or cfg.get("servers") or {}
    if name not in servers:
        raise SystemExit(f"MCP config {mcp_config} has no '{name}' server (found: {', '.join(servers) or 'none'})")
    return servers[name]


def payload(res) -> Any:
    """Unwrap a tool result: JSON text -> dict, and lift {'result': ...}."""
    text = "".join(getattr(c, "text", "") or "" for c in res.content)
    try:
        data = json.loads(text)
    except Exception:
        return {"raw": text[:500]}
    if isinstance(data, dict) and "result" in data and isinstance(data["result"], dict):
        return data["result"]
    return data


def first_image(res) -> bytes | None:
    for c in res.content:
        if getattr(c, "type", "") == "image":
            return base64.b64decode(c.data)
    return None


class Resolve:
    """Convenience wrapper: await r.call('timeline', 'get_current', {...})."""

    def __init__(self, session: ClientSession):
        self.s = session

    async def call(self, tool: str, action: str, params: dict | None = None) -> Any:
        res = await self.s.call_tool(tool, {"action": action, "params": params or {}})
        data = payload(res)
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict) and err.get("category") == "not_connected":
            raise SystemExit(
                f"\nLost the connection to Resolve during {tool}.{action}.\n"
                "Free edition: Resolve was restarted or the bridge stopped. Open a project, then run "
                "Workspace > Scripts > resolve_bridge, and re-run this command.\n"
                "Studio: check Preferences > General > External scripting = Local.")
        return data

    async def raw(self, tool: str, action: str, params: dict | None = None):
        return await self.s.call_tool(tool, {"action": action, "params": params or {}})

    async def confirmed(self, tool: str, action: str, params: dict) -> Any:
        """Run a confirm-token-gated action (the server's destructive-op guard) in one go.

        Only use for operations the pipeline owns, e.g. replacing the graph of a version it just created.
        """
        first = await self.call(tool, action, params)
        tok = None
        if isinstance(first, dict):
            tok = first.get("confirm_token") or (first.get("error") or {}).get("confirm_token")
        if not tok:
            return first
        return await self.call(tool, action, {**params, "confirm_token": tok})


@asynccontextmanager
async def connect(mcp_config: str | Path, name: str = "davinci-resolve"):
    srv = load_server(mcp_config, name)
    # UTF-8 for the server's own logging: on Windows consoles (cp1252) its '->' arrows spam encode errors
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", **(srv.get("env") or {})}
    params = StdioServerParameters(command=srv["command"], args=srv.get("args", []), env=env)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            yield Resolve(s)
