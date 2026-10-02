# Formal verification for math claims (research)

Branch: `research/formal-math` · Status: prototype · 2026-10-02

An extension of the evidence contract: where Layer-2 NLI gives *entailment*
grounding, a mathematical claim can be given **proof-level** grounding. Math is
where the academic community is pushing hardest right now (Numina-Lean-Agent's
perfect Putnam-2025 formalization; DeepSeek-Prover-V2, Goedel-Prover-V2, Kimina,
Seed-Prover), and it is the cleanest place to show a verdict that is a *proof*,
not a probability. Research-only for now — not wired into the product.

## Design

```
claim --(NLI router: is this math?)--> formal verifier --> proved | refuted | UNCERTAIN
                                           │
                        ┌──────────────────┴───────────────────┐
                    Z3 / SMT (now)                       Lean (future)
```

- **Router** (`is_math_claim`): the NLI model, zero-shot, entails a "this is a
  precise mathematical claim" hypothesis; a keyword heuristic is the model-free
  fallback. Only math-routed claims reach the formal layer.
- **Z3 engine** (`Z3Verifier`, deployable now): an LLM autoformalizes the claim to
  SMT-LIB2; Z3 checks **validity by refuting the negation** (`unsat` ⇒ the claim is
  a theorem; `sat` ⇒ a counterexample ⇒ refuted; `unknown` ⇒ abstain). Pure pip
  (`z3-solver`), decidable fragments (integer/real arithmetic, bitvectors). The
  VeriFin pattern named in the main design note.
- **Lean engine** (`LeanVerifier`, stub): the Numina-Lean-Agent architecture — a
  general LLM driving the Lean proof assistant over MCP — for claims beyond
  decidable SMT. Heavyweight (Lean + Mathlib, GPU provers); left as a seam.
- **Integration** (`verify_claim_formal`): math-routed → formal; a proved/refuted
  result is authoritative (confidence 1.0) and the formalization is recorded as an
  auditable structured check; otherwise fall back to Layer-2 NLI.

## The safety property (validated)

**The formal layer never fabricates support.** A malformed formalization, an
undecidable problem, or a solver `unknown` all yield UNCERTAIN (abstain), never
SUPPORTED. Demo (`python -m app.evidence.eval.formal_demo`, gpt-4o-mini + Z3):

| claim | verdict |
|---|---|
| sum of two even integers is even | **supported** (proof) |
| ∀ integer n, n² ≥ 0 | **supported** (proof) |
| ∀ real x, x² ≥ 2x − 1 | **supported** (proof; nonlinear, nlsat) |
| sum of two odd integers is odd *(false)* | uncertain — malformed SMT, abstained |
| 17 is prime / no largest prime | uncertain — bad SMT / undecidable here |
| "users want offline mode" | routed to NLI (not math) |

Three genuinely-valid claims proved; the rest abstained; **no false SUPPORTED**,
including on the false claim.

## Limitations (honest)

- **Autoformalization faithfulness** is the real risk: Z3 verifies the *formalized*
  statement, not that the translation matches the English. We record the SMT for
  audit; a back-translation / round-trip check is the next safeguard.
- **Small-model SMT competence**: gpt-4o-mini emitted invalid SMT-LIB2 on ~half the
  claims (quantifier syntax). A parse-repair/retry loop or a stronger formaliser
  (or Kimina/DeepSeek-Prover for Lean) fixes this; the abstain-on-failure property
  means it degrades safely meanwhile.
- **Decidability bounds**: SMT handles arithmetic fragments; induction/infinitude
  (e.g. infinitude of primes) needs the Lean path.

## Next steps

1. SMT parse-repair + round-trip faithfulness check; re-run the demo and report a
   formalization-success rate.
2. A small math-claim eval set (true/false/undecidable) with proof-level
   precision/recall, mirroring the GaRAGe harness.
3. Wire the Lean seam to a Numina-Lean-agent-style MCP tool for claims beyond SMT.
4. Decide product fit separately — this stays on the research branch until then.
