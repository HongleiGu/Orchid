"""Generic benchmark runner: score a plugin's items with a chosen scorer and
report hallucination-detection metrics. Decoupled from the pipeline.

    python -m app.evidence.eval.benchmark_eval --benchmark hallumix --data-dir <dir> \
        --scorer grounding --minicheck --nli-model /models/minicheck --limit 200

Scorers: grounding (our checker: decompose+full-evidence+guards), nli (whole
sentence), judge (LLM), stub (offline token overlap, for smoke tests).
"""
from __future__ import annotations

import argparse
import sys

from app.evidence.eval.plugins import available, get_plugin
from app.evidence.eval.plugins.base import EvalItem, Scorer
from app.evidence.eval.plugins.metrics import evaluate


def _grounding_scorer(verifier, decomposer, support_fraction: float = 0.5) -> Scorer:
    from app.evidence.grounding import chunk_sources, ground_claims

    def score(claim: str, context: list[str]) -> tuple[bool, float]:
        res = ground_claims(verifier, [claim], chunk_sources(context),
                            decomposer=decomposer, support_fraction=support_fraction)
        d = res["details"][0]
        p_faithful = d["confidence"] if d["grounded"] else 1.0 - d["confidence"]
        return bool(d["grounded"]), float(p_faithful)

    return score


def _judge_scorer(model: str) -> Scorer:
    from app.evidence.judge import LLMJudge
    judge = LLMJudge(model=model)

    def score(claim: str, context: list[str]) -> tuple[bool, float]:
        v = judge.judge(claim, "\n\n".join(context)[:6000])
        return bool(v.supported), 1.0 if v.supported else 0.0

    return score


def _stub_scorer() -> Scorer:
    import re

    def toks(s: str) -> set[str]:
        return set(re.findall(r"[a-z0-9]+", s.lower()))

    def score(claim: str, context: list[str]) -> tuple[bool, float]:
        c = toks(claim)
        if not c:
            return True, 1.0
        hay = toks(" ".join(context))
        overlap = len(c & hay) / len(c)
        return overlap >= 0.6, overlap

    return score


def build_scorer(args) -> Scorer:
    if args.scorer == "stub":
        return _stub_scorer()
    if args.scorer == "judge":
        return _judge_scorer(args.model)
    # grounding | nli
    if args.minicheck:
        from app.evidence.nli import MINICHECK_MODEL, MiniCheckNLI
        verifier = MiniCheckNLI(model_name=args.nli_model or MINICHECK_MODEL)
    else:
        from app.evidence.nli import DEFAULT_MODEL, TransformersNLI
        verifier = TransformersNLI(model_name=args.nli_model or DEFAULT_MODEL)
    decomposer = None
    if args.scorer == "grounding" and not args.no_decompose:
        from app.evidence.decompose import LLMDecomposer
        decomposer = LLMDecomposer(model=args.model)
    return _grounding_scorer(verifier, decomposer, args.support_fraction)


def run(items: list[EvalItem], scorer: Scorer) -> dict:
    gold, pred, pf = [], [], []
    graded, abstained = 0, 0
    for it in items:
        if it.gold_abstain:               # gray-zone items: not part of binary metrics
            abstained += 1
            continue
        p, conf = scorer(it.claim, it.context)
        gold.append(it.gold)
        pred.append(p)
        pf.append(conf)
        graded += 1
    report = evaluate(gold, pred, pf)
    return {"report": report, "graded": graded, "gray_zone": abstained}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.evidence.eval.benchmark_eval")
    ap.add_argument("--benchmark", required=True, help=f"one of: {', '.join(available())}")
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--scorer", default="grounding", choices=["grounding", "nli", "judge", "stub"])
    ap.add_argument("--minicheck", action="store_true")
    ap.add_argument("--nli-model", default=None)
    ap.add_argument("--no-decompose", action="store_true")
    ap.add_argument("--support-fraction", type=float, default=0.5)
    ap.add_argument("--model", default="openrouter/openai/gpt-4o-mini")
    args = ap.parse_args(argv)

    items = get_plugin(args.benchmark).load(data_dir=args.data_dir, limit=args.limit, seed=args.seed)
    faithful = sum(1 for it in items if it.gold and not it.gold_abstain)
    print(f"benchmark: {args.benchmark}  items: {len(items)}  (faithful {faithful}, "
          f"hallucinated {len(items)-faithful}, gray {sum(1 for it in items if it.gold_abstain)})")
    print(f"scorer: {args.scorer}{' +minicheck' if args.minicheck else ''}"
          f"{'' if args.no_decompose or args.scorer!='grounding' else ' +decompose'}\n")

    out = run(items, build_scorer(args))
    r = out["report"]
    print(f"graded: {out['graded']}  gray-zone (excluded): {out['gray_zone']}")
    print(f"accuracy           : {r.accuracy:.1%}")
    print(f"balanced accuracy  : {r.balanced_accuracy:.1%}")
    print(f"hallucination  P/R/F1: {r.halluc_precision:.1%} / {r.halluc_recall:.1%} / {r.halluc_f1:.1%}")
    print(f"faithful F1        : {r.faithful_f1:.1%}")
    print(f"AUROC (P_faithful) : {r.auroc:.3f}" if r.auroc is not None else "AUROC: n/a")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
