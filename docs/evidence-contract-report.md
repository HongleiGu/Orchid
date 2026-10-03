# Mechanical Attribution as a Contract

### Routing NLI grounding into agent workflows, and where a judge cannot go

*Orchid evidence-contract technical report · checkpoint · 2026-10-01*

## Abstract

Deep-research agents have a *verification gap*: 11–57% of their citations are
hallucinated, and commercial systems cite sources that do not support their
claims 6–22% of the time. The reflexive fix — ask an LLM "is this well-supported?"
— fails, because LLM judges exhibit **authority bias**: they accept a claim
because a source is *present and on-topic*, not because it *entails* the claim.
We argue citation-checking must instead be **mechanical** (NLI entailment),
**decomposed** (per atomic sub-claim), and **upstream of** any judge. We build
this as a contract check, route it into a real auto-research pipeline, and report
three connected results on the public GaRAGe benchmark (ACL 2025) and in the
pipeline: (1) on human-labelled mis-citations a constrained LLM judge rejects only
**6%** [95% CI 1–10] where mechanical NLI rejects **80%** [70–88] (non-overlapping);
(2) mechanical attribution is a
**tunable precision/recall dial** (from 80%/21% to 34%/74% reject/accept) that the
judge sits off entirely; (3) naive sentence-level grounding *degrades* a research
pipeline, but **decomposition + full-evidence** lifts groundedness to the point the
contract passes, and in the pipeline the judge accepts **92%** of the claims the
NLI gate rejects. Finally we note the boundary of NLI grounding — it checks claim
*content*, not citation *identity* — and add a cheap mechanical check for that.

## 1. The problem

LLM-as-a-judge is the default evaluation and gating pattern. For *attribution* —
does a cited source support the claim — it is the wrong tool. Large-scale work
(*Reliability without Validity*, 2026) finds judges favour answers that carry a
citation **even when the citation is fabricated**, alongside verbosity, position,
and self-enhancement bias and temperature sensitivity (95%→70% same-verdict from
temperature 0→1). Deep-research-agent surveys (arXiv:2506.18096, 2508.12752) and
the citation-hallucination literature (arXiv:2608.05179, 2605.06635, CiteCheck
2605.27700) identify the verification gap as the field's open problem.

Thesis: **citation-checking must be mechanical, decomposed, and upstream of the
judge.** A small NLI model asks the narrow, checkable question — *does THIS passage
entail THIS claim* — and is free of the judge's biases, deterministic, and cheap.

## 2. The evidence contract

A finding is a discrete `Claim{statement, sources[], verdict, confidence}`
(FActScore / SAFE / VeriScore atomic-claim approach). Verification is layered,
cheapest and most reliable first:

1. **deterministic** — numbers, dates, cross-figure consistency (Z3 where needed);
2. **reference (load-bearing)** — NLI entailment of the claim by the retrieved
   passage (the ALCE method);
3. **invariant** — coverage and falsification rules;
4. **judge (constrained)** — relevance/framing only, temperature 0, *never* trusted
   to check citations.

The load-bearing idea is that Layer 2 is mechanical and Layer 4 never checks
citations. For abstractive text a claim is first **decomposed** into atomic,
verifiable sub-claims (opinion dropped); each atom is checked against the **full**
evidence set, and the claim is supported when a configurable fraction of its atoms
are entailed.

Models: NLI = `mDeBERTa-v3-base-mnli-xnli` (multilingual, 3-way) and
`MiniCheck-DeBERTa-v3-Large` (grounding-tuned, binary — it cannot false-refute);
decomposer / writer / judge = `gpt-4o-mini`. All runs CPU, in Docker via `uv`.

## 2.1 Positioning: an agentic gate, not an offline metric

The decompose-then-verify line this builds on — FActScore, SAFE, VeriScore,
DnDScore, MiniCheck, TriQua — is **offline, single-pass evaluation**: a verifier
scores a *fixed* piece of generated text post-hoc and reports a number (with
fine-grained annotations). We route the same mechanical attribution into an
**agentic workflow as a control-flow contract**. That is not a packaging
difference; it changes what the verifier is and what matters about it:

1. **Verdict is a control signal, not a score.** A failing check drives the
   workflow — revise with the ungrounded sentences as feedback, back off to a
   coarser granularity, or abstain/escalate. So *actionability* (which claims
   failed), *determinism*, and *latency* are first-class requirements, not
   reporting niceties.
