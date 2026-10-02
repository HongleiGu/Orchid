"""NLI grounding sidecar + the backend's remote routing (OR-58 deployment).

Uses StubNLI so no model loads: tests the HTTP surface and that the backend
routes to the sidecar when EVIDENCE_NLI_URL is set.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core import dag
from app.core.types import AgentOutput
from app.evidence import service
from app.evidence.nli import StubNLI


@pytest.fixture
def client():
    service._verifier = StubNLI()
    service._decomposer = None
    service._loaded = True
    yield TestClient(service.app)
    service._verifier = None
    service._loaded = False


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_ground_endpoint_scores_claims(client):
    body = {
        "claims": ["The market grew 40 percent in 2026.",
                   "The company will acquire three rivals next quarter."],
        "sources": ["Reports show the market grew 40 percent in 2026."],
        "min_grounded": 0.8, "decompose": False,
    }
    r = client.post("/ground", json=body).json()
    assert r["ok"] is False                       # one claim ungrounded
    assert r["fraction"] == 0.5
    assert any("acquire three rivals" in u for u in r["ungrounded"])


def test_ground_endpoint_empty_is_pass(client):
    r = client.post("/ground", json={"claims": [], "sources": [], "decompose": False}).json()
    assert r["ok"] is True


async def test_backend_routes_to_sidecar_when_url_set(monkeypatch):
    monkeypatch.setenv("EVIDENCE_NLI_URL", "http://sidecar:8900")

    async def fake_remote(url, claims, sources, check):
        assert url == "http://sidecar:8900" and claims and sources
        return {"ok": False, "reason": "remote says 1/2", "fraction": 0.5, "ungrounded": ["x"]}

    monkeypatch.setattr(dag, "_ground_remote", fake_remote)
    out = AgentOutput(content="Claim one is here and is long enough. Claim two is also here and long.")
    up = {"retrieve": AgentOutput(content="Some evidence passage that is sufficiently long to chunk.")}
    res = await dag._run_grounding_check(out, up, {"sources": ["retrieve"]}, index=0)
    assert res["status"] == "fail" and res["fraction"] == 0.5


async def test_backend_skips_when_sidecar_unreachable(monkeypatch):
    monkeypatch.setenv("EVIDENCE_NLI_URL", "http://sidecar:8900")

    async def boom(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(dag, "_ground_remote", boom)
    out = AgentOutput(content="A claim that is sufficiently long to be split out here.")
    up = {"retrieve": AgentOutput(content="Evidence passage long enough to be chunked into one.")}
    res = await dag._run_grounding_check(out, up, {}, index=0)
    assert res["status"] == "pass" and "sidecar unavailable" in res["reason"]
