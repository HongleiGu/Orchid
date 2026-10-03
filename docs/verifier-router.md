# Verifier Router — proof-carrying claims

Status: design + prototype · Branch: research · 2026-10-03

A generalization of the evidence contract's Layer 2: instead of sending every
claim to one NLI checker, **route each claim to the strongest verifier it admits**,
and have the claim carry the resulting verification artifact. The verdict is then
typed by *how strongly* it was established — a verification lattice:

    proof (Z3 / Lean)  >  execution (sandbox trace)  >  entailment (NLI span)
                       >  argument acceptability      >  none / abstain

## The router

```
claim ──▶ classify kind
   formal   (arithmetic / logic / math)   ──▶ Z3 / Lean         → proof
   computational ("code returns X")        ──▶ sandbox execute  → trace
   atomic-factual (entity / quantity / date)──▶ retrieval+NER / NLI → span
   argumentative (reasoning over evidence)  ──▶ ARGUMENT VERIFIER → acceptability + graph
   opinion / unverifiable                   ──▶ not graded
```

The router keeps cost proportional to difficulty: cheap claims hit cheap
verifiers; only genuine reasoning claims pay for the argument verifier. Each
claim emits a `ProofCarryingVerdict{kind, verdict, strength, artifact}`, and
aggregation prefers the strongest strength available.

## Why non-formal claims need *argument* decomposition, not atomic facts

Atomic-fact decomposition (FActScore / SAFE / VeriScore) only asks *"is each fact
present in the source?"*. It cannot catch the classic failure **every premise is
true but the conclusion does not follow** — the *warrant* (the inferential link)
is never checked. So for non-formal claims we decompose into an **argument**
(Toulmin) and check three things separately:

1. **Grounds grounded** — each premise is entailed by the evidence (recurses into
   the router; most grounds bottom out as atomic-factual → NLI).
2. **Warrant valid** — does the conclusion *follow from its own grounds*
   (`grounds ⊨ claim`), and is that step not contradicted by the evidence? This is
   the piece atomic checking collapses: it isolates **inference-validity** from
   **fact-grounding**.
3. **Attacks defeated** (Dung) — actively search the evidence for defeaters:
   *undermine* (contradicts a ground), *undercut* (breaks the warrant), *rebut*
   (contradicts the claim). A claim is accepted only if grounds hold, the warrant
   holds, and every attack is itself defeated/absent.

Verdict = Dung grounded-extension check on the small argument graph. The artifact
is the **argument graph** (claim, grounds, warrant, attacks), which is auditable.

## Why this is a step change, not a feature
- **Separates fact-grounding from inference-validity** — the dimension every
  atomic method merges, and the source of "true facts, wrong conclusion" errors.
- **Falsification is first-class** — attacks must be found and defeated to accept,
  turning our Layer-3 invariant into principled argumentation semantics.
- **Typed proof objects** — every claim carries the strongest artifact it earned
  (proof > trace > entailment > argument graph), ordered and auditable.

## Prototype scope (this slice)
- `router.py`: classify a claim's kind and dispatch (formal → existing Z3; else →
  argument / NLI). Thin.
- `argument.py`: the novel core — Toulmin mining (LLM, injectable) + **warrant
  check** (`grounds ⊨ claim`, NLI) + **single-pass rebuttal search** (NLI
  contradiction of claim/ground in the evidence) + acceptability. Single level of
  attacks (no attack-of-attack recursion yet).
- Demonstration target: "true-facts-wrong-conclusion" cases where flat NLI passes
  but the argument verifier rejects on the warrant or an attack.

## Evaluation — going multi-domain (benchmarks to add as plugins)
Current grounding benchmarks (HalluMix/RAGTruth/VeriGray) test fact-grounding, not
warrants. For inference-validity and attacks we want:

- **EntailmentBank** (Dalvi et al.) — annotated *entailment trees* (grounds →
  intermediates → hypothesis); directly tests whether the inference chain is valid.
- **ARCT — Argument Reasoning Comprehension** (Habernal et al.) — literally
  selecting the correct **warrant** for a claim+reason (artifact caveats noted).
- **FOLIO** — NL + first-order-logic reasoning; inference validity, multi-domain;
  also exercises the formal route.
- **δ-NLI / Defeasible-NLI** (Rudinger et al.) — whether added info strengthens or
  weakens an inference → maps directly onto **attacks** (undercut / undermine).

These slot into the existing plugin framework; `EvalItem` extends naturally to
carry grounds/warrant where annotated.

## Risks
- Argument mining + attack search are LLM/retrieval-heavy → the argument verifier
  is the *last* route, only for claims cheaper verifiers can't settle.
- Dung semantics can get heavy; cap at one attack level initially.
- Warrant-via-NLI is a proxy for logical validity; FOLIO/formal route is the
  stronger check where the claim admits it.

Grounding: Toulmin (The Uses of Argument) — claim/grounds/warrant/rebuttal; Dung
1995 — abstract argumentation frameworks + acceptability semantics; argument mining
(Lawrence & Reed) for extraction.
