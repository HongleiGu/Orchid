"""Confidence calibration + selective prediction (OR-60).

Turns a set of (confidence, correct) observations — produced by reconciling the
outcome store against reality — into the numbers that make the contract
trustworthy: is the confidence calibrated (ECE, Brier), and at what threshold
should the gate abstain vs assert (risk–coverage, suggested threshold).

Pure functions, no I/O: the outcome store feeds them observations. Our own design
note's caveat (attribution metrics don't transfer across domains) is why these
must run on *your* reconciled data, not be guessed.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CalibrationReport:
    n: int
    accuracy: float
    brier: float
    ece: float
    suggested_threshold: float   # abstain below this confidence
    coverage_at_threshold: float  # fraction asserted at the suggested threshold
    risk_at_threshold: float      # error rate among asserted, at the threshold


def brier_score(obs: list[tuple[float, bool]]) -> float:
    """Mean squared error between confidence and outcome (0/1). Lower is better."""
    if not obs:
        return 0.0
    return sum((c - (1.0 if ok else 0.0)) ** 2 for c, ok in obs) / len(obs)


def expected_calibration_error(obs: list[tuple[float, bool]], bins: int = 10) -> float:
    """ECE: average |accuracy − confidence| per confidence bin, weighted by bin
    size. 0 = perfectly calibrated."""
    if not obs:
        return 0.0
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for c, ok in obs:
        idx = min(bins - 1, max(0, int(c * bins)))
        buckets[idx].append((c, ok))
    ece = 0.0
    for b in buckets:
        if not b:
            continue
        conf = sum(c for c, _ in b) / len(b)
        acc = sum(1 for _, ok in b if ok) / len(b)
        ece += (len(b) / len(obs)) * abs(acc - conf)
    return ece


def risk_coverage_curve(obs: list[tuple[float, bool]]) -> list[tuple[float, float]]:
    """(coverage, selective-risk) as the confidence threshold sweeps from assert-all
    down. Coverage = fraction asserted; risk = error rate among the asserted."""
    if not obs:
        return []
    ranked = sorted(obs, key=lambda o: o[0], reverse=True)
    curve, errors = [], 0
    for i, (_, ok) in enumerate(ranked, start=1):
        if not ok:
            errors += 1
        curve.append((i / len(ranked), errors / i))
    return curve


def suggest_threshold(obs: list[tuple[float, bool]], target_risk: float = 0.1) -> tuple[float, float, float]:
    """Lowest confidence threshold whose asserted set has error rate ≤ target_risk,
    i.e. maximise coverage subject to the risk bound (selective prediction).
    Returns (threshold, coverage, risk). If no threshold meets the bound, returns
    the most conservative (highest-confidence-only) operating point."""
    if not obs:
        return 1.0, 0.0, 0.0
    ranked = sorted(obs, key=lambda o: o[0], reverse=True)
    best = None  # (coverage, threshold, risk) meeting the bound, max coverage
    errors = 0
    for i, (conf, ok) in enumerate(ranked, start=1):
        if not ok:
            errors += 1
        risk = errors / i
        if risk <= target_risk:
            best = (i / len(ranked), conf, risk)
    if best is not None:
        cov, thr, risk = best
        return thr, cov, risk
    top_conf, top_ok = ranked[0]
    return top_conf, 1 / len(ranked), 0.0 if top_ok else 1.0


def calibration_report(obs: list[tuple[float, bool]], target_risk: float = 0.1,
                       bins: int = 10) -> CalibrationReport:
    n = len(obs)
    acc = sum(1 for _, ok in obs if ok) / n if n else 0.0
    thr, cov, risk = suggest_threshold(obs, target_risk)
    return CalibrationReport(
        n=n, accuracy=acc,
        brier=brier_score(obs),
        ece=expected_calibration_error(obs, bins),
        suggested_threshold=thr, coverage_at_threshold=cov, risk_at_threshold=risk,
    )
