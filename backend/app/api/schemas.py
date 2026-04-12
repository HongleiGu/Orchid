"""Shared Pydantic response/request schemas."""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class DataResponse(BaseModel, Generic[T]):
    data: T


class PageMeta(BaseModel):
    page: int
    page_size: int
    total: int


class PageResponse(BaseModel, Generic[T]):
    data: list[T]
    meta: PageMeta


class ErrorDetail(BaseModel):
    message: str
    code: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