2. **Evidence is produced in-workflow.** Grounding is against what a cooperating
   retrieval node actually gathered, so a failure is attributable (bad retrieval
   vs. bad writing) and the loop can re-retrieve or re-write — where an offline
   metric is handed a fixed corpus.
3. **The loop mutates the artifact**, which raises concerns an evaluator never
   faces: loop monotonicity (a revise can *regress*, §5 — hence a keep-best
   policy), gaming the checker, and oscillation.
4. **Errors compound downstream.** A biased gate (the LLM judge, §3) does not just
   mis-score — it lets ungrounded content propagate to later nodes and compound.
   "Judges are biased" is a caveat for an evaluator; for a gate it is a
   control-safety property.
5. **Online cost is binding.** The gate runs inline, per node, per retry — so the
   faithfulness round-trip, numeric guard and NLI all have to be cheap (early-exit,
   a sidecar), where offline evaluation can decompose lavishly.

This reframes several "limitations" of the offline line (it measures but cannot
fix; it assumes given evidence) as artifacts of the evaluation setting that the
agentic framing dissolves — while surfacing new problems (loop dynamics,
checker-gaming) that are ours to own.

**We are not first into the agentic setting, and should not claim to be.** Two
neighbouring lines are active. (i) *Contract-gated agent governance* — ToolGate's
Hoare-style pre/postconditions on tool calls, AgentSpec, proof-carrying actions,
provenance guardrails — but these gate *actions, policy and data-flow*, not the
*epistemic status of claims*. (ii) *Externally-grounded verification in loops* —
e.g. work showing self-evaluation in agent loops degenerates to accept-all and
must be replaced by an out-of-band verifier (arXiv:2607.25152), and the common
"external groundedness check, loop fires on fail" RAG pattern — establishing the
*principle* we also rely on. But their external verifier is a world-state oracle
for software-engineering agents (observable test-pass); NLI-as-grounding in agent
runtime verification already exists too. So neither the contract framing, the
external-grounding principle, nor the revise-loop shape is novel.

Our contribution is the **intersection** none of them occupies: mechanical,
*judge-free*, *claim-level* attribution as the external grounding for epistemic
claims — where no world-state oracle exists (research findings, prose), the oracle
is NLI against retrieved evidence, decomposed, faithfulness- and numeric-guarded,
with a **calibrated abstention threshold** — together with the empirical
judge-authority-bias result (§3) that says *why* the external verifier must be
mechanical, and formal routing for math. Others argue "use external grounding"; we
supply the grounding mechanism for claims and show the LLM judge cannot be it.

## 2.2 Related work

**Attribution & citation evaluation.** The decompose-then-verify line —
FActScore (2305.14251), SAFE, VeriScore (2406.19276) — reduces text to atomic
claims and checks each; ALCE (2023) scores citation precision/recall by NLI; AttrScore
and CAQA (2401.14640) frame attribution as a 3-way labelling; MiniCheck (EMNLP 2024,
2404.10774) and LLM-AggreFact give an efficient grounded-factuality checker and
leaderboard; CiteEval (ACL 2025, 2506.01829) argues NLI is a *suboptimal proxy* and
proposes a principle-driven metric. All of these are **offline evaluators** of a
fixed generation — not control-flow gates (§2.1).

**LLM-as-a-judge (un)reliability.** Large-scale evaluation finds authority,
verbosity, position and self-enhancement bias plus temperature sensitivity
(*Reliability without Validity*, 2606.19544); our GaRAGe result (§3) is a sharp,
labelled instance for the citation case specifically.

**Agentic verification & governance.** Contract-gated action governance —
ToolGate (Hoare pre/postconditions on tool calls), proof-carrying agent actions
(2606.04104), provenance guardrails (2606.04990, 2608.12761) — gates *actions and
data-flow*, not claim epistemics. Externally-grounded verification in loops
(2607.25152) establishes the external-beats-self principle via a world-state oracle
for software agents. We occupy the intersection they leave open (§2.1).

**Convergent decompositions.** Concurrent 2026 work independently splits
faithfulness along our exact axis — C2-Faith (ACL 2026) into *causality* (does a
step follow — our warrant) and *coverage* (are inferences present — our grounds),
and LogicReward (2512.18196) into *premise validity* + *logic validity*. We read
this as corroboration of the fact-grounding vs inference-validity separation.

**Neuro-symbolic / formal.** VeriFin (Z3 for financial claims) and NLI-as-theorem-
proving (2025.acl-long.867) formalise then solve; but *logical soundness is not a
reliable criterion* (2604.04177) and LLMs can *game formalization* (2604.19459) —
autoformalization faithfulness, not solving, is the bottleneck. This is why our
formal route is a *faithfulness-gated* option in a router, not a universal method.

