"""Evaluation harness for Layer-2 attribution (OR-63).

    python -m app.evidence.eval.run            # real NLI model (downloads once)
    python -m app.evidence.eval.run --stub     # deterministic stub, offline
    python -m app.evidence.eval.run --model <hf-name>

Reports overall verdict accuracy against the gold set and, separately, the
**fabricated-citation rejection rate** — the fraction of plausible-but-unrelated
citations correctly NOT marked supported. That subset is the report's headline:
it is exactly where an LLM judge fails via authority bias.

The gold labels are three-way (supported/refuted/unsupported); a predicted
UNCERTAIN counts as "not supported" for the rejection metric (abstention is the
safe answer), and as a miss for exact accuracy.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

from app.evidence.schema import Claim, Source, Verdict
from app.evidence.verify import verify_claim

GOLD = pathlib.Path(__file__).with_name("goldset.jsonl")


def load_gold() -> list[dict]:
    return [json.loads(line) for line in GOLD.read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.evidence.eval.run")
    ap.add_argument("--stub", action="store_true", help="use the deterministic StubNLI (offline)")
    ap.add_argument("--model", default=None, help="HF model name for TransformersNLI")
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
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
