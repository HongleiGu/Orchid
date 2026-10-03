"""Argument verifier — the non-formal route of the verifier router (research).

Atomic-fact decomposition checks only "is each fact in the source?". It misses the
warrant — whether the conclusion *follows* from its grounds. We decompose a
non-formal claim into a Toulmin argument (claim, grounds, warrant) and check three
things separately against the evidence:

  1. grounds grounded  — each premise is entailed by some evidence passage (NLI);
  2. warrant valid      — grounds |= claim (the inference itself), independent of
                          the evidence; this is what atomic checking cannot do;
  3. attacks defeated   — search the evidence for a rebuttal (contradicts the
                          claim) or an undermine (contradicts a ground); Dung-style
                          acceptability, single level of attacks for now.

A claim is SUPPORTED iff grounds hold AND the warrant holds AND no undefeated
attack. A found rebuttal/undermine makes it REFUTED; otherwise UNSUPPORTED. The
artifact is the argument graph, which is auditable.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

from app.evidence.nli import NLIVerifier
from app.evidence.schema import Claim, EntailmentLabel, Source, Verdict

FLOOR = 0.6


@dataclass
class Argument:
    claim: str
    grounds: list[str] = field(default_factory=list)
    warrant: str = ""


@dataclass
class Attack:
    kind: str          # "rebut" (vs claim) | "undermine" (vs a ground)
    evidence: str
    target: str
    score: float


@dataclass
class ArgumentVerdict:
    verdict: Verdict
    grounds_grounded: list[bool]
    warrant_valid: bool
    attacks: list[Attack]
    argument: Argument

    def graph(self) -> dict:
        return {
            "claim": self.argument.claim,
            "grounds": [{"text": g, "grounded": ok}
                        for g, ok in zip(self.argument.grounds, self.grounds_grounded)],
            "warrant": {"text": self.argument.warrant, "valid": self.warrant_valid},
            "attacks": [{"kind": a.kind, "target": a.target[:80], "evidence": a.evidence[:120]}
                        for a in self.attacks],
            "verdict": self.verdict.value,
        }


# ── Toulmin mining (LLM, injectable) ─────────────────────────────────────────

_PROMPT = (
    "Extract the argument in the CLAIM as a Toulmin structure. Reply with JSON only:"
    ' {{"grounds": ["premise the claim rests on", ...], "warrant": "the inferential'
    ' link from grounds to claim (often implicit)"}}. Grounds are checkable premises;'
    " the warrant is the reasoning step, not a fact.\n\nCLAIM: {claim}\n"
)


class LLMArgumentMiner:
    def __init__(self, model: str, complete_fn: Callable[[str, str], str] | None = None) -> None:
        self.model = model
        self._complete = complete_fn or self._litellm

    def _litellm(self, system: str, user: str) -> str:
        import litellm
        resp = litellm.completion(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.0,
        )
        return resp["choices"][0]["message"]["content"]

    def mine(self, claim: str) -> Argument:
        raw = self._complete("You do argument mining. Reply JSON only.", _PROMPT.format(claim=claim))
        m = re.search(r"\{.*\}", raw or "", re.S)
        if not m:
            return Argument(claim=claim)
        try:
            d = json.loads(m.group(0))
            grounds = [str(g).strip() for g in (d.get("grounds") or []) if str(g).strip()]
            return Argument(claim=claim, grounds=grounds, warrant=str(d.get("warrant", "")).strip())
        except (ValueError, TypeError):
            return Argument(claim=claim)


class StubArgumentMiner:
    """Offline: split the claim on 'because/therefore/so/since' into grounds vs
    claim; no warrant inference. For tests and smoke runs."""

    _SPLIT = re.compile(r"\b(because|since|therefore|so|thus|hence)\b", re.I)

    def mine(self, claim: str) -> Argument:
        parts = self._SPLIT.split(claim)
        if len(parts) >= 3:
            head, _kw, tail = parts[0], parts[1], "".join(parts[2:])
            # "X because Y" -> claim X, ground Y ;  "Y therefore X" -> ground Y, claim X
            if _kw.lower() in {"because", "since"}:
                return Argument(claim=head.strip(" ,."), grounds=[tail.strip(" ,.")])
            return Argument(claim=tail.strip(" ,."), grounds=[head.strip(" ,.")])
        return Argument(claim=claim, grounds=[claim])


# ── verification ─────────────────────────────────────────────────────────────

def _entailed_by_any(nli: NLIVerifier, evidence: list[str], hypothesis: str, floor: float) -> bool:
    for e in evidence:
        label, score = nli.entail(e, hypothesis)
        if label == EntailmentLabel.ENTAIL and score >= floor:
            return True
    return False


def verify_argument(argument: Argument, evidence: list[str], nli: NLIVerifier,
                    floor: float = FLOOR) -> ArgumentVerdict:
    grounds = argument.grounds or [argument.claim]

    # 1. grounds grounded in the evidence
    grounds_ok = [_entailed_by_any(nli, evidence, g, floor) for g in grounds]

    # 2. warrant valid: do the grounds (as premises) entail the claim? (inference
    #    validity, independent of the evidence) — the check atomic methods lack.
    wlabel, wscore = nli.entail(" ".join(grounds), argument.claim)
    warrant_valid = wlabel == EntailmentLabel.ENTAIL and wscore >= floor

    # 3. attacks: evidence that rebuts the claim or undermines a ground
    attacks: list[Attack] = []
    for e in evidence:
        lab, sc = nli.entail(e, argument.claim)
        if lab == EntailmentLabel.CONTRADICT and sc >= floor:
            attacks.append(Attack("rebut", e, argument.claim, sc))
        for g in grounds:
            lg, sg = nli.entail(e, g)
            if lg == EntailmentLabel.CONTRADICT and sg >= floor:
                attacks.append(Attack("undermine", e, g, sg))

    # 4. acceptability (single-level Dung grounded extension)
    if attacks:
        verdict = Verdict.REFUTED
    elif all(grounds_ok) and warrant_valid:
        verdict = Verdict.SUPPORTED
    else:
        verdict = Verdict.UNSUPPORTED
    return ArgumentVerdict(verdict, grounds_ok, warrant_valid, attacks, argument)
