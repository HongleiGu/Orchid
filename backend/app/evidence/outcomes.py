"""Outcome store — the calibration flywheel (OR-61).

Every grounding decision is recorded with its confidence and predicted label; when
reality is known (a human reconciles it, or a downstream signal lands) the true
label is attached. Reconciled records feed `calibration` to fit the gate's
abstention threshold and measure ECE/Brier — on *our* data, which our own design
note shows is mandatory because attribution metrics don't transfer across domains.

Storage is append-only JSONL (one event per line: a `record` then later a
`reconcile`), merged on read. Deliberately minimal and dependency-free — a Postgres
table is the clean follow-up, behind this same interface. Thread-/process-safe
enough for a single sidecar via append-only writes; not a concurrent DB.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from app.evidence.calibration import CalibrationReport, calibration_report


class OutcomeStore:
    def __init__(self, path: str | os.PathLike) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _append(self, obj: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def record(self, *, confidence: float, predicted: bool, kind: str = "grounding",
               context: dict | None = None) -> str:
        """Record a prediction. `predicted` is the asserted label (e.g. grounded),
        `confidence` the model's confidence in it. Returns the record id."""
        rid = uuid.uuid4().hex[:16]
        self._append({"event": "record", "id": rid, "ts": time.time(), "kind": kind,
                      "confidence": float(confidence), "predicted": bool(predicted),
                      "context": context or {}})
        return rid

    def reconcile(self, record_id: str, actual: bool) -> None:
        """Attach the ground-truth label for a recorded prediction."""
        self._append({"event": "reconcile", "id": record_id, "ts": time.time(),
                      "actual": bool(actual)})

    def _rows(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        rows: dict[str, dict] = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("event") == "record":
                rows[e["id"]] = {**e, "actual": None}
            elif e.get("event") == "reconcile" and e.get("id") in rows:
                rows[e["id"]]["actual"] = e.get("actual")
        return rows

    def observations(self, kind: str | None = None) -> list[tuple[float, bool]]:
        """(confidence, correct) for reconciled records; correct = predicted matched
        the actual label. Only these can calibrate."""
        out = []
        for r in self._rows().values():
            if r.get("actual") is None:
                continue
            if kind and r.get("kind") != kind:
                continue
            out.append((float(r["confidence"]), bool(r["predicted"]) == bool(r["actual"])))
        return out

    def report(self, target_risk: float = 0.1, kind: str | None = None) -> CalibrationReport:
        return calibration_report(self.observations(kind), target_risk=target_risk)

    def stats(self) -> dict:
        rows = self._rows()
        reconciled = sum(1 for r in rows.values() if r.get("actual") is not None)
        return {"total": len(rows), "reconciled": reconciled, "pending": len(rows) - reconciled}


def default_store() -> OutcomeStore | None:
    """The store configured by $EVIDENCE_OUTCOME_STORE, else None (recording off)."""
    path = os.environ.get("EVIDENCE_OUTCOME_STORE")
    return OutcomeStore(path) if path else None


def record_grounding(store: OutcomeStore, result: dict, context: dict | None = None) -> None:
    """Record one observation per claim from a ground_claims result (best-effort)."""
    for d in result.get("details", []):
        store.record(confidence=float(d.get("confidence", 0.0)),
                     predicted=bool(d.get("grounded", False)),
                     kind="grounding",
                     context={**(context or {}), "claim": d.get("text", "")[:200]})
