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
