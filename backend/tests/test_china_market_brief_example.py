"""Structural check of the China market daily brief pipeline (three parallel
gathering lanes fanning into verification, then a bounded risk-review loop).
Drives the real example topology with scripted agents — no LLM calls, no
network."""
import json
from pathlib import Path

from app.core.agent import BaseAgent
from app.core.context import DAGContext
from app.core.dag import DAGDefinition, DAGEdge, DAGExecutor, DAGNode
from app.core.types import AgentOutput

EXAMPLE = (
    Path(__file__).resolve().parents[2] / "examples" / "china-market-daily-brief.json"
)


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


def _config():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))["tasks"][0]["workflow_config"]


def _build(risk_responder):
    cfg = _config()
    responders = {
        "risk": risk_responder,
        "verify": lambda i, c: "gate: pass\n统一事实底稿",
        "publish": lambda i, c: "gate: pass\n不构成投资建议",
    }
    nodes = {}
    for nc in cfg["nodes"]:
        name = nc["name"]
        responder = responders.get(name, (lambda n: (lambda i, c: f"{n} out"))(name))
        # drop contracts here — this checks topology, not the contract engine
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
    return DAGDefinition(
        nodes=nodes, edges=edges, entry=cfg.get("entry", cfg["nodes"][0]["name"])
    )


async def _run(dag):
    return await DAGExecutor().execute(
        dag=dag, task_id="t", run_id="r", task_description="", inputs={}, emit=_noop_emit
    )


def _c(dag, name):
    return dag.nodes[name].agent.calls


async def test_three_lanes_fan_in_then_publish():
    dag = _build(lambda i, c: "verdict: APPROVE")
    out = await _run(dag)

    assert "gate: pass" in out.content
    # all three gathering lanes ran once and fanned into the verifier
    for lane in ("macro", "cn_market", "global"):
        assert _c(dag, lane) == 1
    assert _c(dag, "verify") == 1
    assert dag.nodes["verify"].agent.seen_upstream[0] >= {"macro", "cn_market", "global"}
    # approved straight through: no revision, one compliance pass, one publish
    assert _c(dag, "revise") == 0
    assert _c(dag, "picks") == 1
    assert _c(dag, "compliance") == 1
    assert _c(dag, "publish") == 1


async def test_risk_review_loop_is_bounded_then_publishes():
    def risk(i, _c):
        return "verdict: REVISE" if i < 3 else "verdict: APPROVE"

    dag = _build(risk)
    out = await _run(dag)

    assert "gate: pass" in out.content
    # the critic bounced the list twice; the picker regenerated each time
    assert _c(dag, "picks") == 3
    assert _c(dag, "risk") == 3
    assert _c(dag, "revise") == 2
    # gathering sits before the loop entry, so it never re-ran
    for lane in ("plan", "macro", "cn_market", "global", "verify", "strategy"):
        assert _c(dag, lane) == 1
    assert _c(dag, "compliance") == 1
    assert _c(dag, "publish") == 1


async def test_recommendation_nodes_are_contract_gated():
    """The picks/risk/publish nodes carry the guarantees the brief rests on:
    numbers verified against the quote API, a machine-checkable decision line,
    and a published report that says it is not investment advice."""
    nodes = {n["name"]: n for n in _config()["nodes"]}

    picks_checks = nodes["picks"]["contract"]["checks"]
    assert {"type": "tool_called", "skill": "market_data"} in picks_checks
    json_check = next(c for c in picks_checks if c["type"] == "json_parse")
    assert "verified_symbols" in json_check["required_keys"]
    assert "unverified_dropped" in json_check["required_keys"]

    assert nodes["risk"]["contract"]["consensus"]["n"] == 3
    assert nodes["risk"]["contract"]["consensus"]["agree_on"] == ["verdict"]

    publish_checks = nodes["publish"]["contract"]["checks"]
    assert {"type": "contains", "value": "不构成"} in publish_checks
    assert {"type": "tool_called", "skill": "vault_write"} in publish_checks
