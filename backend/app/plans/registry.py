"""Subscription plans (OR-38).

Three layers, each able only to narrow the one above:

    1. ceiling      config    what this deployment may ever do (OR-31, OR-32)
    2. plan         config    what a subscription tier grants
    3. membership   database  which user is on which plan, until when

Plans live in config rather than the database on purpose. Every run consumes
untrusted web content, so an agent talked into misbehaving must have no write
path to the thing restricting it. With plans in config, the worst a compromised
database can do is move a user to a tier that already exists — it cannot invent
capability the deployment never defined.

The narrowing rule is enforced, not merely documented: a plan listing a skill
the ceiling denies does not grant it.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

CATALOG_PATH = Path(__file__).parent / "catalog" / "plans.json"

# In a plan's list, means "everything the ceiling allows".
WILDCARD = "*"


class Plan(BaseModel):
    id: str
    name: str = ""
    description: str = ""
    # ["*"] means every template; otherwise an explicit list of template ids.
    templates: list[str] = Field(default_factory=lambda: [WILDCARD])
    skills: list[str] = Field(default_factory=lambda: [WILDCARD])
    models: list[str] = Field(default_factory=lambda: [WILDCARD])
    # null = the plan imposes no limit of its own. The ceiling and any
    # budget_limits row still apply.
    max_cost_per_day: float | None = None
    max_cost_per_month: float | None = None
    max_runs_per_day: int | None = None


@dataclass(frozen=True)
class EffectivePermissions:
    """What a specific user may actually do, after all three layers."""

    plan_id: str | None
    templates: frozenset[str] | None      # None = unrestricted
    skills: frozenset[str] | None
    models: frozenset[str] | None
    max_cost_per_day: float | None
    max_cost_per_month: float | None
    max_runs_per_day: int | None

    def allows_template(self, template_id: str) -> bool:
        return self.templates is None or template_id in self.templates


class PlanRegistry:
    def __init__(self) -> None:
        self._plans: dict[str, Plan] = {}

    def register(self, plan: Plan) -> None:
        self._plans[plan.id] = plan

    def get(self, plan_id: str | None) -> Plan | None:
        return self._plans.get(plan_id) if plan_id else None

    def all(self) -> list[Plan]:
        return sorted(self._plans.values(), key=lambda p: p.id)

    def ids(self) -> list[str]:
        return sorted(self._plans)

    def clear(self) -> None:
        self._plans.clear()


plan_registry = PlanRegistry()


def load_plans(path: Path | None = None) -> int:
    """Load plan definitions. Returns the count.

    A missing file is not an error: a deployment with no tiers is the normal
    single-customer 私有化部署 case, and everyone then runs at the ceiling.
    """
    path = path or CATALOG_PATH
    if not path.exists():
        logger.info("No plan catalog at %s — every user runs at the ceiling", path)
        return 0

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Plan catalog %s is unreadable (%s) — ignoring it", path, exc)
        return 0

    count = 0
    for entry in raw if isinstance(raw, list) else raw.get("plans", []):
        try:
            plan_registry.register(Plan(**entry))
            count += 1
        except Exception as exc:
            logger.warning("Skipping malformed plan %r: %s", entry, exc)

    logger.info("Loaded %d plan(s): %s", count, ", ".join(plan_registry.ids()))
    return count


def _narrow(
    ceiling: frozenset[str] | None, granted: list[str]
) -> frozenset[str] | None:
    """Intersect a plan's list with the ceiling. A plan can only take away.

    ceiling None means "the deployment does not restrict this", so the plan's
    own list stands. A plan naming something the ceiling denies simply does not
    receive it — the intersection drops it silently, which is the point.
    """
    if WILDCARD in granted:
        return ceiling
    wanted = frozenset(granted)
    return wanted if ceiling is None else wanted & ceiling


def resolve_permissions(plan_id: str | None) -> EffectivePermissions:
    """Combine the deployment ceiling with a plan.

    A user with no plan gets the ceiling unchanged. That keeps existing
    deployments working when plans are introduced, and matches the
    single-customer case where tiers are meaningless. Set PLAN_REQUIRED=true to
    make an unsubscribed user get nothing instead.
    """
    from app.config import get_settings

    settings = get_settings()
    skill_ceiling = settings.skills_allowlist or None
    model_ceiling = settings.models_allowlist or None

    plan = plan_registry.get(plan_id)
    if plan is None:
        return EffectivePermissions(
            plan_id=None,
            templates=None,
            skills=frozenset(skill_ceiling) if skill_ceiling else None,
            models=frozenset(model_ceiling) if model_ceiling else None,
            max_cost_per_day=None,
            max_cost_per_month=None,
            max_runs_per_day=None,
        )

    return EffectivePermissions(
        plan_id=plan.id,
        templates=None if WILDCARD in plan.templates else frozenset(plan.templates),
        skills=_narrow(frozenset(skill_ceiling) if skill_ceiling else None, plan.skills),
        models=_narrow(frozenset(model_ceiling) if model_ceiling else None, plan.models),
        max_cost_per_day=plan.max_cost_per_day,
        max_cost_per_month=plan.max_cost_per_month,
        max_runs_per_day=plan.max_runs_per_day,
    )
