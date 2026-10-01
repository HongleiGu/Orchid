"""Claim decomposition — the step that makes Layer-2 NLI usable on real text.

Abstractive statements ("X is valuable and has revolutionised Y") are a mix of
checkable fact and opinion; a strict entailment model returns *neutral* on the
whole thing, so genuine claims get wrongly rejected (the GaRAGe recall problem).
VeriScore / SAFE / FActScore all fix this the same way: an LLM splits the
statement into atomic, self-contained claims and marks which are *verifiable*
(dropping opinion/judgment); each verifiable atom is then checked separately.

The decomposer only *extracts* — it never sees the source and never decides
support. That is deliberate: the authority/topicality bias we measured in the
judge is a failure of judging a passage, so keeping the passage out of the LLM's
hands here means the bias cannot re-enter. Verification stays mechanical (NLI).
"""
from __future__ import annotations

import json
import re
from typing import Callable, Protocol

from app.evidence.schema import AtomicClaim

_PROMPT = (
    "Break the STATEMENT into atomic, self-contained factual claims. For each, set"
    " verifiable=false if it is opinion, judgment, or vague praise (e.g. 'is"
    " valuable', 'revolutionised', 'important') rather than a checkable fact."
    " Resolve pronouns. Reply with JSON only: a list of"
    ' {{"text": "...", "verifiable": true|false}}.\n\nSTATEMENT: {statement}\n'
)


class Decomposer(Protocol):
    def decompose(self, statement: str) -> list[AtomicClaim]: ...


class LLMDecomposer:
    """VeriScore-style extraction via the project's LLM (litellm), temp 0."""

    def __init__(self, model: str, complete_fn: Callable[[str, str], str] | None = None) -> None:
        self.model = model
        self._complete = complete_fn or self._litellm_complete

    def _litellm_complete(self, system: str, user: str) -> str:
        import litellm

        resp = litellm.completion(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.0,
        )
        return resp["choices"][0]["message"]["content"]

    def decompose(self, statement: str) -> list[AtomicClaim]:
        raw = self._complete(
            "You decompose text into atomic claims. Reply with JSON only.",
            _PROMPT.format(statement=statement),
        )
        atoms = _parse(raw)
        # Never return empty — fall back to the whole statement as one atom.
        return atoms or [AtomicClaim(text=statement, verifiable=True)]


def _parse(raw: str) -> list[AtomicClaim]:
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except (ValueError, TypeError):
        return []
    out = []
    for d in data:
        if isinstance(d, dict) and str(d.get("text", "")).strip():
            out.append(AtomicClaim(text=str(d["text"]).strip(), verifiable=bool(d.get("verifiable", True))))
        elif isinstance(d, str) and d.strip():
            out.append(AtomicClaim(text=d.strip(), verifiable=True))
    return out


_SPLIT = re.compile(r"(?:;|\.\s|\band\b|\bwhich\b|\bwhile\b)", re.I)


class StubDecomposer:
    """Offline, deterministic. Splits on clause boundaries and keeps substantial
    fragments. It does NOT filter opinion (that needs the LLM), so it is for tests
    and smoke runs only — recall measurement uses LLMDecomposer."""

    def decompose(self, statement: str) -> list[AtomicClaim]:
        parts = [p.strip(" ,.;") for p in _SPLIT.split(statement)]
        atoms = [AtomicClaim(text=p, verifiable=True) for p in parts if len(p) >= 15]
        return atoms or [AtomicClaim(text=statement.strip(), verifiable=True)]
