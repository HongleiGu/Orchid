"""Layer 2 — attribution by NLI entailment (OR-56).

The load-bearing check: a claim is *supported* only if a retrieved source
passage **entails** it — not merely that a citation is present. This is the ALCE
method, and it is done mechanically, upstream of any LLM judge, precisely
because judges accept fabricated citations (authority bias). A small NLI model
is used on purpose: cheap, fast, CPU-viable, and free of the judge's biases.

`NLIVerifier` is the interface. `TransformersNLI` is the real model
(mDeBERTa-v3 XNLI by default — multilingual, so it covers the Chinese + English
mix). `StubNLI` is a deterministic fake so the logic can be tested without
downloading a model or touching a GPU.
"""
from __future__ import annotations

import logging
from typing import Protocol

from app.evidence.schema import EntailmentLabel

logger = logging.getLogger(__name__)

# Multilingual NLI, ~280M, runs on CPU and covers zh (XNLI includes Chinese).
DEFAULT_MODEL = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"


class NLIVerifier(Protocol):
    def entail(self, premise: str, hypothesis: str) -> tuple[EntailmentLabel, float]:
        """Return (label, probability-of-that-label) for premise ⊨ hypothesis."""
        ...


def _label_from_name(name: str) -> EntailmentLabel:
    n = name.lower()
    if "entail" in n:
        return EntailmentLabel.ENTAIL
    if "contradict" in n:
        return EntailmentLabel.CONTRADICT
    return EntailmentLabel.NEUTRAL


class TransformersNLI:
    """Real NLI head. Lazy-loaded so importing this module is cheap and the
    model is only fetched when actually used."""

    def __init__(self, model_name: str = DEFAULT_MODEL, device: str | None = None,
                 max_length: int = 512) -> None:
        self.model_name = model_name
        self.max_length = max_length
        self._device = device
        self._model = None
        self._tokenizer = None
        self._id2label: dict[int, EntailmentLabel] = {}

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        if self._device is None:
            self._device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("Loading NLI model %s on %s", self.model_name, self._device)
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self._model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
        self._model.to(self._device).eval()
        # Read the label order off the model rather than assuming it.
        self._id2label = {i: _label_from_name(l) for i, l in self._model.config.id2label.items()}

    def entail(self, premise: str, hypothesis: str) -> tuple[EntailmentLabel, float]:
        import torch

        self._ensure_loaded()
        inputs = self._tokenizer(
            premise, hypothesis, truncation=True, max_length=self.max_length, return_tensors="pt"
        ).to(self._device)
        with torch.no_grad():
            probs = self._model(**inputs).logits.softmax(dim=-1)[0]
        idx = int(probs.argmax())
        return self._id2label[idx], float(probs[idx])


# Grounding-tuned binary checker (MiniCheck, EMNLP 2024): label 1 = the document
# supports the claim. Trained precisely on "does this doc support this synthesised
# claim", so it is robust to the abstraction/paraphrase/multi-fact cases where a
# generic MNLI model (mDeBERTa) misfires. English-only — keep mDeBERTa for zh.
MINICHECK_MODEL = "lytang/MiniCheck-DeBERTa-v3-Large"


class MiniCheckNLI:
    """MiniCheck head. Binary (supported / not), so it emits ENTAIL or NEUTRAL and
    never CONTRADICT — which also sidesteps the false-refutation failure mode that
    a 3-way MNLI model hits on negation-shaped atoms. Same lazy-load pattern as
    TransformersNLI; loads with the existing deps (sentencepiece for DeBERTa-v3)."""

    def __init__(self, model_name: str = MINICHECK_MODEL, device: str | None = None,
                 max_length: int = 512) -> None:
        self.model_name = model_name
        self.max_length = max_length
        self._device = device
        self._model = None
        self._tokenizer = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        if self._device is None:
            self._device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("Loading MiniCheck model %s on %s", self.model_name, self._device)
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self._model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
        self._model.to(self._device).eval()

    def entail(self, premise: str, hypothesis: str) -> tuple[EntailmentLabel, float]:
        import torch

        self._ensure_loaded()
        # Truncate the document (first segment), keep the whole claim.
        inputs = self._tokenizer(
            premise, hypothesis, truncation="only_first", max_length=self.max_length,
            return_tensors="pt",
        ).to(self._device)
        with torch.no_grad():
            p_support = float(self._model(**inputs).logits.softmax(dim=-1)[0][1])
        if p_support >= 0.5:
            return EntailmentLabel.ENTAIL, p_support
        return EntailmentLabel.NEUTRAL, 1.0 - p_support

    def support_scores(self, premises: list[str], hypothesis: str, batch_size: int = 16) -> list[float]:
        """P(premise supports hypothesis) for each premise, in batched forward
        passes — far faster on CPU than one call per premise."""
        import torch

        self._ensure_loaded()
        out: list[float] = []
        for i in range(0, len(premises), batch_size):
            batch = premises[i:i + batch_size]
            inputs = self._tokenizer(
                batch, [hypothesis] * len(batch), truncation="only_first",
                max_length=self.max_length, padding=True, return_tensors="pt",
            ).to(self._device)
            with torch.no_grad():
                probs = self._model(**inputs).logits.softmax(dim=-1)[:, 1]
            out.extend(float(x) for x in probs)
        return out


class StubNLI:
    """Deterministic NLI for tests. Rules, not a model:

      - hypothesis (claim) is entailed if every one of its content tokens appears
        in the premise — a crude but honest "the source actually says this";
      - explicit negation of an entailed claim ("not"/"无"/"没有") → contradict;
      - otherwise neutral.

    Enough to exercise the aggregation and — crucially — to model a fabricated
    citation: an unrelated premise shares no tokens with the claim, so it lands
    neutral, i.e. NOT supported.
    """

    _NEG = ("not ", "n't", "无", "没有", "并非", "不")

    def entail(self, premise: str, hypothesis: str) -> tuple[EntailmentLabel, float]:
        import re

        def toks(s: str) -> set[str]:
            latin = set(re.findall(r"[A-Za-z0-9]+", s.lower()))
            cjk = set(re.findall(r"[一-鿿]", s))   # per-character for zh
            return latin | cjk

        p, h = toks(premise), toks(hypothesis)
        if not h:
            return EntailmentLabel.NEUTRAL, 1.0
        overlap = len(h & p) / len(h)
        premise_negated = any(neg in premise.lower() for neg in self._NEG)
        hypo_negated = any(neg in hypothesis.lower() for neg in self._NEG)
        if overlap >= 0.8:
            # Source contains the claim's content, but negates it → contradiction.
            if premise_negated and not hypo_negated:
                return EntailmentLabel.CONTRADICT, 0.9
            return EntailmentLabel.ENTAIL, 0.9
        if overlap >= 0.4:
            return EntailmentLabel.NEUTRAL, 0.6
        return EntailmentLabel.NEUTRAL, 0.9
