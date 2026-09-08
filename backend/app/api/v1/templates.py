"""Template catalog endpoints (OR-34).

Read-only by design. Templates ship with the release, so there is no create or
update route — and therefore nothing for the run-only profile to have to block.

Responses never include the pipeline. `Template.pipeline` is declared with
exclude=True, so the prompts and agent graph cannot leak through this surface
even if someone later returns the model directly.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.schemas import DataResponse
from app.templates.registry import Template, template_registry

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=DataResponse[list[Template]])
async def list_templates(category: str | None = None):
    """Everything runnable, optionally filtered by category."""
    items = template_registry.all()
    if category:
        items = [t for t in items if t.category == category]
    return DataResponse(data=items)


@router.get("/{template_id}", response_model=DataResponse[Template])
async def get_template(template_id: str):
    template = template_registry.get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template not found: {template_id}")
    return DataResponse(data=template)
