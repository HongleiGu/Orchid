"""Per-span cost attribution (OR-42).

Cost is recorded per LLM call against the span that made it, so it can roll up
the span tree /runs/{id}/spans already reconstructs — answering "the verifier
node is 60% of this run", which agent name alone cannot, because the same agent
appears in several DAG nodes and subagents nest.

The arithmetic is what is covered here: a wrong sum looks entirely plausible.
The database paths are exercised against real Postgres.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.api.v1.runs import RunCost, SpanNode, _roll_up_cost


def _span(span_id: str, parent: str | None = None, **kw) -> SpanNode:
    return SpanNode(
        span_id=span_id, parent_span_id=parent, kind=kw.pop("kind", "dag_node"),
        agent=kw.pop("agent", "a"), started_at=datetime.now(timezone.utc),
        finished_at=None, status="done", **kw,
    )


def _cost(usd: float, calls: int = 1, inp: int = 100, outp: int = 50) -> RunCost:
    return RunCost(cost_usd=usd, input_tokens=inp, output_tokens=outp, llm_calls=calls)


def _tree(*nodes: SpanNode) -> dict[str, SpanNode]:
    return {n.span_id: n for n in nodes}


# ── Own cost ──────────────────────────────────────────────────────────────────

def test_a_span_carries_what_it_spent():
    spans = _tree(_span("root"))
    _roll_up_cost(spans, {"root": _cost(0.25, calls=3)})

    node = spans["root"]
    assert node.cost_usd == 0.25
    assert node.llm_calls == 3
    assert node.subtree_cost_usd == 0.25
    assert node.subtree_share == 1.0


def test_a_span_that_spent_nothing_reports_zero_not_missing():
    """A DAG node that only fans out to children spends nothing itself. That is
    a correct answer, not an absent one."""
    spans = _tree(_span("root"), _span("child", "root"))
    _roll_up_cost(spans, {"child": _cost(0.10)})

    assert spans["root"].cost_usd == 0.0
    assert spans["root"].llm_calls == 0
    assert spans["root"].subtree_cost_usd == 0.10


# ── Rolling up ────────────────────────────────────────────────────────────────

def test_cost_accumulates_up_the_tree():
    spans = _tree(
        _span("root"),
        _span("a", "root"),
        _span("b", "root"),
        _span("a1", "a"),
    )
    _roll_up_cost(spans, {
        "root": _cost(0.01), "a": _cost(0.02), "b": _cost(0.04), "a1": _cost(0.08),
    })

    assert spans["a1"].subtree_cost_usd == 0.08
    assert spans["a"].subtree_cost_usd == pytest.approx(0.10)
    assert spans["b"].subtree_cost_usd == 0.04
    assert spans["root"].subtree_cost_usd == pytest.approx(0.15)


def test_deep_nesting_sums_once_per_node():
    """Each level is added exactly once — a node counted twice is the classic
    way a rollup silently inflates."""
    spans = _tree(
        _span("l0"), _span("l1", "l0"), _span("l2", "l1"),
        _span("l3", "l2"), _span("l4", "l3"),
    )
    _roll_up_cost(spans, {f"l{i}": _cost(1.0, calls=1) for i in range(5)})

    assert spans["l0"].subtree_cost_usd == 5.0
    assert spans["l0"].subtree_llm_calls == 5
    assert spans["l4"].subtree_cost_usd == 1.0


def test_tokens_and_calls_roll_up_with_cost():
    spans = _tree(_span("root"), _span("child", "root"))
    _roll_up_cost(spans, {
        "root": _cost(0.01, calls=1, inp=10, outp=5),
        "child": _cost(0.02, calls=2, inp=200, outp=100),
    })

    root = spans["root"]
    assert root.subtree_input_tokens == 210
    assert root.subtree_output_tokens == 105
    assert root.subtree_llm_calls == 3


def test_several_roots_are_independent():
    """A run can have more than one top-level span; they must not merge."""
    spans = _tree(_span("r1"), _span("r2"), _span("c1", "r1"))
    _roll_up_cost(spans, {"r1": _cost(1.0), "r2": _cost(2.0), "c1": _cost(3.0)})

    assert spans["r1"].subtree_cost_usd == 4.0
    assert spans["r2"].subtree_cost_usd == 2.0


# ── Share of the run ──────────────────────────────────────────────────────────

def test_share_answers_the_question_the_ticket_asks():
    """"The verifier node is 60% of this run"."""
    spans = _tree(_span("root"), _span("verifier", "root"), _span("other", "root"))
    _roll_up_cost(spans, {"verifier": _cost(6.0), "other": _cost(4.0)})

    assert spans["verifier"].subtree_share == 0.6
    assert spans["other"].subtree_share == 0.4
    assert spans["root"].subtree_share == 1.0


def test_unattributed_spend_lowers_every_share_rather_than_hiding():
    """The denominator is everything the run cost. Shares then fall short of 1
    by exactly what carries no span, instead of quietly redistributing it."""
    spans = _tree(_span("root"))
    _roll_up_cost(spans, {"root": _cost(3.0), None: _cost(1.0)})

    assert spans["root"].subtree_cost_usd == 3.0
    assert spans["root"].subtree_share == 0.75


def test_cost_against_a_span_not_in_the_tree_stays_out_of_it():
    """An orphan span_id must not be attributed to some other node — but it
    still counts against the total, so the shortfall remains visible."""
    spans = _tree(_span("root"))
    _roll_up_cost(spans, {"root": _cost(1.0), "vanished": _cost(1.0)})

    assert spans["root"].subtree_cost_usd == 1.0
    assert spans["root"].subtree_share == 0.5


def test_a_free_run_does_not_divide_by_zero():
    spans = _tree(_span("root"))
    _roll_up_cost(spans, {})
    assert spans["root"].subtree_share == 0.0
    assert spans["root"].subtree_cost_usd == 0.0


# ── Malformed input ───────────────────────────────────────────────────────────

def test_a_parent_that_does_not_exist_is_treated_as_a_root():
    """Spans come from stored events; a truncated log can reference a parent
    whose start was never written."""
    spans = _tree(_span("orphan", "never-recorded"))
    _roll_up_cost(spans, {"orphan": _cost(1.0)})
    assert spans["orphan"].subtree_cost_usd == 1.0


def test_a_cycle_terminates_instead_of_hanging():
    """parent_span_id is read from event rows, so a cycle is possible input.
    Returning a wrong number is survivable; hanging the request is not."""
    a, b = _span("a", "b"), _span("b", "a")
    spans = _tree(a, b)
    _roll_up_cost(spans, {"a": _cost(1.0), "b": _cost(1.0)})
    assert spans["a"].subtree_cost_usd >= 1.0


def test_a_span_that_is_its_own_parent_does_not_double_itself():
    spans = _tree(_span("self", "self"))
    _roll_up_cost(spans, {"self": _cost(1.0)})
    assert spans["self"].subtree_cost_usd == 1.0


# ── Where the attribution comes from ──────────────────────────────────────────

async def test_record_usage_defaults_to_the_ambient_span(monkeypatch):
    """Read from the context variable rather than added to every call site: a
    call site added later would otherwise silently record unattributed spend."""
    from app.budget import tracker
    from app.core.span import current_span_id

    captured = {}

    class _Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        async def get(self, *_): return None
        def add(self, obj): captured["usage"] = obj
        async def commit(self): pass

    monkeypatch.setattr(tracker, "AsyncSessionLocal", lambda: _Session())

    token = current_span_id.set("01SPAN")
    try:
        await tracker.record_usage("run-1", "agent", "m", 10, 5)
    finally:
        current_span_id.reset(token)

    assert captured["usage"].span_id == "01SPAN"


async def test_record_usage_outside_a_span_records_no_attribution(monkeypatch):
    from app.budget import tracker

    captured = {}

    class _Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        async def get(self, *_): return None
        def add(self, obj): captured["usage"] = obj
        async def commit(self): pass

    monkeypatch.setattr(tracker, "AsyncSessionLocal", lambda: _Session())
    await tracker.record_usage("run-1", "agent", "m", 10, 5)

    assert captured["usage"].span_id is None


async def test_an_explicit_span_id_overrides_the_ambient_one(monkeypatch):
    from app.budget import tracker
    from app.core.span import current_span_id

    captured = {}

    class _Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        async def get(self, *_): return None
        def add(self, obj): captured["usage"] = obj
        async def commit(self): pass

    monkeypatch.setattr(tracker, "AsyncSessionLocal", lambda: _Session())

    token = current_span_id.set("01AMBIENT")
    try:
        await tracker.record_usage("run-1", "agent", "m", 10, 5, span_id="01EXPLICIT")
    finally:
        current_span_id.reset(token)

    assert captured["usage"].span_id == "01EXPLICIT"


def test_cost_is_not_attributed_to_individual_tool_calls():
    """Deliberate. A tool call spends no tokens itself; it costs by enlarging
    the context of the turns around it, so pinning cost to one would be an
    allocation dressed up as a measurement. The span is the finest honest unit."""
    from app.db.models.usage import TokenUsage

    assert not hasattr(TokenUsage, "tool_call_id")
    assert hasattr(TokenUsage, "span_id")
