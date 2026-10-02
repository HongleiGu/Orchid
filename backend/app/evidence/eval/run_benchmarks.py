"""Run one scorer across several benchmark plugins and print a comparison table.

Loads the model once and reuses it. Example (in the evidence Docker image):

    python -m app.evidence.eval.run_benchmarks --data-root /bench \
        --benchmarks hallumix,ragtruth,verigray \
        --scorer grounding --minicheck --nli-model /models/minicheck --limit 80
"""
from __future__ import annotations

import argparse
import sys
import time

from app.evidence.eval.benchmark_eval import build_scorer, run
from app.evidence.eval.plugins import get_plugin

# Conventional sub-paths under --data-root for each benchmark's fetched data.
LAYOUT = {
    "hallumix": "hallumix",
    "ragtruth": "RAGTruth/dataset",
    "verigray": "verigray",
    "tofueval": "tofueval",
}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.evidence.eval.run_benchmarks")
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--benchmarks", default="hallumix,ragtruth,verigray")
    ap.add_argument("--limit", type=int, default=80)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--scorer", default="grounding", choices=["grounding", "nli", "judge", "stub"])
    ap.add_argument("--minicheck", action="store_true")
    ap.add_argument("--nli-model", default=None)
    ap.add_argument("--no-decompose", action="store_true")
    ap.add_argument("--support-fraction", type=float, default=0.5)
    ap.add_argument("--model", default="openrouter/openai/gpt-4o-mini")
    args = ap.parse_args(argv)

    scorer = build_scorer(args)
    names = [b.strip() for b in args.benchmarks.split(",") if b.strip()]
    print(f"scorer: {args.scorer}{' +minicheck' if args.minicheck else ''}"
          f"{'' if args.no_decompose or args.scorer != 'grounding' else ' +decompose'}  limit/bench: {args.limit}\n")
    print(f"{'benchmark':12} {'n':>4} {'acc':>6} {'bal_acc':>8} {'hallucF1':>9} {'faithF1':>8} {'AUROC':>6}  {'gray':>4}")

    rows = []
    for name in names:
        import pathlib
        dd = str(pathlib.Path(args.data_root) / LAYOUT.get(name, name))
        items = get_plugin(name).load(data_dir=dd, limit=args.limit, seed=args.seed)
        t0 = time.time()
        out = run(items, scorer)
        r = out["report"]
        auroc = f"{r.auroc:.3f}" if r.auroc is not None else "n/a"
        print(f"{name:12} {r.n:>4} {r.accuracy:>6.1%} {r.balanced_accuracy:>8.1%} "
              f"{r.halluc_f1:>9.1%} {r.faithful_f1:>8.1%} {auroc:>6}  {out['gray_zone']:>4}"
              f"   ({time.time()-t0:.0f}s)")
        rows.append((name, r))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