## 3. Experiment 1 — judges accept mis-citations (GaRAGe)

GaRAGe (Amazon, ACL 2025) pairs claims with human per-citation labels. We take the
cleanest unit — answer sentences citing exactly one source — and use GaRAGe's own
labels: 88 real mis-citations (`related-only`: on-topic but does **not** support
the claim) and 92 genuine citations.

| on 88 mis-citations / 92 genuine | mis-citations **rejected** (95% CI) | genuine **accepted** |
|---|---|---|
| mechanical NLI (`mDeBERTa`) | **80%** [70–88] | 21% |
| LLM judge (`gpt-4o-mini`) | **6%** [1–10] | 92% |

The rejection CIs are **non-overlapping and far apart** (bootstrap, 2000 resamples
over the fixed 88 mis-citations), so the gap is statistically unambiguous, not a
small-sample artefact. The judge accepts 83/88 on-topic-but-unsupportive citations,
justifying each by the passage's topic ("*Source mentions…*", "*Source
confirms…*") — authority bias, reproduced on real human-labelled data. **The judge
cannot be trusted to check citations.** But naive whole-sentence NLI is over-strict
(21% genuine recall): the two fail as mirror images, which is the case *for* a
layered, tunable contract rather than either method alone.

## 4. Experiment 2 — mechanical attribution is a tunable dial

The same 180-item set, varying model / decomposition / evidence scope:

| configuration | mis-cites rejected | genuine accepted |
|---|---|---|
| `mDeBERTa`, whole-sentence, cited-only | **80%** | 21% |
| `mDeBERTa` + decomposition, cited-only | 75% | 28% |
| `MiniCheck`, whole-sentence, cited-only | 88% | 23% |
| `MiniCheck` + decomposition, cited-only | 44% | 67% |
| `MiniCheck` + decomposition + full-evidence | 34% | **74%** |
| *LLM judge (reference)* | *6%* | *92%* |

Each lever slides one precision/recall frontier monotonically. **The judge sits
off this frontier** (6%/92%) and cannot be dialled toward rejection. The ablation
isolates the dominant lever: both models at whole-sentence are strict and
low-recall (`mDeBERTa` 21%, `MiniCheck` 23%); it is **decomposition**, not the
model swap, that unlocks recall (`MiniCheck` 23%→67%) — the unit of attribution
matters more than the checker. The operating
point is chosen per use: a **citation gate** (keep mis-citations out of a knowledge
store) wants the high-reject end and abstains on the rest; **answer-groundedness**
wants the high-recall end. A caveat specific to GaRAGe: its `related-only` label
means "does not *answer the question*", which diverges from "is the claim
*grounded*"; the two agree on genuine and blatantly-irrelevant citations and
diverge on related-only, so no single point reaches high-reject *and* high-accept
on this benchmark.

## 5. Experiment 3 — routing it into an auto-research pipeline

We add a `grounded` contract check to Orchid's DAG engine: it verifies a writer
node's claims against its upstream (retrieved) evidence by NLI, and feeds the
ungrounded sentences into the existing retry/revise loop. A DRA-shaped workflow
(plan → retrieve → write) has its writer gated by the check.

**Naive wiring fails.** Whole-sentence NLI against raw web-scrape chunks rejects a
legitimately-grounded brief (grounded 25%→0% `mDeBERTa`, ~12% `MiniCheck`) and the
revise loop *degrades* the text — because facts are split across chunks and the
writer synthesises multi-fact sentences spanning them.

**Done right it works.** With decomposition + full-evidence + boilerplate-stripped
passages:

| grounding check | grounded @0 | after 1 revise | contract |
|---|---|---|---|
| naive whole-sentence (`MiniCheck`) | ~12% | — | fail |
| decompose + full-evidence (`MiniCheck`) | **71%** | **86%** | **fail → pass** |

The check flagged unsupported sentences, the writer corrected them, groundedness
rose 71%→86%, and the contract flipped fail→pass — Layer-2 measurably improving the
pipeline.

**Judge gate vs NLI gate, across 6 queries (52 claims).** Scoring every claim both
ways against the same evidence:

| gate | claims grounded |
|---|---|
| NLI (decompose + full-evidence) | 39/52 = **75%** |
| LLM judge (same evidence) | 46/52 = **88%** |

