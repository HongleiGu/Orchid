"""Hallucination-detection metrics (no sklearn/scipy dependency).

Convention: gold/pred are *faithful* booleans (True = faithful/supported). The
"detection" view treats hallucination (not-faithful) as the positive class, since
catching hallucinations is the job.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Report:
    n: int
    accuracy: float
    balanced_accuracy: float
    halluc_precision: float   # positive class = hallucination (not faithful)
    halluc_recall: float
    halluc_f1: float
    faithful_f1: float
    auroc: float | None       # P(faithful) vs gold; None if scores are degenerate


def _f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def _auroc(scores: list[float], gold_faithful: list[bool]) -> float | None:
    # AUROC that higher score => faithful (positive=faithful). Rank-based (Mann-Whitney).
    pos = [s for s, g in zip(scores, gold_faithful) if g]
    neg = [s for s, g in zip(scores, gold_faithful) if not g]
    if not pos or not neg:
        return None
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1  # average rank (1-indexed) for ties
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    sum_pos = sum(r for r, g in zip(ranks, gold_faithful) if g)
    n_pos, n_neg = len(pos), len(neg)
    return (sum_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def evaluate(gold_faithful: list[bool], pred_faithful: list[bool],
             p_faithful: list[float] | None = None) -> Report:
    n = len(gold_faithful)
    correct = sum(1 for g, p in zip(gold_faithful, pred_faithful) if g == p)
    # hallucination = positive class
    tp = sum(1 for g, p in zip(gold_faithful, pred_faithful) if not g and not p)
    fp = sum(1 for g, p in zip(gold_faithful, pred_faithful) if g and not p)
    fn = sum(1 for g, p in zip(gold_faithful, pred_faithful) if not g and p)
    tn = sum(1 for g, p in zip(gold_faithful, pred_faithful) if g and p)
    hp, hr, hf = _f1(tp, fp, fn)
    _, _, ff = _f1(tn, fn, fp)  # faithful class
    # balanced accuracy = mean of per-class recall
    halluc_support = tp + fn
    faithful_support = tn + fp
    rec_h = tp / halluc_support if halluc_support else 0.0
    rec_f = tn / faithful_support if faithful_support else 0.0
    bal = (rec_h + rec_f) / 2
    auroc = _auroc(p_faithful, gold_faithful) if p_faithful else None
    return Report(n=n, accuracy=correct / n if n else 0.0, balanced_accuracy=bal,
                  halluc_precision=hp, halluc_recall=hr, halluc_f1=hf,
                  faithful_f1=ff, auroc=auroc)
