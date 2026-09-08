"""Run-event broker and SSE framing.

Covers fan-out, subscriber lifecycle, and the frame format. The endpoint's
replay-from-run_events path is not covered here — that needs a database
fixture, and this repo has no DB test infrastructure yet; building one is worth
doing deliberately rather than as a side effect of this change.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.api.v1.runs import _sse
from app.ws import manager as mgr
from app.ws.manager import RunEventBroker


# ── SSE framing ───────────────────────────────────────────────────────────────

def test_frame_carries_id_and_terminates_with_blank_line():
    frame = _sse(7, '{"type":"AGENT_START"}')
    assert frame == 'id: 7\ndata: {"type":"AGENT_START"}\n\n'
    # The trailing blank line is what tells the client the event is complete.
    assert frame.endswith("\n\n")


def test_frame_without_id_omits_the_id_line():
    """An event with no sequence must not emit `id:`, or a reconnecting client
    would resume from a bogus Last-Event-ID."""
    frame = _sse(None, "{}")
    assert frame == "data: {}\n\n"
    assert "id:" not in frame


# ── Broker fan-out ────────────────────────────────────────────────────────────

async def test_subscriber_receives_broadcast():
    broker = RunEventBroker()
    async with broker.subscribe("run-1") as q:
        await broker.broadcast("run-1", {"type": "AGENT_START", "seq": 1})
        msg = await asyncio.wait_for(q.get(), timeout=1.0)
    assert json.loads(msg)["type"] == "AGENT_START"


async def test_every_subscriber_gets_a_copy():
    """Two browser tabs on the same run must both stream."""
    broker = RunEventBroker()
    async with broker.subscribe("run-1") as a, broker.subscribe("run-1") as b:
        await broker.broadcast("run-1", {"seq": 1})
        assert json.loads(await asyncio.wait_for(a.get(), 1.0))["seq"] == 1
        assert json.loads(await asyncio.wait_for(b.get(), 1.0))["seq"] == 1


async def test_events_do_not_leak_between_runs():
    broker = RunEventBroker()
    async with broker.subscribe("run-1") as q:
        await broker.broadcast("run-2", {"seq": 99})
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(q.get(), timeout=0.05)


async def test_timing_out_on_get_does_not_kill_the_subscription():
    """The keepalive path: the endpoint waits with a timeout, and a timeout
    must leave the subscription usable. Cancelling an async generator's
    __anext__ would have torn it down instead — the reason this is a queue."""
    broker = RunEventBroker()
    async with broker.subscribe("run-1") as q:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(q.get(), timeout=0.05)

        # Still subscribed, and still delivering.
        await broker.broadcast("run-1", {"seq": 1})
        assert json.loads(await asyncio.wait_for(q.get(), 1.0))["seq"] == 1


async def test_leaving_the_block_removes_the_queue():
    """A leaked queue would retain every event for a finished run forever."""
    broker = RunEventBroker()
    async with broker.subscribe("run-1"):
        assert len(broker._subscribers["run-1"]) == 1
    assert "run-1" not in broker._subscribers


async def test_a_stalled_subscriber_does_not_break_broadcast(caplog):
    """A client that stops reading must not raise into the producer.

    Dropping events for that subscriber is the intended trade: it reconnects
    with Last-Event-ID and the durable table backfills what it missed.
    """
    broker = RunEventBroker()
    async with broker.subscribe("run-1"):
        for i in range(mgr.SUBSCRIBER_QUEUE_MAXSIZE + 50):
            await broker.broadcast("run-1", {"seq": i})   # must not raise
    assert "queue full" in caplog.text.lower()


async def test_broadcast_with_no_subscribers_is_a_noop():
    await RunEventBroker().broadcast("nobody-listening", {"seq": 1})