Of the 13 claims the NLI gate rejected, the judge accepted **12 (92%)**: the GaRAGe
authority bias, reproduced in the live pipeline. (The pipeline is unlabelled, so
per-claim ground truth comes from GaRAGe, §3; the pipeline shows the same
disagreement pattern at scale.)

## 6. The boundary — citation identity

NLI grounding verifies claim *content*, not citation *identity*. A writer can state
a supported fact and attribute it to a fabricated source (we observed invented
study names — "JudgeBiasBench", invented authors — in a brief whose *facts* were
grounded). We add a mechanical check: extract the named sources a brief asserts and
flag any absent from the retrieved evidence. It catches the invented names while
clearing the real ones (FairJudge, RAND Corporation), and raised **0** false
positives across the 6-query batch (whose strict writer did not invent names). It
is a safeguard that fires on fabrication and stays quiet otherwise — a layer beyond
NLI, not a replacement.

## 7. Limitations

- **Domain transfer.** Attribution metrics do not transfer across domains
  (arXiv:2606.23915); GaRAGe is web/news, not idea-validation. An outcome store for
  on-domain recalibration is required, not optional.
- **Benchmark label semantics.** GaRAGe's `related-only` ≠ "ungrounded" (§4).
- **Pipeline labels.** §5's gate comparison is unlabelled; ground truth is §3.
- **MiniCheck is English-only** — keep `mDeBERTa` as the zh head for bilingual use.
- **Judge decomposer.** The decomposer is an LLM; it only *extracts* (never sees
  the source, never decides support), so judge bias cannot re-enter — but it adds
  token cost to the check.
- **Checker contamination.** MiniCheck's training evaluation (LLM-AggreFact)
  *includes* RAGTruth/TofuEval, so our checker is not strictly zero-shot on those;
  HalluMix and VeriGray (2025) post-date it and are the clean ones.
- **Sample size.** The external-benchmark numbers (§6-adjacent, design note) are
  small CPU subsamples, single-seed; only the GaRAGe headline (§3) carries CIs.
  Full-set, multi-seed runs need a GPU — a scale, not a method, gap.

## 8. Conclusion

Mechanical, decomposed attribution, upstream of the judge, is the right shape for
citation-checking in agent workflows. It is a tunable precision/recall dial the
judge cannot reach; it improves a real research pipeline once the unit (atoms, full
evidence) matches how writers compose; and its boundary — citation identity — is
itself cheaply checkable. The judge's role is relevance and framing, never
citations.

## Reproducibility

All runs are CPU, in the `Dockerfile.evidence` image via `uv`; models are frozen
(no training). Headline (§3, with CIs):
`python -m app.evidence.eval.run --benchmark garage --limit 180 --judge`
(mDeBERTa NLI + `gpt-4o-mini` judge). Dial (§4): add `--minicheck`, `--decompose`,
`--full-evidence`. Pipeline (§5): `app.evidence.eval.research_grounding` and
`app.evidence.eval.gate_compare`. External benchmarks: the plugin framework
(`app.evidence.eval.benchmark_eval --benchmark {hallumix,ragtruth,verigray}`).
Bootstrap CIs: 2000 resamples over the fixed item set (`run.py:bootstrap_ci`).
Code + full run logs: `docs/evidence-contract.md`.

## References

AFC survey 2108.11896 · VeriScore 2406.19276 · ALCE · MiniCheck (EMNLP 2024)
2404.10774 · GaRAGe (ACL 2025) · Deep Research Agents 2506.18096 / 2508.12752 ·
Verification Gap 2608.05179 · Cited but Not Verified 2605.06635 · CiteCheck
2605.27700 · Reliability without Validity 2606.19544 · Do LLM Attribution Metrics
Transfer 2606.23915 · TriQua 2608.05228 · DnDScore 2412.13175 · CiteEval (ACL 2025)
2506.01829 · C2-Faith (ACL 2026) 2603.05167 · LogicReward 2512.18196 · Logical
Soundness is not a Reliable Criterion 2604.04177 · Do LLMs Game Formalization? 2604.19459.

*Agentic-verification neighbours (positioned against in §2.1):* ToolGate
(contract-gated tool execution) 2026.findings-acl.470 · Proof-Carrying Agent
Actions 2606.04104 · Agent Traces to Trust (provenance) 2606.04990 · Provenance
Integrity 2608.12761 · Externally-grounded verification in agent loops 2607.25152 ·
Reviewer precision ≠ critique uptake 2607.15388.

See `docs/evidence-contract.md` for the full design note and run logs.
