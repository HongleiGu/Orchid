"""TofuEval plugin (Tang et al., NAACL 2024).

Source: github.com/amazon-science/tofueval — `factual_consistency/*_factual_eval_*.csv`
with columns (doc_id, summ_sent, sent_label[yes/no], type, ...). Each summary
sentence is an EvalItem, faithful iff sent_label == "yes".

The repo ships only `doc_id`s, NOT the source documents (licensing): they are
obtained from MediaSum + MeetingBank by id (see the repo README). So this loader
requires a `docs.json` in data_dir mapping doc_id -> source text; without it the
context cannot be grounded and the loader raises with instructions.
"""
from __future__ import annotations

import csv
import json
import pathlib
import random

from app.evidence.eval.plugins.base import EvalItem, register

_FAITHFUL = {"yes", "factual", "consistent", "1", "true", "faithful"}


@register
class TofuEvalPlugin:
    name = "tofueval"

    def load(self, data_dir: str | None = None, limit: int | None = None, seed: int = 0) -> list[EvalItem]:
        if not data_dir:
            raise FileNotFoundError("tofueval needs --data-dir with the amazon-science/tofueval CSVs")
        d = pathlib.Path(data_dir)
        docs_file = d / "docs.json"
        if not docs_file.exists():
            raise FileNotFoundError(
                "tofueval needs docs.json (doc_id -> source text) in --data-dir. The repo ships "
                "only doc_ids; build the mapping from MediaSum + MeetingBank per the tofueval README "
                "(document_ids_dev_test_split.json), then save it as docs.json.")
        docs = json.loads(docs_file.read_text(encoding="utf-8"))

        csvs = list(d.glob("**/*factual*eval*.csv")) or list(d.glob("**/*.csv"))
        items: list[EvalItem] = []
        for path in csvs:
            with path.open(encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    doc_id = row.get("doc_id")
                    sent = (row.get("summ_sent") or row.get("sentence") or "").strip()
                    label = str(row.get("sent_label") or row.get("label") or "").strip().lower()
                    ctx = docs.get(doc_id)
                    if not sent or not label or ctx is None:
                        continue
                    items.append(EvalItem(
                        id=f"{path.stem}:{row.get('annotation_id') or len(items)}",
                        claim=sent,
                        context=[str(ctx)],
                        gold=label in _FAITHFUL,
                        task="summarization",
                        meta={"doc_id": doc_id, "type": row.get("type"), "model": row.get("model_name")},
                    ))
        rng = random.Random(seed)
        rng.shuffle(items)
        return items[:limit] if limit else items
