"""Tests for cyclic-edge loop support in the DAG executor (OR-2).

Covers: linear DAGs still run once (regression), a loop re-runs its body until
its exit condition holds, per-edge max_iterations caps iterations, the loop node
sees the feedback that triggered it, and the global node-execution ceiling stops
a runaway loop.
"""
import app.core.dag as dag_module
from app.core.agent import BaseAgent
from app.core.context import DAGContext
from app.core.dag import DAGDefinition, DAGEdge, DAGExecutor, DAGNode
from app.core.types import AgentOutput


class ScriptedAgent(BaseAgent):
    """Agent whose output is produced by a responder(call_index, ctx) callable."""

    def __init__(self, name, responder):
        super().__init__(name=name, model="test", system_prompt="")
        self._responder = responder
        self.calls = 0
        self.seen_upstream: list[set[str]] = []

    async def run(self, ctx: DAGContext) -> AgentOutput:
        self.calls += 1
        self.seen_upstream.append(set(ctx.upstream.keys()))
        return AgentOutput(content=self._responder(self.calls, ctx), agent_name=self.name)

    async def _act(self, ctx):  # pragma: no cover - not used in DAG mode
        raise NotImplementedError


async def _noop_emit(_evt):
    return None


def _node(name, responder):
    return DAGNode(name=name, agent=ScriptedAgent(name, responder))


async def _run(nodes, edges, entry, inputs=None):
    dag = DAGDefinition(nodes={n.name: n for n in nodes}, edges=edges, entry=entry)
    out = await DAGExecutor().execute(
        dag=dag, task_id="t", run_id="r",
        task_description="", inputs=inputs or {}, emit=_noop_emit,
    )
    return dag, out


def _calls(dag, name):
    return dag.nodes[name].agent.calls


async def test_linear_dag_runs_each_node_once():
    nodes = [_node("a", lambda i, c: "A"), _node("b", lambda i, c: "B"), _node("c", lambda i, c: "C")]
    dag, out = await _run(nodes, [DAGEdge("a", "b"), DAGEdge("b", "c")], "a")
    assert out.content == "C"
    assert (_calls(dag, "a"), _calls(dag, "b"), _calls(dag, "c")) == (1, 1, 1)


async def test_loop_reruns_body_until_condition_exits():
    def judge(i, c):
        return "decision: refine" if i < 3 else "decision: proceed"

    nodes = [
        _node("design", lambda i, c: "designed"),
        _node("execute", lambda i, c: "ran"),
        _node("judge", judge),
        _node("done", lambda i, c: "DONE"),
    ]
    edges = [
        DAGEdge("design", "execute"),
        DAGEdge("execute", "judge"),
        DAGEdge("judge", "done", condition="'proceed' in output.content.lower()"),
        DAGEdge("judge", "design", condition="'refine' in output.content.lower()", max_iterations=5),
    ]
    dag, out = await _run(nodes, edges, "design")

    assert out.content == "DONE"
    assert _calls(dag, "design") == 3   # initial + 2 refine loops
    assert _calls(dag, "execute") == 3
    assert _calls(dag, "judge") == 3
    assert _calls(dag, "done") == 1
    # On its first run design had no upstream; on re-entry it sees the judge feedback.
    assert "judge" not in dag.nodes["design"].agent.seen_upstream[0]
    assert "judge" in dag.nodes["design"].agent.seen_upstream[1]


async def test_loop_respects_max_iterations():
    nodes = [
        _node("design", lambda i, c: "d"),
        _node("judge", lambda i, c: "decision: refine"),  # never proceeds
    ]
    edges = [
        DAGEdge("design", "judge"),
        DAGEdge("judge", "design", condition="'refine' in output.content.lower()", max_iterations=2),
    ]
    dag, out = await _run(nodes, edges, "design")

    assert _calls(dag, "design") == 3   # initial + exactly 2 loops
    assert _calls(dag, "judge") == 3
    assert "refine" in out.content.lower()   # ends on the last judge output


async def test_loop_field_without_count_defaults_to_one_iteration():
    nodes = [
        _node("a", lambda i, c: "a"),
        _node("b", lambda i, c: "loop back please"),
    ]
    edges = [DAGEdge("a", "b"), DAGEdge("b", "a", loop=True)]
    dag, _ = await _run(nodes, edges, "a")

    assert _calls(dag, "a") == 2   # initial + 1 default loop
    assert _calls(dag, "b") == 2


