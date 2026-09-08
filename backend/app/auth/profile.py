"""API surface allowlist for the locked-down run-only profile (OR-30).

Deny-by-default, deliberately. A denylist fails open: block /agents,
/workflow-maker and /skill-writer today, and the endpoint someone adds next
month is reachable until a person remembers this file exists. With an
allowlist, a new route is closed until it is explicitly opened — the failure
mode is a bug report rather than a breach.

This is one middleware rather than per-route dependencies because every router
mounts under a single prefix in main.py, so there is one place to audit and no
way to forget a route.

Note this is a *capability* boundary, not an entitlement one. It says what this
deployment can do at all, and per-user entitlements (OR-38) layer on top and
may only narrow it further.
"""
from __future__ import annotations

import re
from typing import Iterable

# (allowed methods, compiled path pattern). Anything unmatched is refused.
_RULES: tuple[tuple[frozenset[str], re.Pattern[str]], ...] = (
    # The catalog: what a run-only edition is for. Read-only, and responses
    # never include the pipeline.
    (frozenset({"GET"}), re.compile(r"^/api/v1/templates/?$")),
    (frozenset({"GET"}), re.compile(r"^/api/v1/templates/[^/]+/?$")),

    # Starting a run. This is the *only* entry point, which is what makes "what
    # may run" identical to "what shipped in the catalog" — /tasks/{id}/trigger
    # stays denied, so an arbitrary task cannot be run even if one exists.
    (frozenset({"POST"}), re.compile(r"^/api/v1/templates/[^/]+/run/?$")),

    # Runs: list, read, cancel, and the SSE stream. No create — see above.
    (frozenset({"GET"}), re.compile(r"^/api/v1/runs/?$")),
    (frozenset({"GET"}), re.compile(r"^/api/v1/runs/[^/]+/?$")),
    (frozenset({"GET"}), re.compile(r"^/api/v1/runs/[^/]+/(stream|events)/?$")),
    # Cancelling your own run is a normal user action, not authoring.
    (frozenset({"POST"}), re.compile(r"^/api/v1/runs/[^/]+/cancel/?$")),

    # Cost visibility — read-only. Budget *limits* are deployment policy and
    # stay closed.
    (frozenset({"GET"}), re.compile(r"^/api/v1/budget/usage(/.*)?$")),

    # Outputs.
    (frozenset({"GET"}), re.compile(r"^/api/v1/vault(/.*)?$")),

    # Attestations (OR-40). The only write a run-only user may make, and not an
    # exception to the rule: it appends a record of their own act, about
    # themselves — the same category as cancelling their own run. A template
    # gated on an attestation is unusable without it, since the design is that
    # the user reads the text and agrees. The text stays read-only; it is config.
    (frozenset({"GET"}), re.compile(r"^/api/v1/attestations/?$")),
    (frozenset({"POST"}), re.compile(r"^/api/v1/attestations/[^/]+/(accept|withdraw)/?$")),
)

# /tasks is deliberately absent. It was allowed read-only while templates did
# not exist; now the catalog serves that purpose, and task names and
# descriptions are workflow internals a run-only customer has no need for.

# Everything else is refused, including every write to /agents, and all of
# /workflow-maker, /skill-writer, /marketplace, /config and /providers.


def is_request_permitted(method: str, path: str) -> bool:
    return any(method in methods and pattern.match(path) for methods, pattern in _RULES)


def describe_rules() -> Iterable[str]:
    """Human-readable allowlist, for logging at startup."""
    for methods, pattern in _RULES:
        yield f"{','.join(sorted(methods))} {pattern.pattern}"
