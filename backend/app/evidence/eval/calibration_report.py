"""Print a calibration report from an outcome store (OR-60/61).

    python -m app.evidence.eval.calibration_report <store.jsonl> [--target-risk 0.1]

Shows how many predictions are recorded vs reconciled, and — over the reconciled
ones — accuracy, Brier, ECE, and the suggested abstention threshold (the confidence
below which the gate should abstain to hold selective risk under the target).
"""
from __future__ import annotations

import argparse
import sys

from app.evidence.outcomes import OutcomeStore


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.evidence.eval.calibration_report")
    ap.add_argument("store", help="path to the outcome-store JSONL")
    ap.add_argument("--target-risk", type=float, default=0.1)
    ap.add_argument("--kind", default=None, help="filter by record kind (e.g. grounding)")
    args = ap.parse_args(argv)

    store = OutcomeStore(args.store)
    stats = store.stats()
    print(f"store: {args.store}")
    print(f"records: {stats['total']}  reconciled: {stats['reconciled']}  pending: {stats['pending']}")
    if stats["reconciled"] == 0:
        print("\nNothing reconciled yet — record predictions, attach ground truth, then re-run.")
        return 0
    r = store.report(target_risk=args.target_risk, kind=args.kind)
    print(f"\nover {r.n} reconciled observations (target selective risk {args.target_risk:.0%}):")
    print(f"  accuracy            : {r.accuracy:.1%}")
    print(f"  Brier score         : {r.brier:.4f}   (lower better)")
    print(f"  ECE                 : {r.ece:.4f}   (lower better)")
    print(f"  suggested threshold : {r.suggested_threshold:.3f}  -> abstain below this confidence")
    print(f"  at that threshold   : coverage {r.coverage_at_threshold:.0%}, selective risk {r.risk_at_threshold:.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
