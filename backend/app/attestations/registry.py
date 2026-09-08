"""Attestation catalog (OR-40).

A template declares what it requires; a user's record grants it. The template
that produces buy/sell calls declares `attestation:securities_advisory`, and is
simply not runnable — enforced server-side — for a user with no such record.

The split mirrors plans (OR-38), for the same reason and one more:

    text of the attestation   config     what the user is agreeing to
    record of acceptance      database   who agreed, to which version, when

The text is a release artifact: it is reviewed, versioned, and shipped, and an
agent that has read untrusted web content must have no path to rewriting what
users are asked to agree to. The record is evidentiary and belongs in the
database, because it is a fact about a person rather than a statement of policy.

Version and content hash are both stored on acceptance. Version is what a
person reasons about; the hash is what catches the case nobody means to create,
where the text is edited without bumping the version — at which point every
prior acceptance covers wording that no longer exists, and is treated as stale.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

CATALOG_PATH = Path(__file__).parent / "catalog" / "attestations.json"

# The one requirement scheme understood today. Anything else in a template's
# `requires` is unsatisfiable rather than ignored — see service.unmet_requirements.
REQUIREMENT_SCHEME = "attestation"


class Attestation(BaseModel):
    id: str
    title: str
    # Shown next to the checkbox; the full text is what is actually agreed to.
    summary: str = ""
    text: str
    # Bump this whenever `text` changes in substance. Doing so invalidates every
    # prior acceptance, which is the intended effect: consent is to a wording.
    version: str = "1"
    locale: str = "zh-CN"
    # Free-form, for the operator's own record — the statute or rule this exists
    # to satisfy. Never interpreted by the code.
    basis: str = ""
    requirement: str = Field(default="", exclude=True)

    def model_post_init(self, _context) -> None:
        object.__setattr__(self, "requirement", f"{REQUIREMENT_SCHEME}:{self.id}")

    @property
    def content_hash(self) -> str:
        """SHA-256 of the exact text. Stored with each acceptance so that an
        edit which skips the version bump is detectable rather than silent."""
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


class AttestationRegistry:
    def __init__(self) -> None:
        self._items: dict[str, Attestation] = {}

    def register(self, attestation: Attestation) -> None:
        self._items[attestation.id] = attestation

    def get(self, attestation_id: str | None) -> Attestation | None:
        return self._items.get(attestation_id) if attestation_id else None

    def all(self) -> list[Attestation]:
        return sorted(self._items.values(), key=lambda a: a.id)

    def ids(self) -> list[str]:
        return sorted(self._items)

    def clear(self) -> None:
        self._items.clear()


attestation_registry = AttestationRegistry()


def load_attestations(path: Path | None = None) -> int:
    """Load the attestation catalog. Returns the count.

    A missing file is not an error — a deployment whose templates require
    nothing needs no catalog. A *malformed* one is also not fatal, but it is
    not permissive either: templates requiring an attestation that failed to
    load stay unrunnable, because unmet_requirements cannot find it.
    """
    path = path or CATALOG_PATH
    if not path.exists():
        logger.info("No attestation catalog at %s", path)
        return 0

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Attestation catalog %s is unreadable (%s) — ignoring it", path, exc)
        return 0

    count = 0
    for entry in raw if isinstance(raw, list) else raw.get("attestations", []):
        try:
            attestation_registry.register(Attestation(**entry))
            count += 1
        except Exception as exc:
            logger.warning("Skipping malformed attestation %r: %s", entry, exc)

    logger.info("Loaded %d attestation(s): %s", count, ", ".join(attestation_registry.ids()))
    return count
