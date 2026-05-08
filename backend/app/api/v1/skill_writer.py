"""AI-assisted external skill package drafting."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.schemas import DataResponse
from app.config import get_settings
from app.marketplace.validator import validate_package
from app.models.client import model_client

router = APIRouter(prefix="/skill-writer", tags=["skill-writer"])

GENERATED_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "generated-skills"
MAX_FILES = 12
MAX_FILE_BYTES = 200_000


class SkillWriterRequest(BaseModel):
    description: str = Field(..., min_length=1)
    name: str | None = None
    model: str | None = None


class EnvVarSpec(BaseModel):
    name: str
    required: bool = True
    description: str = ""
    example: str = ""


class SkillFile(BaseModel):
    path: str
    content: str


class SkillDraft(BaseModel):
    package_name: str
    skill_name: str
    summary: str = ""
    env_vars: list[EnvVarSpec] = []
    files: list[SkillFile]
    install_notes: list[str] = []
    test_plan: list[str] = []
    questions: list[str] = []
    limitations: list[str] = []


class SaveSkillDraftRequest(BaseModel):
    package_name: str
    files: list[SkillFile]


class SaveSkillDraftResponse(BaseModel):
    package_name: str
    directory: str
    install_target: str
    valid: bool
    validation_error: str | None = None


@router.post("/draft", response_model=DataResponse[SkillDraft])
async def draft_skill(body: SkillWriterRequest):
    description = body.description.strip()
    if not description:
        raise HTTPException(400, "Skill description is required")

    model = body.model or get_settings().llm_default_model
    response = await model_client.complete(
        model=model,
        system=_system_prompt(),
        history=[],
        tools=[],
        user_message=_user_prompt(description, body.name),
    )

    try:
        data = _extract_json_object(response.content)
        draft = _normalise_draft(data)
    except ValueError as exc:
        raise HTTPException(502, f"Model did not return a usable skill draft: {exc}") from exc

    return DataResponse(data=draft)


@router.post("/save", response_model=DataResponse[SaveSkillDraftResponse])
async def save_skill_draft(body: SaveSkillDraftRequest):
    package_name = _safe_package_dir_name(body.package_name)
    if not body.files:
        raise HTTPException(400, "At least one file is required")
    if len(body.files) > MAX_FILES:
        raise HTTPException(400, f"Too many files; max is {MAX_FILES}")

    target_dir = GENERATED_SKILLS_DIR / package_name
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    for file in body.files:
        rel_path = _safe_relative_path(file.path)
        encoded = file.content.encode("utf-8")
        if len(encoded) > MAX_FILE_BYTES:
            raise HTTPException(400, f"File {file.path!r} is too large")
        path = target_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(file.content, encoding="utf-8")

    validation = validate_package(target_dir)
    return DataResponse(data=SaveSkillDraftResponse(
        package_name=package_name,
        directory=str(target_dir),
        install_target=f"file:{target_dir}",
        valid=validation.valid,
        validation_error=validation.error,
    ))


def _system_prompt() -> str:
    return """You are Orchid's Skill Writer.

Your job is to turn a user's integration idea into a complete external Orchid skill package.
An Orchid skill package is loadable when it has SKILL.md at package root and execute.py.

Important product rule:
- Do not ask for credentials directly unless absolutely impossible to draft without them.
- Prefer documenting required env vars in SKILL.md and README.md.
- Skill code must read secrets with os.environ.get("ENV_NAME", "") and return a clear setup error if missing.
- Never include real secrets, fake secrets that look real, or user-specific credentials.

Return ONLY one JSON object with this exact shape:
{
  "package_name": "orchid-skill-example",
  "skill_name": "example",
  "summary": "short explanation",
  "env_vars": [
    {"name": "EXAMPLE_API_KEY", "required": true, "description": "what it unlocks", "example": "set this in .env"}
  ],
  "files": [
    {"path": "package.json", "content": "..."},
    {"path": "SKILL.md", "content": "..."},
    {"path": "execute.py", "content": "..."},
    {"path": "README.md", "content": "..."}
  ],
  "install_notes": ["..."],
  "test_plan": ["..."],
  "questions": [],
  "limitations": ["..."]
}

