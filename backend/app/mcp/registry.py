"""
MCP registry — reads mcp_servers.json at startup and injects each server's
tools into the global ToolRegistry.

The session lifecycle is a known trade-off for stdio servers: each tool call
reconnects.  For long-running deployments, SSE servers are preferred.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def load_mcp_servers(config_path: Path) -> None:
    """Parse config_path and register all MCP tools into tool_registry."""
    from app.tools.registry import tool_registry
    from app.mcp.client import connect_stdio, connect_sse

    if not config_path.exists():
        logger.warning("MCP config not found at %s — skipping MCP setup.", config_path)
        return

    try:
        servers = json.loads(config_path.read_text())
    except json.JSONDecodeError as exc:
        logger.error("Invalid MCP config JSON: %s", exc)
        return

    for srv in servers:
        name = srv.get("name", "unknown")
        transport = srv.get("transport", "stdio")
        try:
            if transport == "stdio":
                tools = await connect_stdio(srv["command"], srv.get("args", []))
            elif transport == "sse":
                tools = await connect_sse(srv["url"])
            else:
                logger.warning("Unknown MCP transport %r for server %r", transport, name)
                continue

            for tool in tools:
                tool_registry.register(tool)
                logger.info("Registered MCP tool %r from server %r", tool.name, name)

        except Exception:
            logger.error("Failed to load MCP server %r", name, exc_info=True)
