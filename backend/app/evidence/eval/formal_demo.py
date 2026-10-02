"""Demo: route math claims to Z3 formal verification (research).

For each claim: heuristic math-router -> (if math) autoformalize to SMT-LIB2 with
the LLM -> Z3 checks validity by refuting the negation -> proof-level verdict.
Non-math claims are left for the NLI layer. Shows proof-level grounding where a
claim is formalisable, honest abstention where it is not.

    python -m app.evidence.eval.formal_demo            # real LLM autoformaliser
    python -m app.evidence.eval.formal_demo --model openrouter/openai/gpt-4o-mini

Needs an LLM key in the environment (OPENROUTER_API_KEY etc.) and the `formal`
extra (z3-solver).
"""
from __future__ import annotations

import argparse
import os
import sys

from app.evidence.formal import Z3Verifier, is_math_claim

CLAIMS = [
    "The sum of two even integers is even",
    "The sum of two odd integers is odd",              # false (it is even)
    "For every integer n, n squared is greater than or equal to zero",
    "For all real x, x squared is greater than or equal to 2 times x minus 1",
    "17 is a prime number",
    "There is no largest prime number",                # true but beyond quantifier-free SMT
    "Users frequently request an offline mode",        # non-math -> NLI, skipped here
]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.evidence.eval.formal_demo")
    ap.add_argument("--model", default=os.getenv("LLM_DEFAULT_MODEL") or "openrouter/openai/gpt-4o-mini")
    args = ap.parse_args(argv)
    z3v = Z3Verifier(model=args.model)
    print(f"formaliser: {args.model}\n")

    for c in CLAIMS:
        math, score = is_math_claim(c, nli=None)
        if not math:
            print(f"[skip→NLI] {c}")
            continue
        r = z3v.verify(c)
        print(f"[{r.verdict.value:11}] {c}")
        if r.formalization:
            print(f"             smt: {r.formalization[:110]}")
        print(f"             {r.detail[:110]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