File requirements:
- package.json must be valid JSON with name, version, private true, and description.
- SKILL.md must contain YAML frontmatter with name, description, timeout, and JSON-schema parameters.
- execute.py must define execute(**kwargs). It may be sync or async. Return a string.
- README.md must be detailed: purpose, env vars, setup, inputs, outputs, manual tests, failure modes, security notes.
- requirements.txt is optional and should list only real Python packages the skill imports beyond stdlib/httpx.

Implementation guidance:
- Use httpx for HTTP calls when a network API is needed.
- Use defensive timeouts.
- Validate required user inputs inside execute.py.
- Keep the code small and auditable.
- Do not write files outside the vault unless the user explicitly asked for a file-writing skill.
- If API details are unknown, still produce a working scaffold where possible and put exact open questions in "questions".
- Use snake_case for skill_name. Use npm-safe lowercase kebab case for package_name.
"""


def _user_prompt(description: str, name: str | None) -> str:
    label = f"\nPreferred skill/package name: {name.strip()}" if name and name.strip() else ""
    return f"""Draft an external Orchid skill package for this request:{label}

{description}
"""


def _extract_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if not text:
        raise ValueError("empty response")

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    elif not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("no JSON object found")
        text = text[start : end + 1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(data, dict):
        raise ValueError("top-level JSON value must be an object")
    return data


def _normalise_draft(data: dict[str, Any]) -> SkillDraft:
    package_name = _normalise_package_name(str(data.get("package_name") or data.get("name") or "orchid-skill-draft"))
    skill_name = _normalise_skill_name(str(data.get("skill_name") or package_name.replace("orchid-skill-", "")))

    files = _normalise_files(data.get("files"), package_name, skill_name)
    draft = SkillDraft(
        package_name=package_name,
        skill_name=skill_name,
        summary=str(data.get("summary") or ""),
        env_vars=_normalise_env_vars(data.get("env_vars")),
        files=files,
        install_notes=_string_list(data.get("install_notes")),
        test_plan=_string_list(data.get("test_plan")),
        questions=_string_list(data.get("questions")),
        limitations=_string_list(data.get("limitations")),
    )
    _ensure_required_files(draft)
    return draft


def _normalise_files(value: Any, package_name: str, skill_name: str) -> list[SkillFile]:
    files: list[SkillFile] = []
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip()
            content = item.get("content")
            if path and isinstance(content, str):
                files.append(SkillFile(path=path, content=content))

    existing = {file.path for file in files}
    if "package.json" not in existing:
        files.insert(0, SkillFile(path="package.json", content=json.dumps({
            "name": package_name,
            "version": "0.1.0",
            "private": True,
            "description": f"Orchid skill package for {skill_name}",
        }, indent=2)))
    return files


def _ensure_required_files(draft: SkillDraft) -> None:
    paths = {file.path for file in draft.files}
    missing = [path for path in ("package.json", "SKILL.md", "execute.py", "README.md") if path not in paths]
    if missing:
        raise ValueError(f"missing required files: {', '.join(missing)}")


def _normalise_env_vars(value: Any) -> list[EnvVarSpec]:
    if not isinstance(value, list):
        return []
    env_vars: list[EnvVarSpec] = []
    for item in value:
        if isinstance(item, str):
            env_vars.append(EnvVarSpec(name=item))
        elif isinstance(item, dict) and item.get("name"):
            env_vars.append(EnvVarSpec(
                name=str(item["name"]),
                required=bool(item.get("required", True)),
                description=str(item.get("description") or ""),
                example=str(item.get("example") or ""),
            ))
    return env_vars


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _normalise_package_name(value: str) -> str:
    name = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    if not name:
        name = "orchid-skill-draft"
    if not name.startswith("orchid-skill-"):
        name = f"orchid-skill-{name}"
    return name[:80]


def _normalise_skill_name(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
    return name[:64] or "draft_skill"


def _safe_package_dir_name(value: str) -> str:
    return _normalise_package_name(value)


def _safe_relative_path(value: str) -> Path:
    if not value or value.startswith("/"):
        raise HTTPException(400, f"Invalid file path {value!r}")
    path = Path(value)
    if any(part in ("", ".", "..") for part in path.parts):
        raise HTTPException(400, f"Invalid file path {value!r}")
    return path
