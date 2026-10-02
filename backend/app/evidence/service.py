"""NLI grounding sidecar (OR-58 deployment).

The backend API image has no torch; this service does. It loads the NLI model
(and, when an LLM key is present, the claim decomposer) once and exposes the
grounding computation over HTTP, so the torch-less backend's `grounded` contract
check can reach it via $EVIDENCE_NLI_URL.

    uvicorn app.evidence.service:app --host 0.0.0.0 --port 8900

Config (env):
  EVIDENCE_NLI_KIND    transformers | minicheck   (default: transformers)
  EVIDENCE_NLI_MODEL   HF id or local path         (default: the kind's default)
  EVIDENCE_DECOMPOSE   1|0 enable decomposition    (default: 1 if an LLM key exists)
  EVIDENCE_DECOMPOSE_MODEL / LLM_DEFAULT_MODEL      decomposer model
"""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.evidence.grounding import ground_claims

logger = logging.getLogger(__name__)
app = FastAPI(title="Orchid evidence NLI sidecar")

_LLM_KEY_ENVS = ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                 "DEEPSEEK_API_KEY", "GROQ_API_KEY")
_verifier = None
_decomposer = None
_loaded = False


def _load() -> None:
    global _verifier, _decomposer, _loaded
    if _loaded:
        return
    kind = os.environ.get("EVIDENCE_NLI_KIND", "transformers").lower()
    model = os.environ.get("EVIDENCE_NLI_MODEL")
    if kind == "minicheck":
        from app.evidence.nli import MINICHECK_MODEL, MiniCheckNLI
        _verifier = MiniCheckNLI(model_name=model or MINICHECK_MODEL)
    else:
        from app.evidence.nli import DEFAULT_MODEL, TransformersNLI
        _verifier = TransformersNLI(model_name=model or DEFAULT_MODEL)

    want_decomp = os.environ.get("EVIDENCE_DECOMPOSE", "1") != "0"
    if want_decomp and any(os.environ.get(k) for k in _LLM_KEY_ENVS):
        from app.evidence.decompose import LLMDecomposer
        dmodel = os.environ.get("EVIDENCE_DECOMPOSE_MODEL") or os.environ.get("LLM_DEFAULT_MODEL") \
            or "openrouter/openai/gpt-4o-mini"
        _decomposer = LLMDecomposer(model=dmodel)
    _loaded = True
    logger.info("evidence sidecar loaded: kind=%s decompose=%s", kind, _decomposer is not None)


class GroundRequest(BaseModel):
    claims: list[str]
    sources: list[str]
    min_grounded: float = 0.8
    support_fraction: float = 0.5
    decompose: bool = True


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "nli_kind": os.environ.get("EVIDENCE_NLI_KIND", "transformers"),
        "loaded": _loaded,
    }


@app.post("/ground")
def ground(req: GroundRequest) -> dict:
    # Sync endpoint: FastAPI runs it in a threadpool, so the (blocking) NLI work
    # does not stall the event loop.
    _load()
    decomposer = _decomposer if req.decompose else None
    if not req.claims or not req.sources:
        return {"ok": True, "reason": "no claims or sources", "fraction": 1.0, "ungrounded": []}
    return ground_claims(_verifier, req.claims, req.sources, req.min_grounded,
                         decomposer, req.support_fraction)
