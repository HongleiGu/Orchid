"""Evaluation harness for Layer-2 attribution (OR-63).

    python -m app.evidence.eval.run                       # built-in gold set, real NLI
    python -m app.evidence.eval.run --stub                # deterministic stub, offline
    python -m app.evidence.eval.run --model <hf-name>
    python -m app.evidence.eval.run --judge               # also run the LLM-judge baseline
    python -m app.evidence.eval.run --benchmark garage --limit 150 --judge

Metrics are **gold-driven**, not tied to any subset name, so any benchmark that
loads into the gold shape ({statement, passage, gold, subset, lang}) is scored the
same way. Two numbers matter, either side of the SUPPORTED line:

  * accept rate   — of items whose gold IS supported, how many we call supported
  * REJECT rate   — of items whose gold is NOT supported, how many we correctly
                    do NOT call supported          ← the headline (a mis-citation
                    that stands is the expensive error)

A predicted UNCERTAIN/REFUTED counts as "not supported" (abstention is safe).

With --judge the same items go through an ordinary LLM-as-judge ("does this source
support this claim?", temp 0) and the harness prints the head-to-head: NLI vs judge
on the reject rate, with the judge's own reasons on items it wrongly accepts. That
is the report's headline comparison. It spends tokens, so it is off by default and
needs a reachable LLM key ($LLM_JUDGE_MODEL or --judge-model); --judge-stub uses an
offline stub judge (no key) for a smoke test.

Benchmarks (--benchmark): `garage` = GaRAGe (Amazon, ACL 2025), auto-downloaded;
its `related-only` subset is real on-topic-but-unsupportive mis-citations — the
case that stresses a judge. See benchmarks.py.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import sys
import time

from app.evidence.schema import Claim, Source, Verdict
from app.evidence.verify import verify_claim, verify_claim_decomposed

GOLD = pathlib.Path(__file__).with_name("goldset.jsonl")
DEFAULT_JUDGE_MODEL = os.getenv("LLM_JUDGE_MODEL") or os.getenv("LLM_DEFAULT_MODEL") or "deepseek/deepseek-chat"


def load_gold() -> list[dict]:
    return [json.loads(line) for line in GOLD.read_text(encoding="utf-8").splitlines() if line.strip()]


def should_support(g: dict) -> bool:
    return g["gold"] == "supported"


def run_judge(gold: list[dict], judge, name: str, nli_reject: float, nli_accept: float) -> None:
    """Run the LLM-judge baseline and print the head-to-head against Layer-2 NLI.

    The judge answers supported/not, so we score it exactly where that is the whole
    question: items that should be rejected (mis-citations) and items that should be
    accepted (genuine). The gap between the two reject rates is the report's point.
    """
    print(f"\n{'='*70}\nLLM-JUDGE BASELINE  (model: {name})\n{'='*70}")
    reject_set = [g for g in gold if not should_support(g)]
    accept_set = [g for g in gold if should_support(g)]

    t0 = time.time()
    reject_verdicts = [(g, judge.judge(g["statement"], g["passage"])) for g in reject_set]
    accepted_ok = sum(1 for g in accept_set if judge.judge(g["statement"], g["passage"]).supported)
    elapsed = time.time() - t0

    judge_rejected = sum(1 for _, v in reject_verdicts if not v.supported)
    print("\nshould-reject items (mis-citations) — a few the judge got wrong, with its reason:")
    shown = 0
    for g, v in reject_verdicts:
        if v.supported and shown < 12:  # ACCEPT of a mis-citation = the failure
            print(f"  [ACCEPT] {g.get('subset',''):13} {g['statement'][:44]:44} → {v.reason}")
            shown += 1
    if shown == 0:
        print("  (none — the judge rejected every mis-citation)")

    j_reject = judge_rejected / len(reject_set) if reject_set else 0.0
    j_accept = accepted_ok / len(accept_set) if accept_set else 0.0
    print(f"\njudge — mis-citations rejected : {judge_rejected}/{len(reject_set)} = {j_reject:.0%}   (NLI: {nli_reject:.0%})")
    print(f"judge — genuine accepted       : {accepted_ok}/{len(accept_set)} = {j_accept:.0%}   (NLI: {nli_accept:.0%})")
    print(f"judge — {len(reject_set)+len(accept_set)} items in {elapsed:.1f}s")

    reject_gap = nli_reject - j_reject   # + => NLI rejects mis-citations more
    accept_gap = j_accept - nli_accept   # + => judge accepts genuine more
    print("\nreason:")
    if reject_gap >= 0.10 and accept_gap >= 0.10:
        # The informative case: mirror-image failure. Neither method is a
        # verifier on its own — which is the argument for the layered design.
        print(f"  Mirror-image failure. The judge accepts on-topic passages as support without"
              f"\n  checking entailment — it rejects only {j_reject:.0%} of mis-citations vs NLI's"
              f"\n  {nli_reject:.0%} (authority/topicality bias). But naive full-sentence NLI is too"
              f"\n  strict on abstractive claims — it accepts only {nli_accept:.0%} of genuine"
              f"\n  citations vs the judge's {j_accept:.0%}. So neither alone is a verifier: the judge"
              "\n  is credulous (low precision), this NLI is over-strict (low recall). This is the"
              "\n  case FOR the layered contract: mechanical NLI as the citation gate — with atomic"
              "\n  claim decomposition + a grounding-tuned checker to fix recall — and the judge"
              "\n  constrained to relevance/framing, never to checking citations.")
    elif reject_gap >= 0.10:
        print(f"  NLI rejects mis-citations {reject_gap:.0%} more often than the judge ({nli_reject:.0%}"
              f"\n  vs {j_reject:.0%}) at comparable recall. The judge treats on-topic as support"
              "\n  without checking entailment — the authority/topicality bias in the literature —"
              "\n  while mechanical NLI asks 'does THIS passage entail THIS statement?'. Mechanical"
              "\n  attribution > judge where it counts, so citation checking stays upstream of it.")
    elif accept_gap >= 0.10:
        print(f"  The judge accepts genuine citations more than NLI ({j_accept:.0%} vs {nli_accept:.0%})"
              f"\n  at comparable mis-citation rejection — this NLI is over-strict on abstractive"
              "\n  claims (missing entailment/paraphrase). Fix recall with atomic claim decomposition"
              "\n  and a grounding-tuned checker before drawing a precision conclusion.")
    else:
        print(f"  The two are within 10% both ways (reject NLI {nli_reject:.0%}/judge {j_reject:.0%},"
              f"\n  accept NLI {nli_accept:.0%}/judge {j_accept:.0%}), so this set does not separate"
              "\n  them on accuracy. What still holds: NLI is deterministic, ~free and local, vs the"
              "\n  judge's per-item token cost, latency and temperature non-determinism (95%->70%"
              "\n  same-verdict, temp 0->1, in the literature).")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.evidence.eval.run")
    ap.add_argument("--stub", action="store_true", help="use the deterministic StubNLI (offline)")
    ap.add_argument("--model", default=None, help="HF model name for TransformersNLI")
    ap.add_argument("--benchmark", default=None, choices=["garage"], help="external benchmark instead of the built-in gold set")
    ap.add_argument("--data", default=None, help="local path to the benchmark file (else auto-download)")
    ap.add_argument("--limit", type=int, default=None, help="cap the number of items (stratified)")
    ap.add_argument("--seed", type=int, default=0, help="sampling seed for --benchmark")
    ap.add_argument("--judge", action="store_true", help="also run the LLM-judge baseline (spends tokens; needs a key)")
    ap.add_argument("--judge-stub", action="store_true", help="run the judge baseline against an offline stub (no key)")
    ap.add_argument("--judge-model", default=None, help=f"LLM model for the judge (default: {DEFAULT_JUDGE_MODEL})")
    ap.add_argument("--decompose", action="store_true", help="verify via atomic claim decomposition (LLM extract; spends tokens)")
    ap.add_argument("--decompose-stub", action="store_true", help="decomposition via the offline stub splitter (no key)")
    ap.add_argument("--decompose-model", default=None, help=f"LLM model for decomposition (default: {DEFAULT_JUDGE_MODEL})")
    ap.add_argument("--show-atoms", action="store_true", help="print per-atom entailment (diagnostic; use with a small --limit)")
    args = ap.parse_args(argv)

    if args.stub:
        from app.evidence.nli import StubNLI
        nli, name = StubNLI(), "StubNLI"
    else:
        from app.evidence.nli import DEFAULT_MODEL, TransformersNLI
        name = args.model or DEFAULT_MODEL
        nli = TransformersNLI(model_name=name)

    decomposer = None
    decomp_name = "off"
    if args.decompose_stub:
        from app.evidence.decompose import StubDecomposer
        decomposer, decomp_name = StubDecomposer(), "StubDecomposer (offline)"
    elif args.decompose:
        from app.evidence.decompose import LLMDecomposer
        decomp_name = args.decompose_model or DEFAULT_JUDGE_MODEL
        decomposer = LLMDecomposer(model=decomp_name)

    if args.benchmark:
        from app.evidence.eval.benchmarks import LOADERS
        gold = LOADERS[args.benchmark](path=args.data, limit=args.limit, seed=args.seed)
        source = args.benchmark
    else:
        gold = load_gold()
        source = "goldset"
    print(f"model: {name}\nbenchmark: {source}\ndecompose: {decomp_name}\ngold items: {len(gold)}\n")

    t0 = time.time()
    rows = []
    for g in gold:
        claim = Claim(statement=g["statement"], sources=[Source(passage=g["passage"])])
        c = verify_claim_decomposed(claim, nli, decomposer) if decomposer else verify_claim(claim, nli)
        rows.append((g, c.verdict, c.confidence))
        if args.show_atoms and c.atoms:
            miss = (c.verdict == Verdict.SUPPORTED) != (g["gold"] == "supported")
            ent = sum(1 for a in c.atoms if a.verifiable and a.verdict == Verdict.SUPPORTED)
            vf = sum(1 for a in c.atoms if a.verifiable)
            print(f"\n[{'MISS' if miss else 'ok'}] gold={g['gold']} pred={c.verdict.value}  "
                  f"atoms entailed {ent}/{vf} (of {len(c.atoms)} total)")
            for a in c.atoms:
                flag = "verif" if a.verifiable else "OPIN "
                print(f"    {flag} {a.verdict.value:11} ({a.confidence:.2f})  {a.text[:70]}")
    elapsed = time.time() - t0

    def is_supported(v: Verdict) -> bool:
        return v == Verdict.SUPPORTED

    # Binary correctness (well-defined for 2-way and 3-way sets): does our
    # supported/not match gold's supported/not.
    binary_correct = sum(1 for g, v, _ in rows if is_supported(v) == should_support(g))

    accept_set = [(g, v) for g, v, _ in rows if should_support(g)]
    reject_set = [(g, v) for g, v, _ in rows if not should_support(g)]
    accepted_ok = sum(1 for _, v in accept_set if is_supported(v))
    rejected_ok = sum(1 for _, v in reject_set if not is_supported(v))
    nli_accept = accepted_ok / len(accept_set) if accept_set else 0.0
    nli_reject = rejected_ok / len(reject_set) if reject_set else 0.0

    # Per-subset breakdown (works for any labelling).
    per_sub: dict[str, list] = collections.defaultdict(list)
    for g, v, _ in rows:
        per_sub[g.get("subset", "?")].append((g, v))

    if len(rows) <= 40:
        print("per-item:")
        for g, v, conf in rows:
            mark = "ok " if is_supported(v) == should_support(g) else "MISS"
            print(f"  [{mark}] {g.get('subset','?'):13} {g.get('lang','')}  gold={g['gold']:11} "
                  f"pred={v.value:11} ({conf:.2f})  {g['statement'][:44]}")

    print("\nper-subset (correct = our supported/not matches gold):")
    for sub, items in sorted(per_sub.items()):
        ok = sum(1 for g, v in items if is_supported(v) == should_support(g))
        gold_sup = items[0][0]["gold"] == "supported"
        tag = "should SUPPORT" if gold_sup else "should reject "
        print(f"  {sub:14} {tag}  {ok}/{len(items)} = {ok/len(items):.0%}")

    print(f"\nbinary accuracy (supported vs not) : {binary_correct}/{len(rows)} = {binary_correct/len(rows):.0%}")
    print(f"genuine accepted (recall)          : {accepted_ok}/{len(accept_set)} = {nli_accept:.0%}")
    print(f"MIS-CITATIONS rejected             : {rejected_ok}/{len(reject_set)} = {nli_reject:.0%}   (the headline metric)")
    print(f"\n{len(rows)} items in {elapsed:.1f}s ({elapsed/len(rows)*1000:.0f} ms/item)")

    if args.judge or args.judge_stub:
        if args.judge_stub:
            from app.evidence.judge import StubJudge
            run_judge(gold, StubJudge(), "StubJudge (offline)", nli_reject, nli_accept)
        else:
            from app.evidence.judge import LLMJudge
            jmodel = args.judge_model or DEFAULT_JUDGE_MODEL
            run_judge(gold, LLMJudge(model=jmodel), jmodel, nli_reject, nli_accept)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
