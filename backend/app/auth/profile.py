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

    # Runs: list, read, create, and the SSE stream.
    (frozenset({"GET"}), re.compile(r"^/api/v1/runs/?$")),
    (frozenset({"POST"}), re.compile(r"^/api/v1/runs/?$")),
    (frozenset({"GET"}), re.compile(r"^/api/v1/runs/[^/]+/?$")),
    (frozenset({"GET"}), re.compile(r"^/api/v1/runs/[^/]+/(stream|events)/?$")),
    # Cancelling your own run is a normal user action, not authoring.
    (frozenset({"POST"}), re.compile(r"^/api/v1/runs/[^/]+/cancel/?$")),

    # Cost visibility — read-only. Budget *limits* are deployment policy and
    # stay closed.
    (frozenset({"GET"}), re.compile(r"^/api/v1/budget/usage(/.*)?$")),

    # Outputs.
    (frozenset({"GET"}), re.compile(r"^/api/v1/vault(/.*)?$")),

    # Tasks are read-only here: the catalog needs to list what can be run, but
    # creating or editing one is authoring. Tighten to templates once OR-34
    # lands and instantiation stops going through /tasks.
    (frozenset({"GET"}), re.compile(r"^/api/v1/tasks(/[^/]+)?/?$")),
)

# Everything else is refused, including every write to /agents, and all of
# /workflow-maker, /skill-writer, /marketplace, /config and /providers.


def is_request_permitted(method: str, path: str) -> bool:
    return any(method in methods and pattern.match(path) for methods, pattern in _RULES)


def describe_rules() -> Iterable[str]:
    """Human-readable allowlist, for logging at startup."""
    for methods, pattern in _RULES:
        yield f"{','.join(sorted(methods))} {pattern.pattern}"
