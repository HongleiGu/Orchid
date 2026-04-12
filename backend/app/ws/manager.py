"""
WebSocket connection manager.

When Redis is configured, run events are published to a Redis channel
`run:<run_id>` and any connected WS clients subscribe via a Redis listener.
This lets multiple backend workers broadcast to the same client.

When Redis is absent (dev / single-worker), an in-process asyncio.Queue is
used instead — no external dependency required.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self) -> None:
        # run_id → set of connected WebSocket objects (in-process mode)
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._redis = None          # redis.asyncio.Redis | None
        self._redis_task: asyncio.Task | None = None

    async def startup(self) -> None:
        from app.config import get_settings
        url = get_settings().redis_url
        if url:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(url, decode_responses=True)
                await self._redis.ping()
                logger.info("WebSocket manager using Redis pub/sub")
            except Exception as exc:
                logger.warning("Redis unavailable (%s) — falling back to in-process mode", exc)
                self._redis = None
        else:
            logger.info("WebSocket manager using in-process mode (no REDIS_URL)")

    async def shutdown(self) -> None:
        if self._redis:
            await self._redis.aclose()

    # ── Connection lifecycle ──────────────────────────────────────────────────

    async def connect(self, run_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._connections[run_id].add(ws)
        logger.debug("WS client connected for run %s", run_id)

    def disconnect(self, run_id: str, ws: WebSocket) -> None:
        self._connections[run_id].discard(ws)
        logger.debug("WS client disconnected from run %s", run_id)

    # ── Broadcast ─────────────────────────────────────────────────────────────

    async def broadcast(self, run_id: str, data: dict) -> None:
        message = json.dumps(data)
        if self._redis:
            await self._redis.publish(f"run:{run_id}", message)
        # Also push to any direct in-process connections (covers both modes)
        dead: list[WebSocket] = []
        for ws in list(self._connections.get(run_id, [])):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(run_id, ws)

    async def listen(self, run_id: str, ws: WebSocket) -> None:
        """
        Long-lived listener: forwards Redis pub/sub messages to the WebSocket.
        Falls back to just keeping the socket open (in-process mode already
        pushes via broadcast → direct connections dict).
        """
        if not self._redis:
            # In-process mode: broadcast() writes directly; just keep alive
            try:
                while True:
                    await asyncio.sleep(30)
                    await ws.send_text(json.dumps({"type": "ping"}))
            except Exception:
                return

        pubsub = self._redis.pubsub()
        await pubsub.subscribe(f"run:{run_id}")
        try:
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    try:
                        await ws.send_text(msg["data"])
                    except Exception:
                        break
        finally:
            await pubsub.unsubscribe(f"run:{run_id}")
            await pubsub.aclose()


ws_manager = WebSocketManager()
