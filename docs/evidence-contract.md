# Evidence Contract — design note

Status: draft · Owner: TBD · Last updated: 2026-09-29

The spine of the **D substrate** (verified-knowledge engine) and therefore of
**C** (idea discovery + validation). It replaces Orchid's current contract —
which checks a run's *shape and process* (`required_sections`, `tool_called`, an
LLM `gate:` verdict) — with one that checks the **epistemic status of every
claim**: is each finding grounded in a real source, how strongly, and what was
*not* found. Vertical workflow packs ("A") are deferred and out of scope here.

This note is written to be citeable: it seeds a possible technical report, so
each design choice names the prior work it rests on (references at the end).

## Why the current contract is insufficient

Today's checks are boolean and about the container, not the contents. For
validation we need claim-level grounding, graded confidence, provenance quality,
active falsification, and forward-checkable predictions. None of those exist yet.

## The claim primitive

Findings become discrete objects, not prose. This is the FActScore / SAFE /
VeriScore atomic-claim approach; VeriScore's refinement — extract only
*verifiable* claims, dropping opinion/judgment — matters because validation prose
mixes the two.

```
Claim {
  id
  statement          # atomic, self-contained
  type               # demand | competition | pricing | feasibility | regulatory | other
  stance             # support | refute        (relative to the thesis under test)
  sources[]          # {url, retrieved_at, published_at, tier(primary|secondary), passage}
  entailment         # per source: {label(entail|neutral|contradict), score}   ← Layer 2
  structured_check   # optional: {kind, passed, detail}                         ← Layer 1
  confidence         # 0..1, aggregated (below)
  verdict            # supported | refuted | unsupported | uncertain
}
```

## Pipeline (adopted from automated fact-checking)

The canonical AFC five-stage shape, not reinvented: **detect → prioritise →
retrieve → verify → verdict** (AFC survey; ClaimCheck; Claim Verification in the
Age of LLMs, 2026).

```
decompose   →  atomic verifiable claims (VeriScore-style extractor; LLM)
retrieve    →  evidence per claim — deliberately BOTH supporting and refuting
verify      →  the four layers below
score       →  per-claim confidence → per-dimension → overall; abstain/escalate
predict     →  emit falsifiable predictions → outcome store → recalibrate
```

## The four verification layers

Cheapest and most reliable first; the LLM judge is last and constrained.

| Layer | Purpose | Technique / model |
|---|---|---|
| **1 — deterministic** | numbers, dates, arithmetic, cross-figure consistency | plain Python; **Z3** only where cross-figure logic needs it (VeriFin pattern) |
| **2 — reference (load-bearing)** | does the cited source actually *support* the claim | **NLI entailment** (ALCE method): claim must be entailed by the retrieved passage, not merely cited |
| **3 — invariant (our addition)** | coverage & falsification | rule checks: every dimension covered or explicitly "no evidence found"; ≥K refuting sources sought per thesis; no market-size/pricing claim without a dated primary source |
| **4 — judge (constrained)** | relevance, "is this framing misleading" | LLM-as-judge, **temp 0, last, never sole, and never trusted to check citations** |

**Why the judge cannot check citations.** Large-scale evaluation finds LLM
judges exhibit **authority bias — they favour answers containing citations even
when the citations are fabricated** — plus verbosity/position/self-enhancement
bias and temperature sensitivity (95%→70% same-verdict from temp 0→1). So
citation checking must be *mechanical* (Layer 2 NLI against a really-retrieved
passage), upstream of and independent from the judge. This inverts the naive
"ask an LLM if it's well-supported" design. (Reliability without Validity, 2026.)

## Concrete model choices (off-the-shelf; validate on our data)

Deliberately small/deterministic where possible — the "small models for
infrastructure" principle — which also keeps the report reproducible and cheap.

- **Claim extraction:** the pipeline's existing LLM (DeepSeek) with a
  VeriScore-style "extract verifiable claims + spans" prompt. Generation-ish;
  a mid model is fine.
- **NLI / entailment (Layer 2):** `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`
  (multilingual zero-shot NLI, ~280M, CPU-viable) as default. Content is
  bilingual (Chinese market + English sources), so a Chinese-tuned NLI
  (CMNLI/OCNLI-finetuned RoBERTa-wwm or ERNIE) is a second head for zh-heavy text.
- **NER (entity grounding):** HanLP or `hfl/chinese-roberta-wwm-ext` for zh,
  spaCy multilingual for en — to align entities across claim and source and
  catch entity drift (小米 the company vs the product).
