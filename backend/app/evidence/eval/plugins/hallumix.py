"""HalluMix plugin (Emery et al., 2025).

Source: HF dataset quotientai/HalluMix — 7.7k task-agnostic, multi-domain examples,
binary (faithful / hallucination), each a multi-document context + a claim.

Loads a local JSONL/JSON export in data_dir (export once with `datasets`:
`load_dataset('quotientai/HalluMix')['test'].to_json(path)`), or any *.jsonl there.
Tolerant to column names.
"""
from __future__ import annotations

import json
import pathlib
import random

from app.evidence.eval.plugins.base import EvalItem, register

_CTX = ("documents", "context", "docs", "passages", "sources", "evidence")
_CLAIM = ("claim", "answer", "response", "hypothesis", "statement", "output")
_LABEL = ("label", "is_hallucination", "hallucination", "faithful", "gold")


def _records(data_dir: str) -> list[dict]:
    d = pathlib.Path(data_dir)
    out: list[dict] = []
    for p in list(d.glob("*.jsonl")):
        out += [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    for p in list(d.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        out += data if isinstance(data, list) else [data]
    return out


def _pick(d, keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return k, d[k]
    return None, None


def _faithful(label_key: str, v) -> bool:
    # Normalise to True = faithful. Keys like is_hallucination invert the sense.
    s = str(v).strip().lower()
    truthy_hallucination = s in {"hallucination", "hallucinated", "unfaithful", "1", "true", "yes"}
    if "halluc" in label_key:                      # column means "is hallucination"
        return not truthy_hallucination
    return s in {"faithful", "supported", "consistent", "0" if "halluc" in label_key else "faithful",
                 "true", "yes", "1"} and s not in {"hallucination", "hallucinated", "unfaithful"}


@register
class HalluMixPlugin:
    name = "hallumix"

    def load(self, data_dir: str | None = None, limit: int | None = None, seed: int = 0) -> list[EvalItem]:
        if not data_dir:
            raise FileNotFoundError("hallumix needs --data-dir with a local export of quotientai/HalluMix")
        items: list[EvalItem] = []
        for i, r in enumerate(_records(data_dir)):
            _, ctx = _pick(r, _CTX)
            _, claim = _pick(r, _CLAIM)
            lk, label = _pick(r, _LABEL)
            if ctx is None or claim is None or label is None:
                continue
            items.append(EvalItem(
                id=str(r.get("id") or i),
                claim=str(claim).strip(),
                context=[str(c) for c in ctx] if isinstance(ctx, list) else [str(ctx)],
                gold=_faithful(lk, label),
                task=str(r.get("task") or r.get("domain") or ""),
                meta={"domain": r.get("domain")},
            ))
        rng = random.Random(seed)
        rng.shuffle(items)
        return items[:limit] if limit else items
