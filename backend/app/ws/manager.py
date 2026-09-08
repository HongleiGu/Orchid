"""Run-event broker.

Transport-agnostic fan-out for run events. Producers call `broadcast`;
consumers call `subscribe` and get an async iterator of JSON strings.

When Redis is configured, events are published to `run:<run_id>` so multiple
backend workers reach the same client. Without Redis (dev / single worker),
delivery is an in-process asyncio.Queue per subscriber and no external
dependency is required.

Historically this served WebSockets, hence the module path. The transport is
now SSE: the stream is strictly server-to-client, so the bidirectional half of
a WebSocket was never used, and SSE reconnects on its own and authenticates
with ordinary headers instead of a token in the query string.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import AsyncIterator

logger = logging.getLogger(__name__)

# Bound per-subscriber queues so one stalled client cannot grow without limit.
# Dropping the slowest events is acceptable: the client reconnects with
# Last-Event-ID and the durable run_events table backfills whatever it missed.
SUBSCRIBER_QUEUE_MAXSIZE = 1000


class RunEventBroker:
    def __init__(self) -> None:
        # run_id → set of subscriber queues (in-process delivery)
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._redis = None          # redis.asyncio.Redis | None

    async def startup(self) -> None:
        from app.config import get_settings
        url = get_settings().redis_url
        if url:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(url, decode_responses=True)
                await self._redis.ping()
                logger.info("Run-event broker using Redis pub/sub")
            except Exception as exc:
                logger.warning("Redis unavailable (%s) — falling back to in-process mode", exc)
                self._redis = None
        else:
            logger.info("Run-event broker using in-process mode (no REDIS_URL)")

    async def shutdown(self) -> None:
        if self._redis:
            await self._redis.aclose()

    # ── Publish ───────────────────────────────────────────────────────────────

    async def broadcast(self, run_id: str, data: dict) -> None:
        message = json.dumps(data)
        if self._redis:
            await self._redis.publish(f"run:{run_id}", message)
        # Local subscribers are served directly in both modes, so a single-worker
        # deployment does not need a Redis round trip to see its own events.
        for q in list(self._subscribers.get(run_id, ())):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning("Subscriber queue full for run %s — dropping event", run_id)

    # ── Subscribe ─────────────────────────────────────────────────────────────

    @asynccontextmanager
    async def subscribe(self, run_id: str) -> AsyncIterator[asyncio.Queue]:
        """Hand out a queue of JSON event strings for the duration of the block.

        A queue rather than an async generator on purpose. A consumer needs a
        timeout to emit SSE keepalives, and `asyncio.wait_for` cancels whatever
        it is waiting on — cancelling `agen.__anext__()` throws into the
        generator, runs its `finally`, and destroys the subscription, so the
        stream would die at the first keepalive. Cancelling `queue.get()` is
        harmless.

        Subscribe before replaying history: an event emitted between the replay
        query and the subscription would otherwise be lost. The caller
        de-duplicates by sequence number.
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_MAXSIZE)
        self._subscribers[run_id].add(queue)

        pubsub = None
        redis_task: asyncio.Task | None = None
        if self._redis:
            pubsub = self._redis.pubsub()
            await pubsub.subscribe(f"run:{run_id}")

            async def _pump() -> None:
                async for msg in pubsub.listen():
                    if msg["type"] == "message":
                        try:
                            queue.put_nowait(msg["data"])
                        except asyncio.QueueFull:
                            logger.warning("Subscriber queue full for run %s", run_id)

            redis_task = asyncio.create_task(_pump())

        try:
            yield queue
        finally:
            self._subscribers[run_id].discard(queue)
            if not self._subscribers[run_id]:
                self._subscribers.pop(run_id, None)
            if redis_task:
                redis_task.cancel()
            if pubsub:
                await pubsub.unsubscribe(f"run:{run_id}")
                await pubsub.aclose()


# Module-level singleton. Name kept as `ws_manager` only to avoid churning the
# many producers that import it; it is no longer WebSocket-specific.
ws_manager = RunEventBroker()
run_events = ws_manager
