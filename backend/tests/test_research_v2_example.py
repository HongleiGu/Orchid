"""Structural check of the v2 research pipeline (parallel literature fan-in,
self-correcting loop, consensus nodes, LaTeX paper). Drives the real example
topology with scripted agents — no LLM calls."""
import json
from pathlib import Path

from app.core.agent import BaseAgent
from app.core.context import DAGContext
from app.core.dag import DAGDefinition, DAGEdge, DAGExecutor, DAGNode
from app.core.types import AgentOutput

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "autonomous-research-v2.json"


class ScriptedAgent(BaseAgent):
    def __init__(self, name, responder):
        super().__init__(name=name, model="test", system_prompt="")
        self._responder = responder
        self.calls = 0
        self.seen_upstream = []

    async def run(self, ctx: DAGContext) -> AgentOutput:
        self.calls += 1
        self.seen_upstream.append(set(ctx.upstream.keys()))
        return AgentOutput(content=self._responder(self.calls, ctx), agent_name=self.name)

    async def _act(self, ctx):  # pragma: no cover
        raise NotImplementedError


async def _noop_emit(_evt):
    return None


def _build(judge_responder):
    cfg = json.loads(EXAMPLE.read_text(encoding="utf-8"))["tasks"][0]["workflow_config"]
    responders = {"judge": judge_responder,
                  "finalize": lambda i, c: "gate: pass",
                  "write": lambda i, c: "saved paper.tex"}
    nodes = {}
    for nc in cfg["nodes"]:
        name = nc["name"]
        r = responders.get(name, (lambda n: (lambda i, c: f"{n} out"))(name))
        # drop contracts here — this checks topology, not the consensus engine
        nodes[name] = DAGNode(name=name, agent=ScriptedAgent(name, r))
    edges = [DAGEdge(source=e["source"], target=e["target"],
                     condition=e.get("if") or e.get("condition"),
                     max_iterations=e.get("max_iterations"), loop=bool(e.get("loop", False)))
             for e in cfg["edges"]]
    return DAGDefinition(nodes=nodes, edges=edges, entry=cfg.get("entry", cfg["nodes"][0]["name"]))


async def _run(dag):
    return await DAGExecutor().execute(dag=dag, task_id="t", run_id="r",
                                       task_description="", inputs={}, emit=_noop_emit)


def _c(dag, n):
    return dag.nodes[n].agent.calls


async def test_v2_parallel_literature_fans_in_then_writes_paper():
    dag = _build(lambda i, c: "decision: proceed")
    out = await _run(dag)

    assert "gate: pass" in out.content
    # both literature lanes ran (in parallel), merge ran once after both fanned in
    assert _c(dag, "lit_arxiv") == 1
    assert _c(dag, "lit_broad") == 1
    assert _c(dag, "lit_merge") == 1
    assert dag.nodes["lit_merge"].agent.seen_upstream[0] >= {"lit_arxiv", "lit_broad"}
    # straight-through: no refine, paper + finalize once
    assert _c(dag, "rethink") == 0
    assert _c(dag, "write") == 1
    assert _c(dag, "finalize") == 1


async def test_v2_self_correcting_loop_bounded_then_paper():
    def judge(i, _c):
        return "decision: refine" if i < 3 else "decision: proceed"

    dag = _build(judge)
    out = await _run(dag)

    assert "gate: pass" in out.content
    # loop re-ran the experiment; literature stayed put (it's before the loop entry)
    assert _c(dag, "design") == 3
    assert _c(dag, "execute") == 3
    assert _c(dag, "rethink") == 2
    assert _c(dag, "lit_arxiv") == 1
    assert _c(dag, "lit_merge") == 1
    assert _c(dag, "write") == 1
    assert _c(dag, "finalize") == 1
