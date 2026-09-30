"""Loaders that turn public academic benchmarks into the harness gold shape:

    {statement, passage, gold(supported|refuted|unsupported), subset, lang, source}

so the same NLI + judge harness (run.py) can score them unchanged.

**GaRAGe** (Amazon, ACL 2025 — github.com/amazon-science/GaRAGe): RAG answers with
human per-citation labels. We take the cleanest attribution unit — answer
sentences that cite *exactly one* source — paired with that source passage, and
label each by GaRAGe's own annotation of whether the cited passage supports the
claim:

    evidence_correct == ANSWER-THE-QUESTION  -> supported    (genuine)
    evidence_correct == RELATED-INFORMATION  -> unsupported  (on-topic but does
                                                 NOT support the claim — the
                                                 subtle, real-world mis-citation
                                                 that stresses a judge)
    evidence_correct == OUTDATED             -> unsupported
    evidence_relevant == NO                  -> unsupported  (irrelevant)

Ambiguous (UNKNOWN/blank) rows are dropped. This is faithful: real human labels,
no synthetic claim/passage pairing. The RELATED-INFORMATION bucket is the point —
it is where "the passage is about the right topic" tempts a judge into a false
'supported', while mechanical entailment (Layer 2) should still say no.
"""
from __future__ import annotations

import json
import pathlib
import random
import re
import urllib.request

GARAGE_URL = "https://raw.githubusercontent.com/amazon-science/GaRAGe/main/data/GaRAGe_benchmark.jsonl"
_SENT = re.compile(r"(?<=[.!?])\s+")
_CITE = re.compile(r"\[cite_(\d+)\]")


def _dataset_path(path: str | None, url: str, filename: str, cache_dir: str | None) -> pathlib.Path:
    if path:
        return pathlib.Path(path)
    cache = pathlib.Path(cache_dir) if cache_dir else pathlib.Path.home() / ".cache" / "orchid-evidence"
    dest = cache / filename
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {url}\n       -> {dest}")
        urllib.request.urlretrieve(url, dest)
    return dest


def load_garage(path: str | None = None, limit: int | None = None, seed: int = 0,
                cache_dir: str | None = None) -> list[dict]:
    p = _dataset_path(path, GARAGE_URL, "GaRAGe_benchmark.jsonl", cache_dir)
    genuine: list[dict] = []
    mismatch: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        er = d.get("evidence_relevant") or []
        ec = d.get("evidence_correct") or []
        grd = d.get("grounding") or []
        for sent in _SENT.split(d.get("answer_generate") or ""):
            cites = _CITE.findall(sent)
            if len(cites) != 1:
                continue
            i = int(cites[0]) - 1
            if not (0 <= i < len(er) and i < len(ec) and i < len(grd)):
                continue
            passage = str((grd[i] or {}).get(f"cite_{i+1}", "")).strip()
            statement = _CITE.sub("", sent).strip()
            if not passage or len(statement) < 15:
                continue
            rel, cor = er[i], ec[i]
            if rel == "NO":
                bucket, sub, gold = mismatch, "irrelevant", "unsupported"
            elif cor == "ANSWER-THE-QUESTION":
                bucket, sub, gold = genuine, "genuine", "supported"
            elif cor == "RELATED-INFORMATION":
                bucket, sub, gold = mismatch, "related-only", "unsupported"
            elif cor == "OUTDATED":
                bucket, sub, gold = mismatch, "outdated", "unsupported"
            else:
                continue
            bucket.append({"statement": statement, "passage": passage, "gold": gold,
                           "subset": sub, "lang": "en", "source": "garage"})

    rng = random.Random(seed)
    rng.shuffle(genuine)
    rng.shuffle(mismatch)
    # Keep the set from being all-genuine: cap genuine near the mismatch count so
    # both "accept genuine" and "reject mis-citation" are measured on real N.
    if limit:
        n_mis = min(len(mismatch), max(limit // 2, 1))
        n_gen = min(len(genuine), limit - n_mis)
    else:
        n_mis, n_gen = len(mismatch), min(len(genuine), 2 * len(mismatch))
    out = mismatch[:n_mis] + genuine[:n_gen]
    rng.shuffle(out)
    return out


LOADERS = {"garage": load_garage}
