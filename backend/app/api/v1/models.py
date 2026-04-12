from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter

from app.api.schemas import DataResponse

router = APIRouter(prefix="/models", tags=["models"])


class ModelOut(BaseModel):
    id: str
    provider: str
    tools: bool
    vision: bool
    context: int
    output_tokens: int


@router.get("", response_model=DataResponse[list[ModelOut]])
async def list_models():
    from app.models.registry import get_models
    return DataResponse(data=[
        ModelOut(
            id=m.id, provider=m.provider, tools=m.tools,
            vision=m.vision, context=m.context, output_tokens=m.output_tokens,
        )
        for m in get_models()
    ])
