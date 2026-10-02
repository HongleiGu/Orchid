"""Outcome store — record, reconcile, observations, calibration (OR-61)."""
from __future__ import annotations

from app.evidence.outcomes import OutcomeStore, record_grounding


def test_record_then_reconcile_becomes_an_observation(tmp_path):
    store = OutcomeStore(tmp_path / "outcomes.jsonl")
    rid = store.record(confidence=0.9, predicted=True)
    assert store.stats() == {"total": 1, "reconciled": 0, "pending": 1}
    assert store.observations() == []          # nothing reconciled yet

    store.reconcile(rid, actual=True)
    assert store.stats()["reconciled"] == 1
    assert store.observations() == [(0.9, True)]   # predicted True, actual True -> correct


def test_wrong_prediction_is_incorrect_observation(tmp_path):
    store = OutcomeStore(tmp_path / "o.jsonl")
    rid = store.record(confidence=0.8, predicted=True)
    store.reconcile(rid, actual=False)
    assert store.observations() == [(0.8, False)]


def test_record_grounding_writes_one_per_claim(tmp_path):
    store = OutcomeStore(tmp_path / "o.jsonl")
    result = {"details": [
        {"text": "grounded claim", "grounded": True, "confidence": 0.95},
        {"text": "ungrounded claim", "grounded": False, "confidence": 0.1},
    ]}
    record_grounding(store, result, context={"check": "grounded"})
    assert store.stats()["total"] == 2


def test_report_from_reconciled_store(tmp_path):
    store = OutcomeStore(tmp_path / "o.jsonl")
    for conf, pred, actual in [(0.9, True, True), (0.8, True, True), (0.2, False, False)]:
        rid = store.record(confidence=conf, predicted=pred)
        store.reconcile(rid, actual=actual)
    r = store.report(target_risk=0.1)
    assert r.n == 3 and r.accuracy == 1.0      # all predictions matched reality


def test_reload_persists_across_instances(tmp_path):
    p = tmp_path / "o.jsonl"
    rid = OutcomeStore(p).record(confidence=0.7, predicted=True)
    OutcomeStore(p).reconcile(rid, actual=True)
    assert OutcomeStore(p).observations() == [(0.7, True)]   # append-only, merged on read
