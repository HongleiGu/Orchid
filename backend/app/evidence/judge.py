"""LLM-as-judge attribution — the baseline the evidence contract is measured against.

This is deliberately an *ordinary, fair* judge, not a crippled one: it is asked
the plain question a naive design would ask — "does this source support this
claim?" — at temperature 0, and returns a verdict plus a brief reason. The point
of the eval is to show that even a fair judge accepts fabricated citations
(authority bias) where mechanical NLI (Layer 2) rejects them. Crippling the
prompt would make that comparison dishonest.

The reason field is required, short, and load-bearing: on a fabricated citation
the judge typically justifies itself by pointing at the passage's authority
("cites a 2025 report with the figure") — which is exactly the failure mode.

Not used in production verification. It exists so the report can quantify the gap.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)

_PROMPT = (
    "You are checking whether a SOURCE supports a CLAIM.\n"
    "Answer only with JSON: {{\"supported\": true|false, \"reason\": \"<15 words max>\"}}.\n\n"
    "CLAIM: {claim}\n\nSOURCE: {passage}\n"
)


@dataclass
class JudgeVerdict:
    supported: bool
    reason: str


class LLMJudge:
    def __init__(self, model: str, complete_fn: Callable[[str, str], str] | None = None,
                 temperature: float = 0.0) -> None:
        self.model = model
        self.temperature = temperature
        self._complete = complete_fn or self._litellm_complete

    def _litellm_complete(self, system: str, user: str) -> str:
        import litellm

        resp = litellm.completion(
            model=self.model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=self.temperature,
        )
        return resp["choices"][0]["message"]["content"]

    def judge(self, claim: str, passage: str) -> JudgeVerdict:
        raw = self._complete(
            "You are a careful fact-checking assistant. Reply with JSON only.",
            _PROMPT.format(claim=claim, passage=passage),
        )
        return _parse(raw)


def _parse(raw: str) -> JudgeVerdict:
    """Tolerant parse: pull the first JSON object; fall back to a yes/no scan."""
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        try:
            d = json.loads(m.group(0))
            return JudgeVerdict(bool(d.get("supported")), str(d.get("reason", ""))[:200])
        except (ValueError, TypeError):
            pass
    low = raw.lower()
    supported = ("true" in low or "yes" in low) and "false" not in low[:40]
    return JudgeVerdict(supported, raw.strip()[:200])


class StubJudge:
    """For tests only. Models the authority bias the literature reports: it
    treats the mere presence of a substantive, authoritative-sounding source as
    support — which is exactly the mistake the eval is designed to catch."""

    _AUTHORITY = ("report", "study", "survey", "according", "报告", "调查", "研究", "白皮书")

    def judge(self, claim: str, passage: str) -> JudgeVerdict:
        low = passage.lower()
        if any(a in low for a in self._AUTHORITY) or re.search(r"\d", passage):
            return JudgeVerdict(True, "source looks authoritative (cites data/report)")
        return JudgeVerdict(False, "no clear supporting source")
