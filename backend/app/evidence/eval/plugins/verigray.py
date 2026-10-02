"""VeriGray plugin — "Verification with the Gray zone" (summarization unfaithfulness).

Span/sentence-level annotations with categories: explicit, implicit (supported);
contradicting, fabricated, out-dependent (unfaithful); and **ambiguous** (the gray
zone). The ambiguous class maps to `gold_abstain=True` — the one benchmark that
directly tests our abstain/UNCERTAIN behaviour rather than forcing a binary.

Source is the newest of the four and least pinned; confirm the exact file layout
on first fetch. Loader is tolerant and expects *.jsonl in data_dir with a
category/label per sentence.
"""
from __future__ import annotations

import json
import pathlib
import random

from app.evidence.eval.plugins.base import EvalItem, register

_CTX = ("document", "source", "article", "doc", "context", "transcript")
_CLAIM = ("sentence", "summary_sentence", "text", "claim", "span")
_CAT = ("category", "label", "annotation", "type")

_FAITHFUL = {"explicit", "implicit", "supported", "faithful", "entailed"}
_UNFAITHFUL = {"contradicting", "contradict", "fabricated", "out-dependent", "outdependent",
               "unfaithful", "unsupported", "hallucinated"}
_AMBIGUOUS = {"ambiguous", "gray", "grey", "uncertain"}


def _pick(d, keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


@register
class VeriGrayPlugin:
    name = "verigray"

    def load(self, data_dir: str | None = None, limit: int | None = None, seed: int = 0) -> list[EvalItem]:
        if not data_dir:
            raise FileNotFoundError("verigray needs --data-dir with the VeriGray JSONL (confirm source on fetch)")
        items: list[EvalItem] = []
        for path in pathlib.Path(data_dir).glob("*.jsonl"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                r = json.loads(line)
                ctx, claim, cat = _pick(r, _CTX), _pick(r, _CLAIM), _pick(r, _CAT)
                if ctx is None or claim is None or cat is None:
                    continue
                c = str(cat).strip().lower()
                ambiguous = c in _AMBIGUOUS
                items.append(EvalItem(
                    id=str(r.get("id") or f"{path.stem}:{len(items)}"),
                    claim=str(claim).strip(),
                    context=[str(ctx)] if not isinstance(ctx, list) else [str(x) for x in ctx],
                    gold=c in _FAITHFUL,                 # faithful categories
                    task="summarization",
                    gold_abstain=ambiguous,
                    meta={"category": c},
                ))
        rng = random.Random(seed)
        rng.shuffle(items)
        return items[:limit] if limit else items
