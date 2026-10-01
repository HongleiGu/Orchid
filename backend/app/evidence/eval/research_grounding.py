"""Does Layer-2 NLI grounding improve the auto-research pipeline? (OR-58 measurement)

Runs the real loop end-to-end, offline (not through run_executor / the DB):

    retrieve (Tavily)  ->  write (LLM)  ->  grounded check (NLI)  ->  revise -> ...

and reports the grounded fraction of the writer's claims BEFORE and AFTER the
NLI-driven revise loop. It drives the exact contract code path the DAG uses
(`dag._run_grounding_check` + the `grounded` check), so it validates the wiring
as well as measuring the effect.

Run in the evidence Docker image (torch for NLI; litellm + tavily are base deps),
with .env mounted for OPENROUTER/ TAVILY keys:

    python -m app.evidence.eval.research_grounding --query "..." [--minicheck --model /models/minicheck]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from app.core import dag
from app.core.types import AgentOutput

WRITER_SYS = (
    "You write a short factual research brief answering the QUESTION using ONLY the "
    "SOURCES provided. Every sentence must be directly supported by a source; do not "
    "add outside knowledge, speculation, or figures the sources do not contain. "
    "If FEEDBACK lists unsupported sentences, delete or rewrite them to match the sources. "
    "Output 6-12 sentences, no headings."
)


def retrieve(query: str, k: int) -> list[str]:
    from tavily import TavilyClient

    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    res = client.search(query, max_results=k, search_depth="advanced")
    out = []
    for r in res.get("results", []):
        c = (r.get("content") or "").strip()
        if c:
            out.append(f"{r.get('title','')} — {c}")
    return out


def write(model: str, question: str, sources: list[str], feedback: str = "") -> str:
    import litellm

    src_block = "\n\n".join(f"[S{i+1}] {s}" for i, s in enumerate(sources))
    user = f"QUESTION:\n{question}\n\nSOURCES:\n{src_block}"
    if feedback:
        user += f"\n\nFEEDBACK (unsupported sentences to fix or drop):\n{feedback}"
    resp = litellm.completion(
        model=model,
        messages=[{"role": "system", "content": WRITER_SYS}, {"role": "user", "content": user}],
        temperature=0.0,
    )
    return resp["choices"][0]["message"]["content"]


async def grounded_report(brief: str, sources: list[str]) -> tuple[float, list[str], str]:
    """Run the live contract check; return grounded fraction, ungrounded
    sentences (for feedback), and the contract status."""
    out = AgentOutput(content=brief, agent_name="writer")
    upstream = {"retrieve": AgentOutput(content="\n\n".join(sources), agent_name="retrieve")}
    verdict = await dag._run_grounding_check(out, upstream, {"sources": ["retrieve"], "min_grounded": 0.8}, index=0)
    return verdict.get("fraction", 1.0), verdict.get("ungrounded", []), verdict["status"]


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.evidence.eval.research_grounding")
    ap.add_argument("--query", default="What do 2025-2026 studies find about LLM-as-a-judge reliability and bias?")
    ap.add_argument("--model", default=os.getenv("LLM_DEFAULT_MODEL") or "openrouter/openai/gpt-4o-mini")
    ap.add_argument("--k", type=int, default=6, help="sources to retrieve")
    ap.add_argument("--max-revises", type=int, default=2)
    ap.add_argument("--minicheck", action="store_true", help="use MiniCheck as the grounding verifier")
    ap.add_argument("--nli-model", default=None, help="NLI model/path (hub id or local)")
    args = ap.parse_args(argv)

    if args.minicheck:
        from app.evidence.nli import MINICHECK_MODEL, MiniCheckNLI
        dag.set_grounding_verifier(MiniCheckNLI(model_name=args.nli_model or MINICHECK_MODEL))
        nli_name = args.nli_model or MINICHECK_MODEL
    else:
        from app.evidence.nli import DEFAULT_MODEL, TransformersNLI
        dag.set_grounding_verifier(TransformersNLI(model_name=args.nli_model or DEFAULT_MODEL))
        nli_name = args.nli_model or DEFAULT_MODEL

    print(f"query : {args.query}\nwriter: {args.model}\nnli   : {nli_name}\n")
    sources = retrieve(args.query, args.k)
    print(f"retrieved {len(sources)} sources\n")
    if not sources:
        print("no sources retrieved — check TAVILY_API_KEY/network")
        return 1

    brief = write(args.model, args.query, sources)
    frac, ungrounded, status = await grounded_report(brief, sources)
    history = [(0, frac, len(ungrounded), status)]
    print(f"[attempt 0] grounded {frac:.0%}  contract={status}  ungrounded={len(ungrounded)}")
    for u in ungrounded:
        print(f"    - {u[:110]}")

    attempt = 0
    while status == "fail" and attempt < args.max_revises:
        attempt += 1
        feedback = "\n".join(f"- {u}" for u in ungrounded)
        brief = write(args.model, args.query, sources, feedback=feedback)
        frac, ungrounded, status = await grounded_report(brief, sources)
        history.append((attempt, frac, len(ungrounded), status))
        print(f"\n[attempt {attempt}] grounded {frac:.0%}  contract={status}  ungrounded={len(ungrounded)}")
        for u in ungrounded:
            print(f"    - {u[:110]}")

    first, last = history[0], history[-1]
    print("\n" + "=" * 60)
    print(f"RESULT: grounded {first[1]:.0%} -> {last[1]:.0%} over {last[0]} revise(s); "
          f"contract {first[3]} -> {last[3]}.")
    print("The NLI grounding check flagged unsupported claims the writer then\n"
          "removed/corrected — the mechanism by which Layer-2 improves the pipeline.\n"
          "(A judge, by contrast, accepts on-topic-but-unsupported claims — see docs.)")
    print("\nFinal brief:\n" + brief)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
