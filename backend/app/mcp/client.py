"""
MCP client — connects to an MCP server and wraps its tools as BaseTool instances.

Supported transports
--------------------
* stdio  — spawn a local process (e.g. npx @modelcontextprotocol/server-filesystem)
* sse    — connect to a remote HTTP/SSE MCP endpoint

Config example (mcp_servers.json)
----------------------------------
[
  {
    "name": "filesystem",
    "transport": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
  },
  {
    "name": "github",
    "transport": "sse",
    "url": "http://localhost:3001/sse"
  }
]
"""
from __future__ import annotations

import logging
from typing import Any

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class MCPTool(BaseTool):
    """A BaseTool backed by a single MCP tool call."""

    def __init__(self, name: str, description: str, parameters: dict, session: Any) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self._session = session

    async def call(self, **kwargs) -> str:
        result = await self._session.call_tool(self.name, arguments=kwargs)
        # MCP returns a list of content blocks; flatten to text
        parts: list[str] = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "\n".join(parts)


async def connect_stdio(command: str, args: list[str]) -> list[MCPTool]:
    """Spawn an MCP server as a subprocess and return its tools."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server_params = StdioServerParameters(command=command, args=args)
    tools: list[MCPTool] = []

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            resp = await session.list_tools()
            for t in resp.tools:
                tools.append(MCPTool(
                    name=t.name,
                    description=t.description or t.name,
                    parameters=t.inputSchema or {"type": "object", "properties": {}},
                    session=session,
                ))
    return tools


async def connect_sse(url: str) -> list[MCPTool]:
    """Connect to a remote MCP server over SSE and return its tools."""
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    tools: list[MCPTool] = []
    async with sse_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            resp = await session.list_tools()
            for t in resp.tools:
                tools.append(MCPTool(
                    name=t.name,
                    description=t.description or t.name,
                    parameters=t.inputSchema or {"type": "object", "properties": {}},
                    session=session,
                ))
    return tools
