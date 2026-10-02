"""VeriGray plugin — "The Gray Zone of Faithfulness" (arXiv:2510.21118, 2025).

Source: HF dataset `Ding-Qiang/veri-gray`
(FaithBench_sentence_level_reannotated_*.jsonl). Each line is a record
{question(=source document), answer(=summary), sentences:[{text, annotation,...}]}.
Every annotated summary sentence becomes an EvalItem, labelled by its category:

  explicitly-supported / implicitly-supported  -> faithful (grounded in source)
  fabricated / contradicting / out-dependent    -> NOT grounded in the source
      (out-dependent = true but needs external knowledge; unsupported by source)
  ambiguous                                      -> gold_abstain (the gray zone)
  no-fact                                        -> skipped (no factual content)

Download: curl the jsonl from
huggingface.co/datasets/Ding-Qiang/veri-gray and point --data-dir at it.
"""
from __future__ import annotations

import json
import pathlib
import random

from app.evidence.eval.plugins.base import EvalItem, register

_FAITHFUL = {"explicitly-supported", "implicitly-supported"}
_UNFAITHFUL = {"fabricated", "contradicting", "out-dependent", "outdependent"}
_AMBIGUOUS = {"ambiguous"}
_SKIP = {"no-fact", "nofact"}


@register
class VeriGrayPlugin:
    name = "verigray"

    def load(self, data_dir: str | None = None, limit: int | None = None, seed: int = 0) -> list[EvalItem]:
        if not data_dir:
            raise FileNotFoundError("verigray needs --data-dir with the Ding-Qiang/veri-gray jsonl")
        items: list[EvalItem] = []
        for path in pathlib.Path(data_dir).glob("*.jsonl"):
            for li, line in enumerate(path.read_text(encoding="utf-8").split("\n")):
                if not line.strip():
                    continue
                rec = json.loads(line)
                ctx = rec.get("question") or rec.get("source") or rec.get("document")
                if not ctx:
                    continue
                for si, s in enumerate(rec.get("sentences") or []):
                    text = (s.get("text") or "").strip()
                    cat = str(s.get("annotation") or s.get("category") or "").strip().lower()
                    if not text or not cat or cat in _SKIP:
                        continue
                    items.append(EvalItem(
                        id=f"{path.stem}:{li}:{si}",
                        claim=text,
                        context=[str(ctx)],
                        gold=cat in _FAITHFUL,
                        task="summarization",
                        gold_abstain=cat in _AMBIGUOUS,
                        meta={"category": cat, "generator": rec.get("generator")},
                    ))
        rng = random.Random(seed)
        rng.shuffle(items)
        return items[:limit] if limit else items
