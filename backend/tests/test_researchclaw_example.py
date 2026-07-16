"""Structural end-to-end check of the shipped researchclaw example DAG (OR-7).

Loads examples/autonomous-researchclaw-dag.json, rebuilds it with scripted
agents (no LLM calls), and drives the judge through REFINE -> REFINE -> PROCEED
to prove the loop re-runs the experiment and the run terminates at the paper
finalizer. Also checks the loop is bounded when the judge never proceeds.
"""
import json
from pathlib import Path

from app.core.agent import BaseAgent
from app.core.context import DAGContext
from app.core.dag import DAGDefinition, DAGEdge, DAGExecutor, DAGNode
from app.core.types import AgentOutput

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "autonomous-researchclaw-dag.json"


class ScriptedAgent(BaseAgent):
    def __init__(self, name, responder):
        super().__init__(name=name, model="test", system_prompt="")
        self._responder = responder
        self.calls = 0

    async def run(self, ctx: DAGContext) -> AgentOutput:
        self.calls += 1
        return AgentOutput(content=self._responder(self.calls, ctx), agent_name=self.name)

    async def _act(self, ctx):  # pragma: no cover
        raise NotImplementedError


async def _noop_emit(_evt):
    return None


def _build(judge_responder):
    cfg = json.loads(EXAMPLE.read_text(encoding="utf-8"))["tasks"][0]["workflow_config"]

    responders = {
        "judge": judge_responder,
        "write": lambda i, c: "# Paper\nfinal draft",
        "finalize": lambda i, c: "# Research Run Summary\ngate: pass",
    }
    nodes = {}
    for nc in cfg["nodes"]:
        name = nc["name"]
        responder = responders.get(name, (lambda n: (lambda i, c: f"{n} output"))(name))
        nodes[name] = DAGNode(name=name, agent=ScriptedAgent(name, responder))

    edges = [
        DAGEdge(
            source=e["source"],
            target=e["target"],
            condition=e.get("if") or e.get("condition"),
            max_iterations=e.get("max_iterations"),
            loop=bool(e.get("loop", False)),
        )
        for e in cfg["edges"]
    ]
    dag = DAGDefinition(nodes=nodes, edges=edges, entry=cfg.get("entry", cfg["nodes"][0]["name"]))
    return dag


async def _run(dag):
    return await DAGExecutor().execute(
        dag=dag, task_id="t", run_id="r", task_description="", inputs={}, emit=_noop_emit,
    )


def _verbose_judge_output(decision: str) -> str:
    # Mirrors the real judge: a one-line verdict followed by a long analysis
    # that discusses ALL three options (proceed/refine/pivot). Branch conditions
    # must key off line 1 only, or every branch matches at once.
    return (
        f"decision: {decision}\n\n"
        "# Phase F: Analysis and Decision\n"
        "## Stage 15 RESEARCH_DECISION\n"
        "Considered decision: refine and decision: pivot as alternatives, "
        "but the evidence supports proceeding.\n"
    )


async def test_example_loops_twice_then_writes_paper():
    def judge(i, _c):
        return _verbose_judge_output("refine" if i < 3 else "proceed")

    dag = _build(judge)
    out = await _run(dag)

    # PROCEED path terminates at the finalizer.
    assert "gate: pass" in out.content
    # Experiment re-ran: design/execute/judge each ran 3x (initial + 2 refines).
    assert dag.nodes["design"].agent.calls == 3
    assert dag.nodes["execute"].agent.calls == 3
    assert dag.nodes["judge"].agent.calls == 3
    # rethink ran once per refine (2x); the paper/finalize ran once.
    assert dag.nodes["rethink"].agent.calls == 2
    assert dag.nodes["write"].agent.calls == 1
    assert dag.nodes["finalize"].agent.calls == 1
    # Scoping/literature ran exactly once — they are before the loop entry.
    assert dag.nodes["scope"].agent.calls == 1
    assert dag.nodes["literature"].agent.calls == 1


async def test_example_loop_is_bounded_when_never_proceeding():
    dag = _build(lambda i, _c: "decision: refine")  # never proceeds
    out = await _run(dag)

    # initial attempt + exactly 2 bounded retries, then the loop is exhausted.
    assert dag.nodes["design"].agent.calls == 3
    assert dag.nodes["rethink"].agent.calls == 3
    # The paper path is never taken.
    assert dag.nodes["write"].agent.calls == 0
    assert dag.nodes["finalize"].agent.calls == 0
    # Terminal artifact is the last rethink plan.
    assert "REFINE/PIVOT Plan" in out.content or out.agent_name == "rethink"
