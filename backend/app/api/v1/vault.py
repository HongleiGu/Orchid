"""Vault API — browse, read, and manage markdown documents."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.schemas import DataResponse

router = APIRouter(prefix="/vault", tags=["vault"])

VAULT_DIR = Path(os.environ.get("VAULT_DIR", "/app/vault"))


class ProjectInfo(BaseModel):
    name: str
    file_count: int
    total_size: int  # bytes


class FileInfo(BaseModel):
    name: str
    project: str
    size: int
    modified_at: str


class FileContent(BaseModel):
    name: str
    project: str
    content: str
    size: int
    modified_at: str


@router.get("/projects", response_model=DataResponse[list[ProjectInfo]])
async def list_projects():
    if not VAULT_DIR.exists():
        return DataResponse(data=[])

    projects = []
    for d in sorted(VAULT_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        files = list(d.glob("*.md"))
        total_size = sum(f.stat().st_size for f in files)
        projects.append(ProjectInfo(name=d.name, file_count=len(files), total_size=total_size))
    return DataResponse(data=projects)


@router.get("/projects/{project}", response_model=DataResponse[list[FileInfo]])
async def list_files(project: str):
    project_dir = VAULT_DIR / project
    if not project_dir.exists():
        raise HTTPException(404, f"Project '{project}' not found")

    files = []
    for f in sorted(project_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = f.stat()
        files.append(FileInfo(
            name=f.name,
            project=project,
            size=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(),
        ))
    return DataResponse(data=files)


@router.get("/projects/{project}/{filename}", response_model=DataResponse[FileContent])
async def read_file(project: str, filename: str):
    file_path = VAULT_DIR / project / filename
    if not file_path.exists():
        raise HTTPException(404, f"File not found: {project}/{filename}")

    content = file_path.read_text(encoding="utf-8")
    stat = file_path.stat()
    return DataResponse(data=FileContent(
        name=filename,
        project=project,
        content=content,
        size=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(),
    ))


@router.delete("/projects/{project}/{filename}", status_code=204)
async def delete_file(project: str, filename: str):
    file_path = VAULT_DIR / project / filename
    if not file_path.exists():
        raise HTTPException(404, f"File not found: {project}/{filename}")
    file_path.unlink()
