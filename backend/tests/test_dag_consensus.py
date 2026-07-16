"""Tests for the consensus node engine (OR-4).

Covers majority-reached, no-majority, per-trajectory timeout exclusion, the new
per-trajectory error resilience (one raising trajectory must not sink the vote),
the all-failed edge case, and the end-to-end no-majority retry/exhaustion policy
driven through the full executor.
"""
import asyncio

from app.core.agent import BaseAgent
from app.core.context import DAGContext
from app.core.dag import DAGDefinition, DAGExecutor, DAGNode, _majority_vote
from app.core.types import AgentOutput


class TrajectoryAgent(BaseAgent):
    """Agent whose per-call behaviour is scripted, to simulate diverging,
    slow, or crashing consensus trajectories. `behaviors` entries are
    ("ok", content) | ("sleep", seconds) | ("raise", message), indexed by
    call order (cycled)."""

    def __init__(self, name, behaviors):
        super().__init__(name=name, model="test", system_prompt="")
        self._behaviors = behaviors
        self.calls = 0

    async def run(self, ctx: DAGContext) -> AgentOutput:
        idx = self.calls
        self.calls += 1
        kind, val = self._behaviors[idx % len(self._behaviors)]
        if kind == "sleep":
            await asyncio.sleep(val)
            return AgentOutput(content="late", agent_name=self.name)
        if kind == "raise":
            raise RuntimeError(val)
        return AgentOutput(content=val, agent_name=self.name)

    async def _act(self, ctx):  # pragma: no cover
        raise NotImplementedError


async def _noop_emit(_evt):
    return None


async def _consensus(behaviors, *, n=3, min_agree=2, timeout=5.0):
    node = DAGNode(name="judge", agent=TrajectoryAgent("judge", behaviors))
    out = await DAGExecutor()._run_consensus(
        node=node,
        consensus={"n": n, "agree_on": ["decision"], "min_agree": min_agree,
                   "timeout_per_trajectory_s": timeout},
        task_id="t", run_id="r", task_description="", inputs={}, upstream={},
        predecessor_names=[], emit=_noop_emit, parent_span_id="",
    )
    return out, out.metadata["consensus_tally"]


# ── _majority_vote unit tests ────────────────────────────────────────────────

def _out(content, **md):
    return AgentOutput(content=content, agent_name="judge", metadata=md)


def test_majority_vote_counts_plurality():
    outs = [_out("decision: proceed"), _out("decision: proceed"), _out("decision: refine")]
    winner, tally = _majority_vote(outs, ["decision"], 2)
    assert tally["majority_reached"] is True
    assert tally["winner_count"] == 2
    assert "proceed" in winner.content


def test_majority_vote_excludes_failed_trajectories():
    outs = [
        _out("decision: proceed"),
        _out("decision: proceed"),
        _out("[timed out]", traj_timeout=True),
        _out("[errored]", traj_error=True),
    ]
    _winner, tally = _majority_vote(outs, ["decision"], 2)
    assert tally["valid_trajectories"] == 2
    assert tally["total_trajectories"] == 4
    assert tally["majority_reached"] is True


def test_majority_vote_all_failed():
    outs = [_out("x", traj_error=True), _out("y", traj_timeout=True)]
    _winner, tally = _majority_vote(outs, ["decision"], 2)
    assert tally["majority_reached"] is False
    assert tally["error"] == "all_trajectories_failed"


# ── _run_consensus integration tests ─────────────────────────────────────────

async def test_consensus_reaches_majority():
    out, tally = await _consensus([("ok", "decision: proceed")])
    assert tally["majority_reached"] is True
    assert "proceed" in out.content


async def test_consensus_no_majority_when_all_differ():
    out, tally = await _consensus(
        [("ok", "decision: proceed"), ("ok", "decision: refine"), ("ok", "decision: pivot")]
    )
    assert tally["majority_reached"] is False
    assert tally["valid_trajectories"] == 3


async def test_consensus_excludes_timed_out_trajectory():
    _out, tally = await _consensus(
        [("ok", "decision: proceed"), ("ok", "decision: proceed"), ("sleep", 0.3)],
        timeout=0.05,
    )
    assert tally["valid_trajectories"] == 2
    assert tally["total_trajectories"] == 3
    assert tally["majority_reached"] is True


async def test_consensus_survives_trajectory_exception():
    # The raising trajectory must be excluded, not crash the whole node.
    _out, tally = await _consensus(
        [("ok", "decision: proceed"), ("ok", "decision: proceed"), ("raise", "boom")]
    )
    assert tally["valid_trajectories"] == 2
    assert tally["majority_reached"] is True


# ── end-to-end policy through execute() ──────────────────────────────────────

async def _run_single_node(behaviors, contract):
    node = DAGNode(name="judge", agent=TrajectoryAgent("judge", behaviors), contract=contract)
    dag = DAGDefinition(nodes={"judge": node}, edges=[], entry="judge")
    out = await DAGExecutor().execute(
        dag=dag, task_id="t", run_id="r", task_description="", inputs={}, emit=_noop_emit,
    )
    return node, out


async def test_consensus_node_passes_on_majority():
    contract = {"consensus": {"n": 3, "agree_on": ["decision"], "min_agree": 2,
                              "timeout_per_trajectory_s": 5}}
    _node, out = await _run_single_node([("ok", "decision: proceed")], contract)
    assert out.metadata.get("contract_halt") is not True
    assert out.metadata["contract"]["status"] == "pass"
    assert "proceed" in out.content


async def test_consensus_no_majority_retries_then_halts():
    contract = {
        "consensus": {"n": 3, "agree_on": ["decision"], "min_agree": 2,
                      "timeout_per_trajectory_s": 5},
        "max_retries": 1,
        "on_exhausted": "stop",
    }
    node, out = await _run_single_node(
        [("ok", "decision: proceed"), ("ok", "decision: refine"), ("ok", "decision: pivot")],
        contract,
    )
    assert out.metadata.get("contract_halt") is True
    assert out.metadata["contract"]["policy"] == "stop"
    assert out.metadata["contract"].get("retries_exhausted") is True
    # 3 trajectories × (initial attempt + 1 retry) = 6 agent runs.
    assert node.agent.calls == 6
