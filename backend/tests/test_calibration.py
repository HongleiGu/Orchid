"""Calibration + selective prediction math (OR-60)."""
from __future__ import annotations

from app.evidence.calibration import (
    brier_score,
    calibration_report,
    expected_calibration_error,
    risk_coverage_curve,
    suggest_threshold,
)

# confidence tracks correctness: the top 3 are right, the bottom 3 wrong.
OBS = [(0.9, True), (0.8, True), (0.7, True), (0.4, False), (0.3, False), (0.2, False)]


def test_brier_bounds():
    assert brier_score([(1.0, True), (0.0, False)]) == 0.0      # perfect
    assert brier_score([(1.0, False), (0.0, True)]) == 1.0      # worst
    assert abs(brier_score(OBS) - 0.43 / 6) < 1e-9


def test_ece_zero_when_calibrated():
    # 60% confidence, 60% correct, all in one bin -> ECE ~ 0
    obs = [(0.6, True)] * 6 + [(0.6, False)] * 4
    assert expected_calibration_error(obs, bins=10) < 1e-9


def test_suggest_threshold_maximises_coverage_under_risk_bound():
    thr, cov, risk = suggest_threshold(OBS, target_risk=0.1)
    assert (thr, cov, risk) == (0.7, 0.5, 0.0)   # assert the 3 confident-correct


def test_risk_coverage_is_full_length_and_ends_at_overall_error():
    curve = risk_coverage_curve(OBS)
    assert len(curve) == len(OBS)
    assert curve[-1][0] == 1.0 and abs(curve[-1][1] - 0.5) < 1e-9


def test_report_fields():
    r = calibration_report(OBS, target_risk=0.1)
    assert r.n == 6 and r.accuracy == 0.5 and r.suggested_threshold == 0.7


def test_empty_is_safe():
    r = calibration_report([], target_risk=0.1)
    assert r.n == 0 and r.suggested_threshold == 1.0   # abstain-all when no data