async def test_conditional_branches_merge_into_one_terminal():
    # judge → write (proceed) OR rethink (refine); both → finalize (single join).
    nodes = [
        _node("judge", lambda i, c: "decision: proceed"),
        _node("write", lambda i, c: "wrote"),
        _node("rethink", lambda i, c: "rethought"),
        _node("finalize", lambda i, c: "FINAL"),
    ]
    edges = [
        DAGEdge("judge", "write", condition="'proceed' in output.content.lower()"),
        DAGEdge("judge", "rethink", condition="'refine' in output.content.lower()"),
        DAGEdge("write", "finalize"),
        DAGEdge("rethink", "finalize"),
    ]
    dag, out = await _run(nodes, edges, "judge")

    assert out.content == "FINAL"
    assert _calls(dag, "write") == 1
    assert _calls(dag, "rethink") == 0   # untaken branch skipped
    assert _calls(dag, "finalize") == 1  # join runs exactly once, no hang


async def test_join_with_mixed_conditional_and_unconditional_inedges():
    # C has one unconditional in-edge (A) and one conditional-false in-edge (B).
    # The old engine hung here; C must still run once off the live path.
    nodes = [
        _node("a", lambda i, c: "A"),
        _node("b", lambda i, c: "B"),
        _node("c", lambda i, c: "C"),
    ]
    edges = [
        DAGEdge("a", "c"),
        DAGEdge("b", "c", condition="'never' in output.content.lower()"),
    ]
    dag, out = await _run(nodes, edges, "a")

    assert out.content == "C"
    assert _calls(dag, "c") == 1


async def test_fully_dead_branch_is_pruned_end_to_end():
    # a → b only via a false condition; b → c. Both b and c must be skipped.
    nodes = [
        _node("a", lambda i, c: "A"),
        _node("b", lambda i, c: "B"),
        _node("c", lambda i, c: "C"),
    ]
    edges = [
        DAGEdge("a", "b", condition="'yes' in output.content.lower()"),
        DAGEdge("b", "c"),
    ]
    dag, out = await _run(nodes, edges, "a")

    assert out.content == "A"          # only a ran
    assert _calls(dag, "b") == 0
    assert _calls(dag, "c") == 0


async def test_loop_with_conditional_exit_into_shared_terminal():
    # The OR-7 shape in miniature: design→execute→judge; judge loops back to
    # design on refine and exits to done on proceed; done→finalize (single join).
    def judge(i, c):
        return "decision: refine" if i < 3 else "decision: proceed"

    nodes = [
        _node("design", lambda i, c: "designed"),
        _node("execute", lambda i, c: "ran"),
        _node("judge", judge),
        _node("done", lambda i, c: "done"),
        _node("finalize", lambda i, c: "FINAL"),
    ]
    edges = [
        DAGEdge("design", "execute"),
        DAGEdge("execute", "judge"),
        DAGEdge("judge", "done", condition="'proceed' in output.content.lower()"),
        DAGEdge("judge", "design", condition="'refine' in output.content.lower()", max_iterations=5),
        DAGEdge("done", "finalize"),
    ]
    dag, out = await _run(nodes, edges, "design")

    assert out.content == "FINAL"
    assert _calls(dag, "design") == 3    # initial + 2 refine loops
    assert _calls(dag, "done") == 1      # exit branch runs once, after the loop
    assert _calls(dag, "finalize") == 1  # shared terminal, not duplicated


async def test_global_ceiling_halts_runaway_loop(monkeypatch):
    class _Stub:
        dag_max_total_node_executions = 6

    monkeypatch.setattr(dag_module, "get_settings", lambda: _Stub())

    nodes = [
        _node("design", lambda i, c: "d"),
        _node("judge", lambda i, c: "decision: refine"),
    ]
    edges = [
        DAGEdge("design", "judge"),
        DAGEdge("judge", "design", condition="'refine' in output.content.lower()", max_iterations=999),
    ]
    _dag, out = await _run(nodes, edges, "design")

    assert out.metadata.get("dag_halt") == "node_execution_ceiling"
    assert out.metadata.get("contract_halt") is True
