"""Judge-gate vs NLI-gate, in the auto-research pipeline (OR-58 experiment).

For each research query: retrieve -> write a brief -> score every claim two ways
against the SAME retrieved evidence:
  * NLI gate   — decomposition + full-evidence entailment (the Layer-2 contract)
  * judge gate — an LLM asked "is this claim supported by these sources?"
and run the citation-identity check on the brief.

The paper's punchline, in the pipeline: the judge accepts claims the NLI gate
rejects (authority/credulity bias, cf. the GaRAGe result), and neither NLI content
grounding nor the judge catches fabricated citation *identities* — only the
dedicated identity check does. Run in the evidence image (torch + litellm +
tavily), .env mounted:

    python -m app.evidence.eval.gate_compare --n 6 --minicheck --nli-model /models/minicheck
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from app.core.types import AgentOutput
from app.evidence.citation_identity import unsupported_citations
from app.evidence.eval.research_grounding import retrieve, write

QUERIES = [
    "What do 2025-2026 studies find about LLM-as-a-judge reliability and bias?",
    "How effective is retrieval-augmented generation at reducing hallucination in 2025-2026?",
    "What are the main failure modes of LLM tool-use and function-calling agents in 2025-2026?",
    "What does recent work say about chain-of-thought faithfulness in large language models?",
    "How well do LLMs handle long-horizon multi-step agent tasks according to 2025-2026 work?",
    "What methods detect citation hallucination in LLM-generated scientific text (2025-2026)?",
]


async def eval_query(q: str, model: str, verifier, decomposer, judge, k: int) -> dict:
    from app.core import dag
    from app.evidence.schema import Claim, Source, Verdict
    from app.evidence.verify import verify_claim_decomposed

    sources = retrieve(q, k)
    if not sources:
        return {"query": q, "skipped": "no sources"}
    brief = write(model, q, sources)
    claims = dag._split_claims(brief)
    up = {"retrieve": AgentOutput(content="\n\n".join(sources))}
    chunks = dag._grounding_sources(AgentOutput(content=brief), up, {"sources": ["retrieve"]})
    srcs = [Source(passage=c) for c in chunks]
    joined = "\n\n".join(sources)[:6000]

    nli_g, judge_g = [], []
    for s in claims:
        c = verify_claim_decomposed(Claim(statement=s, sources=srcs), verifier, decomposer, support_fraction=0.5)
        nli_g.append(c.verdict == Verdict.SUPPORTED)
        judge_g.append(judge.judge(s, joined).supported)
    fab = unsupported_citations(brief, sources)
    return {"query": q, "claims": len(claims), "nli_g": sum(nli_g), "judge_g": sum(judge_g),
            "judge_accepts_nli_rejects": sum(1 for n, j in zip(nli_g, judge_g) if j and not n),
            "nli_rejects": sum(1 for n in nli_g if not n), "fab": fab}


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.evidence.eval.gate_compare")
    ap.add_argument("--n", type=int, default=len(QUERIES))
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--model", default=os.getenv("LLM_DEFAULT_MODEL") or "openrouter/openai/gpt-4o-mini")
    ap.add_argument("--minicheck", action="store_true")
    ap.add_argument("--nli-model", default=None)
    args = ap.parse_args(argv)

    if args.minicheck:
        from app.evidence.nli import MINICHECK_MODEL, MiniCheckNLI
        verifier = MiniCheckNLI(model_name=args.nli_model or MINICHECK_MODEL)
    else:
        from app.evidence.nli import DEFAULT_MODEL, TransformersNLI
        verifier = TransformersNLI(model_name=args.nli_model or DEFAULT_MODEL)
    from app.evidence.decompose import LLMDecomposer
    from app.evidence.judge import LLMJudge
    decomposer = LLMDecomposer(model=args.model)
    judge = LLMJudge(model=args.model)

    print(f"writer/judge/decomposer: {args.model}\nqueries: {args.n}\n")
    rows = []
    for q in QUERIES[: args.n]:
        r = await eval_query(q, args.model, verifier, decomposer, judge, args.k)
        rows.append(r)
        if "skipped" in r:
            print(f"- [skip] {q[:60]} ({r['skipped']})")
            continue
        print(f"- {q[:58]:58}  claims={r['claims']:2}  NLI_grounded={r['nli_g']:2}  "
              f"judge_grounded={r['judge_g']:2}  judge✓@NLI✗={r['judge_accepts_nli_rejects']:2}  "
              f"fab_cites={len(r['fab'])}")

    good = [r for r in rows if "skipped" not in r]
    tc = sum(r["claims"] for r in good)
    tn = sum(r["nli_g"] for r in good)
    tj = sum(r["judge_g"] for r in good)
    trej = sum(r["nli_rejects"] for r in good)
    tja = sum(r["judge_accepts_nli_rejects"] for r in good)
    tfab = sum(len(r["fab"]) for r in good)
    print("\n" + "=" * 66)
    print(f"TOTAL over {len(good)} queries, {tc} claims:")
    print(f"  NLI gate   grounded : {tn}/{tc} = {tn/tc:.0%}")
    print(f"  judge gate grounded : {tj}/{tc} = {tj/tc:.0%}")
    print(f"  of {trej} claims the NLI gate REJECTED, the judge accepted {tja} "
          f"({(tja/trej if trej else 0):.0%}) — credulity/authority bias in the pipeline.")
    print(f"  fabricated citation identities flagged (NLI/judge both miss these): {tfab}")
    if tfab:
        for r in good:
            for f in r["fab"]:
                print(f"      · {f}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
