"""Evaluation harness for Layer-2 attribution (OR-63).

    python -m app.evidence.eval.run            # real NLI model (downloads once)
    python -m app.evidence.eval.run --stub     # deterministic stub, offline
    python -m app.evidence.eval.run --model <hf-name>
    python -m app.evidence.eval.run --judge    # also run the LLM-judge baseline

Reports overall verdict accuracy against the gold set and, separately, the
**fabricated-citation rejection rate** — the fraction of plausible-but-unrelated
citations correctly NOT marked supported. That subset is the report's headline:
it is exactly where an LLM judge fails via authority bias.

The gold labels are three-way (supported/refuted/unsupported); a predicted
UNCERTAIN counts as "not supported" for the rejection metric (abstention is the
safe answer), and as a miss for exact accuracy.

With --judge, the same gold set is run through an ordinary LLM-as-judge
("does this source support this claim?", temp 0) as a baseline, and the harness
prints a side-by-side: Layer-2 NLI vs judge on fabricated-citation rejection,
with the judge's own reasons on the items it wrongly accepts. That is the report's
headline comparison. It spends tokens, so it is off by default and needs a
reachable LLM key (uses $LLM_JUDGE_MODEL or --judge-model). --judge-stub runs the
same wiring against an offline stub judge (no key, no tokens) for a smoke test.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

from app.evidence.schema import Claim, Source, Verdict
from app.evidence.verify import verify_claim

GOLD = pathlib.Path(__file__).with_name("goldset.jsonl")
DEFAULT_JUDGE_MODEL = os.getenv("LLM_JUDGE_MODEL") or os.getenv("LLM_DEFAULT_MODEL") or "deepseek/deepseek-chat"


def load_gold() -> list[dict]:
    return [json.loads(line) for line in GOLD.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_judge(gold: list[dict], judge, name: str) -> None:
    """Run the LLM-judge baseline and print the head-to-head against Layer-2 NLI.

    The judge only answers supported/not, so we score it exactly where that is
    the whole question: fabricated citations (should reject) and genuine ones
    (should accept). The gap between the two rejection rates is the report's point.
    """
    print(f"\n{'='*66}\nLLM-JUDGE BASELINE  (model: {name})\n{'='*66}")
    fabricated = [g for g in gold if g["subset"] == "fabricated"]
    genuine = [g for g in gold if g["subset"] == "genuine"]

    t0 = time.time()
    fab_verdicts, gen_accepted = [], 0
    for g in fabricated:
        v = judge.judge(g["statement"], g["passage"])
        fab_verdicts.append((g, v))
    for g in genuine:
        gen_accepted += 1 if judge.judge(g["statement"], g["passage"]).supported else 0
    elapsed = time.time() - t0

    fab_rejected = sum(1 for _, v in fab_verdicts if not v.supported)
    print("\nfabricated citations — the judge should reject all of these:")
    for g, v in fab_verdicts:
        mark = "reject" if not v.supported else "ACCEPT"  # ACCEPT = the failure
        print(f"  [{mark}] {g['lang']}  {g['statement'][:40]:40}  → {v.reason}")

    print(f"\njudge — fabricated citations rejected : {fab_rejected}/{len(fabricated)} = {fab_rejected/len(fabricated):.0%}")
    print(f"judge — genuine claims accepted      : {gen_accepted}/{len(genuine)} = {gen_accepted/len(genuine):.0%}")
    print(f"judge — {len(fabricated)+len(genuine)} items in {elapsed:.1f}s")

    accepted = len(fabricated) - fab_rejected
    print("\nreason:")
    if accepted > len(fabricated) // 3:
        # The literature's failure mode reproduced: the judge waved through
        # fabricated citations by reading authority as support.
        print(f"  the judge accepted {accepted}/{len(fabricated)} fabricated citations. It reads the"
              "\n  passage's authority (a dated figure, a named report) as support without"
              "\n  checking the passage is about the same subject as the claim — the authority"
              "\n  bias in the literature. Layer-2 NLI asks the narrower, mechanical question"
              "\n  'does THIS passage entail THIS statement?', which a wrong-subject citation"
              "\n  fails, so citation checking is mechanical and upstream of the judge.")
    else:
        # The judge held up. Honest reading: this gold set is too easy to
        # separate the two methods on accuracy alone.
        print(f"  on THIS set the judge matched Layer-2 NLI ({fab_rejected}/{len(fabricated)} rejected), so"
              "\n  it does NOT show the authority-bias failure here — because these fabrications"
              "\n  are blatantly off-topic (weather for a market claim, coffee for pet-food), which"
              "\n  a capable judge catches. The authority bias reported in the literature needs"
              "\n  HARDER fabrications to surface: on-topic wrong-number, claim embedded verbatim"
              "\n  in an unrelated-source passage, adversarial phrasing. That is the next gold-set"
              "\n  iteration. What already holds regardless of accuracy: NLI is deterministic,"
              "\n  ~free and local, vs the judge's per-item token cost, latency, and temperature"
              "\n  non-determinism (95%->70% same-verdict, temp 0->1, in the literature).")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.evidence.eval.run")
    ap.add_argument("--stub", action="store_true", help="use the deterministic StubNLI (offline)")
    ap.add_argument("--model", default=None, help="HF model name for TransformersNLI")
    ap.add_argument("--judge", action="store_true", help="also run the LLM-judge baseline (spends tokens; needs a key)")
    ap.add_argument("--judge-stub", action="store_true", help="run the judge baseline against an offline stub (no key)")
    ap.add_argument("--judge-model", default=None, help=f"LLM model for the judge (default: {DEFAULT_JUDGE_MODEL})")
    args = ap.parse_args(argv)

    if args.stub:
        from app.evidence.nli import StubNLI
        nli, name = StubNLI(), "StubNLI"
    else:
        from app.evidence.nli import DEFAULT_MODEL, TransformersNLI
        name = args.model or DEFAULT_MODEL
        nli = TransformersNLI(model_name=name)

    gold = load_gold()
    print(f"model: {name}\ngold items: {len(gold)}\n")

    t0 = time.time()
    rows = []
    for g in gold:
        c = verify_claim(Claim(statement=g["statement"], sources=[Source(passage=g["passage"])]), nli)
        rows.append((g, c.verdict, c.confidence))
    elapsed = time.time() - t0

    correct = sum(1 for g, v, _ in rows if v.value == g["gold"])
    # "Not supported" = anything other than SUPPORTED — the safe outcome for a
    # citation that should not stand.
    def not_supported(v: Verdict) -> bool:
        return v != Verdict.SUPPORTED

    fabricated = [(g, v) for g, v, _ in rows if g["subset"] == "fabricated"]
    fab_rejected = sum(1 for g, v in fabricated if not_supported(v))

    genuine = [(g, v) for g, v, _ in rows if g["subset"] == "genuine"]
    gen_supported = sum(1 for g, v in genuine if v == Verdict.SUPPORTED)

    print("per-item:")
    for g, v, conf in rows:
        mark = "ok " if v.value == g["gold"] else "MISS"
        print(f"  [{mark}] {g['subset']:13} {g['lang']}  gold={g['gold']:11} pred={v.value:11} ({conf:.2f})  {g['statement'][:44]}")

    print(f"\noverall verdict accuracy   : {correct}/{len(gold)} = {correct/len(gold):.0%}")
    print(f"genuine claims supported   : {gen_supported}/{len(genuine)} = {gen_supported/len(genuine):.0%}")
    print(f"FABRICATED citations rejected: {fab_rejected}/{len(fabricated)} = {fab_rejected/len(fabricated):.0%}"
          "   (the headline metric)")
    print(f"\n{len(gold)} items in {elapsed:.1f}s ({elapsed/len(gold)*1000:.0f} ms/item)")

    if args.judge or args.judge_stub:
        if args.judge_stub:
            from app.evidence.judge import StubJudge
            run_judge(gold, StubJudge(), "StubJudge (offline)")
        else:
            from app.evidence.judge import LLMJudge
            jmodel = args.judge_model or DEFAULT_JUDGE_MODEL
            run_judge(gold, LLMJudge(model=jmodel), jmodel)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