- **Structured (Layer 1):** Python; Z3 only for cross-figure consistency.
- **Confidence:** aggregate per-claim NLI probability × source tier × corroboration
  count; calibrate (below).

**Caveat that forces the outcome store:** attribution/factuality metrics
**do not transfer across domains** ("Do LLM Attribution Metrics Transfer?",
2026). We must recalibrate on our own labelled data — so the outcome store is
mandatory, not optional.

## Confidence → selective prediction

Confidence is not decorative; it drives **abstention/escalation**. Below a
calibrated threshold the system says "insufficient evidence / needs a human"
rather than asserting — the established selective-prediction pattern, which
reduces hallucination and is measured with **ECE / Brier**. Thresholds are set
against the outcome store, not guessed.

## Outcome store (the flywheel)

Each validation emits ≥1 structured, later-checkable prediction. When reality
lands, the prediction is reconciled → this both **calibrates** the confidence
model and accumulates a proprietary track record no fresh model has. Minimal
from day one.

## Reuse vs. new (against the current codebase)

- **Reuse:** `RunEventType.CONTRACT_CHECK` (emit per-claim results); the
  verifier→critic→reviser loop and bounded DAG loops (retry within budget);
  spans + per-span cost (observability of the verification path); vault
  (evidence store).
- **New:** the Claim schema; Layer-2 NLI service; Layer-3 coverage/falsification
  invariants; confidence aggregation + calibration; the outcome store; connectors
  for real signal.

## Evaluation plan (for the technical report)

1. **Gold set:** ~200–300 claims sampled from our domain (idea-validation /
   market findings), EN + ZH, each labelled `{supported | refuted | unsupported}`
   with gold source spans. Include a subset with **fabricated or mismatched
   citations**.
2. **Metrics:** attribution precision/recall (ALCE-style, NLI-based); veracity
   accuracy; calibration (ECE, Brier); risk–coverage (selective-prediction)
   curve; Layer-3 invariant pass rates.
3. **Headline experiment:** layered evidence contract **vs. an LLM-judge-only
   baseline**, on the fabricated-citation subset — expected result: the judge
   accepts fabricated citations (authority bias) while Layer-2 NLI rejects them.
   Clean, literature-grounded, and directly the report's thesis: *mechanical
   attribution beats judge-based attribution where it counts.*

## First results (2026-09-29)

Layer-2 only, real model (`mDeBERTa-v3-base-mnli-xnli`), 28-item EN+ZH gold set,
run on Linux via `Dockerfile.evidence` (uv):

- **fabricated citations rejected: 9/9 = 100%** — the headline metric
- genuine claims supported: 9/9 = 100%
- overall 3-way verdict accuracy: 26/28 = 93%

