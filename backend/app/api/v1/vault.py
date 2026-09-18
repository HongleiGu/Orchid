"""Vault API — browse, read, download and delete what runs produced.

Layout on disk is flat: VAULT_DIR/<project>/<file>. Subdirectories (a project's
assets/) and hidden entries (the .orchid index) are not part of the browsable
surface.

Every path is resolved through `_resolve`, which is the security boundary of
this module. It previously joined `VAULT_DIR / project / filename` unchecked, so
a project of ".." (sent as %2e%2e) read — and could delete — files outside the
vault (OR-45). Nginx normalising the URL happened to block that at the gateway;
the backend must not depend on it.
"""
from __future__ import annotations

import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.api.schemas import DataResponse
from app.vault import ownership

router = APIRouter(prefix="/vault", tags=["vault"])

VAULT_DIR = Path(os.environ.get("VAULT_DIR", "/app/vault"))

# Readable inline as text. Everything else is served only through /download.
TEXT_SUFFIXES = frozenset({
    ".md", ".markdown", ".txt", ".json", ".csv", ".tsv", ".tex", ".bib",
    ".yaml", ".yml", ".html", ".htm", ".xml", ".log",
})
# A report is kilobytes; anything past this belongs in a download, not a JSON
# body a phone has to parse.
MAX_INLINE_BYTES = 2 * 1024 * 1024


class ProjectInfo(BaseModel):
    name: str
    file_count: int
    total_size: int  # bytes
    modified_at: str | None = None


class FileInfo(BaseModel):
    name: str
    project: str
    size: int
    modified_at: str
    media_type: str
    # Whether GET /projects/{p}/{f} returns it inline. Binary files are
    # download-only.
    is_text: bool


class FileContent(BaseModel):
    name: str
    project: str
    content: str
    size: int
    modified_at: str
    media_type: str


# ── path safety ──────────────────────────────────────────────────────────────

def _check_segment(name: str) -> None:
    """One path segment, as the client sent it. Rejects anything that is not a
    plain name — separators, parent references, hidden entries, NUL."""
    if (
        not name
        or name in {".", ".."}
        or name.startswith(".")
        or "/" in name
        or "\\" in name
        or "\x00" in name
    ):
        raise HTTPException(400, "Invalid name")


def _vault_root() -> Path:
    return VAULT_DIR.resolve()


def _resolve(project: str, filename: str | None = None) -> Path:
    """Resolve a project directory, or a file directly inside one.

    Checks the segments, then checks where the path *actually* lands after
    resolution: that is what catches a symlink planted inside the vault
    pointing out of it. The result must be exactly one level (project) or two
    levels (file) below the vault root — never merely "somewhere under it".
    """
    _check_segment(project)
    if filename is not None:
        _check_segment(filename)

    root = _vault_root()
    target = (root / project / filename) if filename is not None else (root / project)
    try:
        resolved = target.resolve()
    except (OSError, RuntimeError):
        raise HTTPException(400, "Invalid name")

    expected_parent = root / project if filename is not None else root
    if resolved.parent != expected_parent.resolve() or not resolved.is_relative_to(root):
        raise HTTPException(400, "Invalid name")
    return resolved


def _project_dir(project: str) -> Path:
    path = _resolve(project)
    if not path.is_dir():
        raise HTTPException(404, f"Project '{project}' not found")
    return path


def _file(project: str, filename: str) -> Path:
    path = _resolve(project, filename)
    if not path.is_file():
        raise HTTPException(404, f"File not found: {project}/{filename}")
    return path


# ── ownership (OR-48) ─────────────────────────────────────────────────────────
#
# A request with no user identity — an operator's static key, or a deployment
# with auth disabled — sees everything: nothing to scope to. An identified user
# sees only the projects they own; a project they do not own is reported as 404,
# not 403, so the surface does not confirm that another user's project exists.

def _viewer(request: Request) -> str | None:
    return getattr(request.state, "user_id", None)


async def _require_access(request: Request, project: str) -> None:
    viewer = _viewer(request)
    if viewer is None:
        return
    if not await ownership.can_view(project, viewer):
        raise HTTPException(404, f"Project '{project}' not found")


def _entries(project_dir: Path) -> list[Path]:
    """Browsable files in a project: regular, visible, not symlinks."""
    return [
        p for p in project_dir.iterdir()
        if not p.name.startswith(".") and p.is_file() and not p.is_symlink()
    ]


def _mtime(path: Path) -> str:
    # UTC with an explicit offset: a naive timestamp is read as local time by
    # every client that parses it, which in Beijing is eight hours wrong.
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _media_type(path: Path) -> str:
    if path.suffix.lower() in {".md", ".markdown"}:
        return "text/markdown"
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _is_text(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES


# ── routes ───────────────────────────────────────────────────────────────────

@router.get("/projects", response_model=DataResponse[list[ProjectInfo]])
async def list_projects(request: Request):
    root = _vault_root()
    if not root.exists():
        return DataResponse(data=[])

    viewer = _viewer(request)
    owned = None if viewer is None else await ownership.owned_projects_for(viewer)

    projects = []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith(".") or d.is_symlink():
            continue
        if owned is not None and d.name not in owned:
            continue
        files = _entries(d)
        latest = max((f.stat().st_mtime for f in files), default=None)
        projects.append(ProjectInfo(
            name=d.name,
            file_count=len(files),
            total_size=sum(f.stat().st_size for f in files),
            modified_at=datetime.fromtimestamp(latest, tz=timezone.utc).isoformat() if latest else None,
        ))
    return DataResponse(data=projects)


@router.get("/projects/{project}", response_model=DataResponse[list[FileInfo]])
async def list_files(project: str, request: Request):
    await _require_access(request, project)
    project_dir = _project_dir(project)
    files = sorted(_entries(project_dir), key=lambda p: p.stat().st_mtime, reverse=True)
    return DataResponse(data=[
        FileInfo(
            name=f.name,
            project=project,
            size=f.stat().st_size,
            modified_at=_mtime(f),
            media_type=_media_type(f),
            is_text=_is_text(f),
        )
        for f in files
    ])


@router.get("/projects/{project}/{filename}", response_model=DataResponse[FileContent])
async def read_file(project: str, filename: str, request: Request):
    await _require_access(request, project)
    path = _file(project, filename)
    if not _is_text(path):
        raise HTTPException(415, f"{filename} is not a text file — download it instead")
    size = path.stat().st_size
    if size > MAX_INLINE_BYTES:
        raise HTTPException(413, f"{filename} is too large to show inline — download it instead")

    content = path.read_text(encoding="utf-8", errors="replace")
    return DataResponse(data=FileContent(
        name=filename,
        project=project,
        content=content,
        size=size,
        modified_at=_mtime(path),
        media_type=_media_type(path),
    ))


@router.get("/projects/{project}/{filename}/download")
async def download_file(project: str, filename: str, request: Request):
    await _require_access(request, project)
    path = _file(project, filename)
    # RFC 6266 / 5987: the plain filename= form is ASCII-only, and report names
    # are often Chinese. filename* carries the real name; the ASCII fallback is
    # for clients too old to read it.
    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace("?", "_").replace('"', "_")
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"
    return FileResponse(
        path,
        media_type=_media_type(path),
        headers={
            "Content-Disposition": disposition,
            # Authenticated content: never let a shared cache hold it.
            "Cache-Control": "private, no-store",
            # Never let a browser guess a stored .html is a page to render on
            # this origin — where it would run with the console's privileges.
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/projects/{project}/{filename}", status_code=204)
async def delete_file(project: str, filename: str, request: Request):
    await _require_access(request, project)
    _file(project, filename).unlink()
