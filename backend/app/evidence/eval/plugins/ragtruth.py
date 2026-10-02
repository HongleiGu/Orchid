"""RAGTruth plugin (Niu et al., ACL 2024).

Source: github.com/ParticleMedia/RAGTruth (dataset/ has source_info.jsonl +
response.jsonl) or the processed HF mirror wandb/RAGTruth-processed. Each response
has span-level hallucination annotations; we map to a response-level label:
faithful iff no hallucination spans are annotated.

Expected files in data_dir: `source_info.jsonl` and `response.jsonl` (the raw
ParticleMedia layout). Download: clone the repo and point --data-dir at dataset/.
"""
from __future__ import annotations

import json
import pathlib
import random

from app.evidence.eval.plugins.base import EvalItem, register


def _read_jsonl(path: pathlib.Path) -> list[dict]:
    # split on \n only (text may contain U+2028/U+2029 that splitlines() breaks on)
    return [json.loads(l) for l in path.read_text(encoding="utf-8").split("\n") if l.strip()]


def _context_of(src: dict) -> list[str]:
    si = src.get("source_info")
    if isinstance(si, str):
        return [si]
    if isinstance(si, dict):
        # data2text / qa variants store the context under varying keys
        parts = [str(v) for v in si.values() if isinstance(v, (str, int, float)) and str(v).strip()]
        return parts or [json.dumps(si, ensure_ascii=False)]
    if isinstance(si, list):
        return [str(x) for x in si]
    return [str(src.get("prompt", ""))]


@register
class RAGTruthPlugin:
    name = "ragtruth"

    def load(self, data_dir: str | None = None, limit: int | None = None, seed: int = 0) -> list[EvalItem]:
        if not data_dir:
            raise FileNotFoundError("ragtruth needs --data-dir pointing at RAGTruth dataset/ "
                                    "(source_info.jsonl + response.jsonl from ParticleMedia/RAGTruth)")
        d = pathlib.Path(data_dir)
        sources = {s["source_id"]: s for s in _read_jsonl(d / "source_info.jsonl")}
        items: list[EvalItem] = []
        for r in _read_jsonl(d / "response.jsonl"):
            src = sources.get(r.get("source_id"))
            if not src:
                continue
            labels = r.get("labels") or []
            items.append(EvalItem(
                id=str(r.get("id") or f"{r.get('source_id')}:{r.get('model')}"),
                claim=str(r.get("response", "")).strip(),
                context=_context_of(src),
                gold=len(labels) == 0,                       # no hallucination spans = faithful
                task=str(src.get("task_type", "")),
                meta={"model": r.get("model"), "n_spans": len(labels)},
            ))
        rng = random.Random(seed)
        rng.shuffle(items)
        return items[:limit] if limit else items
