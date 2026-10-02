"""TofuEval plugin (Tang et al., NAACL 2024).

Source: github.com/amazon-science/tofueval — topic-focused dialogue summarization
with binary *sentence-level* factual-consistency annotations (+ explanations).
Each annotated summary sentence becomes an EvalItem: faithful iff labelled
factually consistent with the source document.

Expected: a JSONL in data_dir (we read every *.jsonl). Field names vary across
the repo's splits, so the loader is tolerant; confirm the mapping on first fetch.
"""
from __future__ import annotations

import json
import pathlib
import random

from app.evidence.eval.plugins.base import EvalItem, register

_CTX = ("document", "source", "source_doc", "transcript", "doc", "context")
_CLAIM = ("sentence", "summary_sentence", "summ_sent", "text", "claim")
_LABEL = ("label", "factual", "is_factual", "consistent", "factual_consistency")


def _pick(d: dict, keys, default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _is_faithful(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v == 1
    return str(v).strip().lower() in {"factual", "consistent", "yes", "faithful", "1", "true", "supported"}


@register
class TofuEvalPlugin:
    name = "tofueval"

    def load(self, data_dir: str | None = None, limit: int | None = None, seed: int = 0) -> list[EvalItem]:
        if not data_dir:
            raise FileNotFoundError("tofueval needs --data-dir with the amazon-science/tofueval JSONL files")
        items: list[EvalItem] = []
        for path in pathlib.Path(data_dir).glob("*.jsonl"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                r = json.loads(line)
                ctx, claim, label = _pick(r, _CTX), _pick(r, _CLAIM), _pick(r, _LABEL)
                if ctx is None or claim is None or label is None:
                    continue
                items.append(EvalItem(
                    id=str(r.get("id") or f"{path.stem}:{len(items)}"),
                    claim=str(claim).strip(),
                    context=[str(ctx)] if not isinstance(ctx, list) else [str(c) for c in ctx],
                    gold=_is_faithful(label),
                    task="summarization",
                    meta={"source": path.stem},
                ))
        rng = random.Random(seed)
        rng.shuffle(items)
        return items[:limit] if limit else items