The two misses are instructive rather than failures: both near-miss fabrications
(a "*coffee* market reached 15B" passage cited for a "*pet-food* market reached
15B" claim) were labelled **refuted**, not **unsupported** — the model reads
*same number, different subject* as a contradiction. Both still count as "not
supported", so the rejection property holds; it is a labelling nuance to note in
the report, not a leak. Speed: ~1.4 s/item on CPU in Docker.

### LLM-judge baseline (`--judge`, `openrouter/openai/gpt-4o-mini`, 2026-09-30)

The headline comparison — and the expected result **did not reproduce**. An
ordinary judge ("does this source support this claim?", temp 0) scored
**fabricated rejected 9/9 = 100%** and **genuine accepted 9/9 = 100%**, matching
Layer-2 NLI. It even beat NLI on the two near-misses, correctly calling them
*unsupported* with the right reason ("*Source discusses coffee market, not
pet-food market*") where NLI over-fired to *refuted*.

**Honest reading:** on *this* gold set the judge does not exhibit authority bias,
because the fabrications are **blatantly off-topic** (weather for a market claim,
coffee for pet-food) — a capable modern judge catches those. So this set cannot
separate the two methods on accuracy; the bias in the literature needs **harder
fabrications** to surface (on-topic wrong-number, the claim embedded verbatim in
an otherwise-unrelated passage, adversarial phrasing). Building that adversarial
subset is the next step before the report can claim an accuracy gap.

What already holds *regardless* of the accuracy tie, and is the defensible thesis
today: Layer-2 NLI is **deterministic, ~free, and local**, versus the judge's
per-item token cost, latency, and **temperature non-determinism** (95%→70%
same-verdict from temp 0→1, per *Reliability without Validity*). Mechanical
attribution wins on cost, reproducibility and auditability — not (yet, on our
data) on raw accuracy. The report should say exactly that rather than overclaim.

### On a real academic benchmark: GaRAGe (2026-09-30)

The toy set couldn't separate the methods, so we re-ran on **GaRAGe** (Amazon,
ACL 2025) — RAG answers with **human per-citation labels**. We take the cleanest
unit (answer sentences citing exactly one source) and use GaRAGe's own labels:
`ANSWER-THE-QUESTION` → supported; `RELATED-INFORMATION` (on-topic but does *not*
support the claim) / `OUTDATED` / irrelevant → unsupported. No synthetic pairs.
Sample: 88 real mis-citations + 92 genuine; NLI = `mDeBERTa`, judge = `gpt-4o-mini`.

| on GaRAGe | mis-citations **rejected** | genuine **accepted** |
|---|---|---|
| **Layer-2 NLI** | **80%** (70/88) | **21%** (19/92) |
| **LLM judge** | **5%** (4/88) | **90%** (83/92) |

**This is the real result, and it cuts both ways.** The judge's authority /
topicality bias reproduced *hard*: it accepts 84/88 on-topic-but-unsupportive
citations, justifying each by pointing at the passage's topic ("*Source mentions
…*", "*Source confirms …*") — it never checks entailment. That is the case for
never letting the judge check citations.

But **naive full-sentence NLI is too strict**: it wrongly rejects 79% of genuine
citations. The two methods fail as **mirror images** — the judge is credulous
(low precision), this NLI is over-strict (low recall); both land near 49% binary
accuracy on opposite sides. The 100% on the toy set was an artefact of passages
that literally contained the claim.

Diagnosis (checked, not guessed): **not truncation** — only 1% of passages exceed
the model's 512-token limit. The cause is that GaRAGe's genuine "claims" are
*abstractive* answer sentences ("*it has revolutionised …*", "*particularly
valuable …*") that go beyond any single source, so a strict entailment model
returns *neutral*. This is exactly the failure the design's **atomic claim
decomposition** step exists to fix (and why grounding-tuned checkers like
MiniCheck outperform vanilla NLI on real LLM output).

**What this changes for the report.** The thesis is *not* "NLI beats the judge on
accuracy" — it is: **neither method is a verifier alone**, which is the empirical
case *for the layered contract*. Mechanical entailment must be the citation gate
(the judge cannot be trusted there — 5% rejection), but it needs claim
decomposition + a grounding-tuned checker to be usable for recall; the judge is
constrained to relevance/framing, never citations. Next steps this implies:
(1) add the decompose step and re-measure NLI recall; (2) swap in / add a
MiniCheck-style checker as a second Layer-2 head; (3) report precision *and*
recall, never a single accuracy number.

### Decomposition alone is not the recall fix (2026-10-01)

Added VeriScore-style decomposition (an LLM splits the statement into atomic
claims, flags verifiable vs opinion; each verifiable atom is checked by NLI — the
decomposer never sees the source, so judge-bias cannot re-enter). Re-ran the same
180 GaRAGe items:

| | mis-citations rejected | genuine accepted | binary acc |
|---|---|---|---|
| plain NLI | 80% | 21% | 49% |
| **+ decomposition** | 75% | 28% | 51% |

Recall barely moved (21→28%) and rejection slipped (80→75%). A per-atom dump
(`--show-atoms`) explains why — decomposition introduced two *new* failure modes:

1. **Over-aggressive opinion flagging** — the decomposer marks genuine factual
   clauses ("asymptotic solutions provide insights…") as opinion, leaving zero
   verifiable atoms → whole-statement fallback → wrongly unsupported.
2. **One atom flips genuine → refuted** — a multi-fact sentence decomposed against
   a *single* passage yields an atom the passage seems to contradict ("the merger
   *failed*", "Vegas *won* on 2018-10-06", 0.97/0.99), and the "any contradicted
   atom refutes" rule flips the whole claim. Decomposition *created* false
   refutations.
3. **Strict all-atom entailment vs multi-source sentences** — "volatility affects
   bond yields / stock prices / currency" (1/6 entailed): the RAG answer synthesised
   several sources, but we test against only the one cited passage, so most atoms
   cannot be entailed. Structural, not a model error.
   Rejection also slipped because generic atoms ("the company faced challenges") are
   entailed by an on-topic passage → leak.

**Conclusion.** The recipe "decompose + strict/brittle aggregation + a generic
MNLI model" is wrong. The principled fixes, in order of expected payoff:
(a) **aggregation policy** — do not require *all* atoms; do not let a single
mid-confidence "contradict" flip to refuted (treat it as neutral unless strong and
corroborated); score K-of-N against a calibrated threshold. Cheap, no new model.
(b) **test each atom against the full evidence set** for the answer (GaRAGe ships
all grounding passages), not just the one cited passage — the single-passage
restriction artificially caps recall.
(c) **a grounding-tuned checker (MiniCheck)** instead of vanilla mDeBERTa — trained
precisely on "does this document support this synthesised claim", robust to the
abstraction/paraphrase/multi-fact cases where MNLI misfires. New model + Docker
rebuild.
This is itself a report result: it characterises *why* naive mechanical attribution
underperforms and what the engineering actually requires — strengthening the
"carefully layered" thesis over both "just use NLI" and "just use a judge".

### The operating point is a dial, not a winner (2026-10-01)

Implemented all three fixes and measured them against the same GaRAGe items:

| config | mis-cites rejected | genuine accepted | binary acc |
|---|---|---|---|
| plain mDeBERTa, cited-only | **80%** | 21% | 49% |
| mDeBERTa + decompose, cited-only | 75% | 28% | 51% |
| **MiniCheck + decompose, cited-only** | 44% | 67% | **56%** |
| MiniCheck + decompose + full-evidence | 34% | **74%** | 54% |
| *LLM judge (reference)* | *5%* | *90%* | *~49%* |

(Last two framings are the recall-oriented ones; full-evidence = atoms checked
against all grounding passages, ≤5. MiniCheck = `MiniCheck-DeBERTa-v3-Large`,
grounding-tuned, binary so it never false-refutes.)

**The real finding: the contract's operating point is an engineerable dial.** Each
lever — model (mDeBERTa↔MiniCheck), decomposition, `support_fraction`, evidence
scope — slides it monotonically along a precision/recall frontier, from
(80% reject / 21% accept) to (34% / 74%). The LLM judge sits off the useful part
of that frontier entirely, pinned at the credulous extreme (5% / 90%) and
un-dial-able — it cannot be configured to reject mis-citations. That is the
durable result, stronger than any single accuracy number.

**Why no config rejects *and* accepts well on GaRAGe — a measurement-validity
point.** GaRAGe's `related-only` label means "this citation does not *answer the
question*", but our contract asks "is this atomic claim *grounded* in the passage".
On related-only items those diverge: the on-topic passage genuinely does state the
generic atomic facts ("businesses face uncertainty"), so a good grounding checker
*accepts* them — correct by our question, "wrong" by GaRAGe's. The two metrics
agree on genuine and on blatantly-irrelevant citations and diverge precisely on
related-only, which is why the dial cannot reach high-reject + high-accept on this
benchmark. The gate use case (keep fabricated/mismatched citations out of the
substrate) wants the high-reject end; answer-groundedness wants the high-recall
end; both are the same machinery at a different setting.

**What this means for the product.** Pick the operating point per use:
- **citation gate** (default for the substrate): strict mDeBERTa, cited-only,
  `support_fraction`→1.0 — maximise rejection, and route the rest to abstain /
  escalate (selective prediction), never to the judge;
- **answer-groundedness / recall**: MiniCheck + decomposition + full evidence.
Next: calibrate `support_fraction` and the abstention threshold against the outcome
store (OR-60); try finer, question-anchored decomposition to recover related-only
rejection; keep mDeBERTa as the zh head (MiniCheck is English-only).

### Routing Layer-2 into the live pipeline — the same lesson (2026-10-01)

Wired a `grounded` contract check into the DAG engine (OR-58): it verifies a
node's claims against its upstream evidence via Layer-2 NLI and feeds the
ungrounded sentences into the existing retry/revise loop. Added a DRA-shaped
`autonomous-research-grounded` workflow (plan → retrieve → write, writer gated by
the check) and an offline measurement loop (Tavily retrieve → LLM write → NLI
check → revise → re-check).

**Live result: naive wiring does NOT improve the pipeline — it over-rejects.**
On a real research brief (grounded, well-cited), whole-sentence NLI against raw
web chunks scored grounded 25%→0% (mDeBERTa) / 12% (MiniCheck), and the revise
loop *degraded* the text (the writer hedged further from literal entailment).

A `--debug` dump pinned the cause — and it is **not** NLI error:
1. retrieved "sources" are raw web-scrape (nav, "FAQ", "arXiv logo Back to
   arXiv"), chunked into 40 noisy fragments;
2. the supporting facts are present but **split across chunks** ("80% agreement"
   in one, "50% error rates" in another);
3. the writer **synthesises multi-fact sentences spanning chunks/sources**, and
   the check tests each whole sentence against a single 3-sentence chunk — so it
   cannot match even though every sub-fact exists.

This is the GaRAGe lesson reproduced in the pipeline: whole-sentence entailment is
the wrong unit. The fix is the machinery already built — **atomic decomposition**
(check each sub-fact, not the combined sentence) + **full-evidence matching**
(an atom against all chunks, not one window) — plus **cleaner retrieved passages**.

**Upgrade result — done right, Layer-2 does improve the pipeline.** Routing
`verify_claim_decomposed` + full-evidence into the `grounded` check (MiniCheck,
boilerplate stripped from passages), same query:

| grounding check | grounded @0 | after 1 NLI-driven revise | contract |
|---|---|---|---|
| naive whole-sentence (mDeBERTa) | 25% | 0% | fail → fail |
| naive whole-sentence (MiniCheck) | ~12% | — | fail |
| **decompose + full-evidence (MiniCheck)** | **71%** | **86%** | **fail → pass** |

The revise loop now works: the check flagged 2 unsupported sentences, the writer
dropped/fixed them, groundedness rose 71%→86%, and the contract flipped
fail→pass. This is the direct answer to "does NLI improve the pipeline": **yes,
but only with decomposition + full-evidence; the naive sentence-vs-chunk gate
over-rejects and degrades.**

Known limitation (honest): the check grounds *factual content*, not *citation
identity* — the final brief still attributes facts to plausibly-confabulated study
names ("…FairJudge", "…JudgeBiasBench"). Verifying that a named source exists and
is the one that supports the claim is a separate check (citation-identity /
retrieval-match), not NLI entailment. That is the next layer, and it is exactly
the citation-hallucination the deep-research literature flags.

### Shipping the gate: deployment + flywheel (2026-10-02)

The verification research became a deployable product gate. Three pieces:

- **NLI sidecar** (`app/evidence/service.py`, compose `evidence-nli`, profile-gated):
  the backend image stays torch-free; the sidecar loads the model and serves
  `POST /ground`. The `grounded` check routes to `$EVIDENCE_NLI_URL` (httpx) and
  **skips gracefully** if the sidecar is down. The grounding computation is a
  dep-free `app/evidence/grounding.py` shared by both. Verified end-to-end in
  Docker (health up, `/ground` loads mDeBERTa, fabricated claim rejected).
- **Clean retrieval** (`grounding.clean_evidence`): strips scrape boilerplate
  (nav, bylines, dates, markdown chrome) before NLI — the garbage-in that sank
  recall — on by default in `chunk_sources`.
- **Outcome store + calibration** (`app/evidence/outcomes.py`,
  `calibration.py`): every grounding decision records a per-claim
  `(confidence, predicted)` observation (append-only JSONL, `$EVIDENCE_OUTCOME_STORE`);
  reconciling it against reality feeds Brier/ECE and a **suggested abstention
  threshold** (max coverage s.t. selective risk ≤ target). Thresholds are now
  *fit on on-domain data*, not guessed — mandatory because attribution metrics
  don't transfer. View with `python -m app.evidence.eval.calibration_report`.

Still open for full product: L3 invariants, the constrained L4 judge, a zh NLI
head (MiniCheck is English-only), a Postgres outcome-store table (behind the same
interface), reconciliation signal/UI, and the C discover/validate loop.

### Guards that resolve documented failure modes (2026 literature)

Two small checks turn limitations recent work *acknowledges* into guards:

- **Decomposition-faithfulness round-trip (A).** Decompose-then-verify work reports
  the decomposer itself fabricates or over-decontextualizes (e.g. coreference-heavy
  text: ~19% fail to parse, 84% of those invent a different identity). After
  decomposing, each atom must be entailed by the *original statement* (reverse NLI)
  or it is dropped as introduced. When all atoms are dropped (over-fragmented), the
  check **backs off to the whole sentence**, which keeps context — a pragmatic
  2-level granularity pyramid (the full article→chunk→atom pyramid, cf. TriQua, is
  a deferred experiment). `FAITHFUL_FLOOR=0.5`, lenient so only clearly-introduced
  atoms are cut.
- **Numeric guard (B).** NLI is insensitive to single-digit numeric precision
  ("15B" vs "16B") in near-identical context — a documented false-positive source,
  and the exact class of our earlier coffee-vs-pet-food near-miss. A grounded claim
  whose numbers do not appear in the evidence is demoted. Digit-presence only;
  approximate (misses "40%" vs "0.4", unit changes) — refinement deferred.

### Benchmark evaluation as a plugin framework (2026-10-02)

Rigorous evaluation lives in a **plugin framework**, never wired into the runtime
(nothing in `app.core` imports it). A benchmark is a plugin that loads its raw
data and yields a common `EvalItem{claim, context[], gold(faithful), gold_abstain,
task}`; a generic runner (`app/evidence/eval/benchmark_eval.py`) scores items with
any scorer — our grounding checker, plain NLI, an LLM judge, or an offline stub —
and reports hallucination-detection metrics (accuracy, balanced accuracy,
hallucination P/R/F1, AUROC on P(faithful)). New benchmark = new plugin; runner and
metrics unchanged.

Four grounding/hallucination benchmarks are registered (all human-labelled,
reducing to context→claim→faithful): **HalluMix** (`quotientai/HalluMix`),
**RAGTruth** (`ParticleMedia/RAGTruth`), **TofuEval** (`amazon-science/tofueval`),
**VeriGray** (summarization unfaithfulness — its *ambiguous* class maps to
`gold_abstain`, the one set that tests our abstain/UNCERTAIN directly). Loaders are
tolerant to field-name variants; exact formats (esp. VeriGray's source) are
confirmed at fetch time. Framework + loaders tested on synthetic fixtures;
loaders verified against fetched data (HalluMix 6500, RAGTruth 17790, VeriGray 2018).

**First real runs (2026-10-03, MiniCheck whole-sentence, small CPU subsamples):**

| benchmark | n | claim unit | acc | balanced | halluc-F1 | AUROC |
|---|---|---|---|---|---|---|
| HalluMix | 80 | short answer | 64% | 61% | 73% | **0.706** |
| HalluMix (+decompose) | 60 | " | 73% | 73% | — | **0.727** |
| VeriGray | 60 | summary sentence | 45% | 63% | 38% | **0.660** |
| RAGTruth | 50 | full response | 38% | 50% | 49% | **0.462** |

Small, single-seed subsamples (MiniCheck-large is CPU-bound; full/multi-seed is a
GPU follow-up). The pattern is the point and **independently validates two design
choices**: (1) *decomposition* — it lifts HalluMix (0.706->0.727), and RAGTruth
fails *without* it (AUROC 0.462) because the "claim" is a whole multi-sentence
response that no single chunk entails (the decomposition lesson, on external data);
(2) *calibration* — the fixed 0.6 threshold over-flags everywhere (hallucination
recall ~88-93% but low precision / faithful-F1), i.e. real signal
(AUROC > 0.5 where the unit is atomic) at a mis-set operating point — exactly what
the outcome-store threshold fit is for. (TofuEval pending its MediaSum/MeetingBank
doc-join; it ships only doc_ids.)

Infra note: run benchmarks one at a time — a killed `docker run` leaves the
container alive, and stacked zombies split the CPU and starve later runs.

## Open choices

- Validation dimensions — is **demand / competition / willingness-to-pay /
  feasibility / regulatory** the right "worth doing" checklist, or framed
  differently?
- One multilingual NLI head vs. separate en/zh heads.
- How much Z3 is worth it vs. plain arithmetic checks (probably: very little).

## References

- A Survey on Automated Fact-Checking — arXiv:2108.11896
- Claim Verification in the Age of LLMs (survey), ACL SRW 2026 — aclanthology 2026.acl-srw.2
- ClaimCheck: Real-Time Fact-Checking with Small LMs — arXiv:2510.01226
- FActScore — arXiv:2305.14251 · SAFE (long-form factuality) · VeriScore — arXiv:2406.19276
- ALCE (NLI-based citation recall/precision) · attribution frameworks (AIS, AttrScore, RAGAS, CiteEval)
- Do LLM Attribution Metrics Transfer? — arXiv:2606.23915
- VeriFin (neurosymbolic, Z3, financial claims) — arXiv:2608.10213 · VERGE — arXiv:2601.20055
- Logical Soundness is not a Reliable Criterion for Neurosymbolic Fact-Checking — arXiv:2604.04177
- Reliability without Validity: LLM-as-a-Judge at scale — arXiv:2606.19544
- Uncertainty-Based Abstention Improves Safety — arXiv:2404.10960 · selective prediction / calibration (ECE, Brier)
