"""Template catalog (OR-34).

A template is a runnable, curated workflow: identity and presentation, plus the
pipeline that implements it. Templates are the unit a run-only edition offers —
users pick one and fill in its inputs; they never author.

Provisioning is file-based on purpose. Templates ship with the release, so there
is no admin write surface and therefore no attack surface, and updates arrive
the same way a 私有化部署 customer receives any other upgrade.

Inputs are *derived* from the pipeline's task `input_schema` rather than
restated here. That schema already exists and is what the executor actually
reads, so duplicating it in template metadata would create two sources of truth
that drift.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

CATALOG_DIR = Path(__file__).parent / "catalog"


class TemplateInput(BaseModel):
    """One declared input, mirroring the task input_schema entries."""

    name: str
    type: str = "string"
    label: str = ""
    description: str = ""
    default: Any = None
    # Nothing declares this today; an input with no default is treated as
    # required so a catalog UI can mark it.
    required: bool = False


class Template(BaseModel):
    id: str
    name: str
    description: str = ""
    category: str = "general"
    inputs: list[TemplateInput] = Field(default_factory=list)
    # Capability requirements this template declares (OR-40), e.g.
    # "attestation:securities_advisory". Returned to clients on purpose: a UI
    # has to know why a template is locked and what would unlock it. Unmet
    # requirements are enforced server-side at the run gate regardless.
    requires: list[str] = Field(default_factory=list)
    # The implementation. Deliberately excluded from API responses — the
    # workflow is the product, and a run-only customer has no reason to receive
    # the prompts. See OR-35.
    pipeline: dict = Field(default_factory=dict, exclude=True)


def _repo_bases() -> list[Path]:
    """Candidate roots for resolving pipeline_file.

    Anchored on this module, not on the template file, so adding directories
    under catalog/ cannot silently shift the arithmetic.

    This file is <root>/backend/app/templates/registry.py locally, where
    examples/ sits beside backend/ (parents[3]). In the image WORKDIR is /app
    with the app package at /app/app, so the same file is
    /app/app/templates/registry.py and examples/ sits at /app (parents[2]).
    Try both rather than branching on environment.
    """
    here = Path(__file__).resolve()
    return [p for p in (here.parents[2], here.parents[3]) if p.exists()]


def _load_pipeline(spec: dict) -> dict:
    if "pipeline" in spec:
        return spec["pipeline"]

    rel = spec.get("pipeline_file")
    if not rel:
        raise ValueError("template needs either 'pipeline' or 'pipeline_file'")

    tried = []
    for base in _repo_bases():
        candidate = base / rel
        tried.append(str(candidate))
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"pipeline_file not found: {rel} (tried: {'; '.join(tried)})")


def _derive_inputs(pipeline: dict) -> list[TemplateInput]:
    """Read declared inputs off the pipeline's entry task.

    Templates have one entry task by construction; if that changes, the first
    task's schema is still the one a caller parameterises.
    """
    tasks = pipeline.get("tasks") or []
    if not tasks:
        return []

    schema = tasks[0].get("input_schema") or []
    out: list[TemplateInput] = []
    for entry in schema:
        if not isinstance(entry, dict) or "name" not in entry:
            continue
        out.append(TemplateInput(
            name=entry["name"],
            type=entry.get("type", "string"),
            label=entry.get("label", ""),
            description=entry.get("description", ""),
            default=entry.get("default"),
            required=entry.get("required", "default" not in entry),
        ))
    return out


class TemplateRegistry:
    def __init__(self) -> None:
        self._templates: dict[str, Template] = {}

    def register(self, template: Template) -> None:
        self._templates[template.id] = template

    def get(self, template_id: str) -> Template | None:
        return self._templates.get(template_id)

    def all(self) -> list[Template]:
        return sorted(self._templates.values(), key=lambda t: (t.category, t.name))

    def ids(self) -> list[str]:
        return sorted(self._templates)

    def clear(self) -> None:
        self._templates.clear()


template_registry = TemplateRegistry()


def load_templates(directory: Path | None = None) -> int:
    """Load every template JSON in the catalog directory. Returns the count.

    A malformed file is logged and skipped rather than aborting startup: one bad
    template should not take the whole catalog — and therefore the product —
    offline.
    """
    directory = directory or CATALOG_DIR
    if not directory.exists():
        logger.info("No template catalog at %s", directory)
        return 0

    count = 0
    for path in sorted(directory.glob("*.json")):
        try:
            spec = json.loads(path.read_text(encoding="utf-8"))
            pipeline = _load_pipeline(spec)
            template = Template(
                id=spec.get("id") or path.stem,
                name=spec["name"],
                description=spec.get("description", ""),
                category=spec.get("category", "general"),
                inputs=_derive_inputs(pipeline),
                requires=spec.get("requires", []),
                pipeline=pipeline,
            )
            template_registry.register(template)
            count += 1
        except Exception as exc:
            logger.warning("Skipping template %s: %s", path.name, exc)

    logger.info("Loaded %d template(s)", count)
    return count
