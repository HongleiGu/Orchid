"""
Skill/tool loader for the skill-runner sandbox.

Scans the shared /packages/node_modules directory for valid packages,
loads their SKILL.md/TOOL.md metadata and execute.py entry points.

Supports:
  - Native format:  SKILL.md + execute.py
  - ClaWHub compat: SKILL.md + index.py (fallback)
  - Scripts dir:    SKILL.md + scripts/execute.py (alternate layout)
"""
from __future__ import annotations

import importlib.util
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

import yaml

logger = logging.getLogger(__name__)

PACKAGES_DIR = Path("/packages/node_modules")
BUNDLED_DIR = Path("/bundled")


@dataclass
class LoadedSkill:
    name: str
    description: str
    parameters: dict
    pkg_type: str  # "skill" | "tool"
    package_dir: Path
    execute_fn: Callable[..., Awaitable[str]]


_loaded: dict[str, LoadedSkill] = {}


def get_loaded() -> dict[str, LoadedSkill]:
    return _loaded


def get_skill(name: str) -> LoadedSkill | None:
    return _loaded.get(name)


def scan_and_load() -> dict[str, LoadedSkill]:
    """Scan bundled + marketplace packages dirs and load all valid skills/tools."""
    _loaded.clear()

    # 1. Load bundled skills (shipped with Orchid)
    if BUNDLED_DIR.exists():
        for skill_dir in sorted(BUNDLED_DIR.iterdir()):
            if not skill_dir.is_dir():
                continue
            try:
                skill = _load_package(skill_dir)
                if skill:
                    _loaded[skill.name] = skill
                    logger.info("Loaded bundled %s %r", skill.pkg_type, skill.name)
            except Exception:
                logger.warning("Failed to load bundled skill from %s", skill_dir, exc_info=True)

    # 2. Load marketplace packages (do NOT override bundled skills)
    bundled_names = set(_loaded.keys())
    if PACKAGES_DIR.exists():
        for pkg_dir in _iter_package_dirs(PACKAGES_DIR):
            try:
                skill = _load_package(pkg_dir)
                if skill:
                    if skill.name in bundled_names:
                        logger.info("Skipping marketplace %r — bundled version takes priority", skill.name)
                        continue
                    _loaded[skill.name] = skill
                    logger.info("Loaded marketplace %s %r", skill.pkg_type, skill.name)
            except Exception:
                logger.warning("Failed to load package from %s", pkg_dir, exc_info=True)

    logger.info("Loaded %d total skills/tools (%s)", len(_loaded), ", ".join(_loaded.keys()) or "none")
    return _loaded


def load_single(pkg_dir: Path) -> LoadedSkill | None:
    """Load a single package (called after install)."""
    skill = _load_package(pkg_dir)
    if skill:
        _loaded[skill.name] = skill
    return skill


def unload(name: str) -> bool:
    """Remove a loaded skill by name."""
    if name in _loaded:
        # Clean up the module from sys.modules
        module_name = f"_pkg_{name}"
        sys.modules.pop(module_name, None)
        del _loaded[name]
        return True
    return False


# ── Internal ──────────────────────────────────────────────────────────────────

def _iter_package_dirs(root: Path):
    """Yield package directories, handling scoped (@org/pkg) and flat layouts."""
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("@"):
            # Scoped package: @org/pkg-name
            for sub in sorted(entry.iterdir()):
                if sub.is_dir():
                    yield sub
        elif not entry.name.startswith("."):
            yield entry


def _load_package(pkg_dir: Path) -> LoadedSkill | None:
    """Attempt to load a single package directory."""
    # Detect type
    skill_md = pkg_dir / "SKILL.md"
    tool_md = pkg_dir / "TOOL.md"

    if skill_md.exists():
        md_path = skill_md
        pkg_type = "skill"
    elif tool_md.exists():
        md_path = tool_md
        pkg_type = "tool"
    else:
        return None  # not a valid Orchid package

    # Find execute entry point
    execute_path = _find_execute(pkg_dir)
    if not execute_path:
        logger.warning("Package %s has %s but no execute entry point", pkg_dir.name, md_path.name)
        return None

    # Parse metadata
    meta = _parse_md(md_path)
    name = meta.get("name") or pkg_dir.name
    description = meta.get("description") or name
    parameters = meta.get("parameters") or {
        "type": "object",
        "properties": {},
        "required": [],
    }

    # Load Python module
    execute_fn = _load_execute(name, execute_path)

    return LoadedSkill(
        name=name,
        description=description,
        parameters=parameters,
        pkg_type=pkg_type,
        package_dir=pkg_dir,
        execute_fn=execute_fn,
    )


def _find_execute(pkg_dir: Path) -> Path | None:
    """Find the execute entry point in priority order."""
    candidates = [
        pkg_dir / "execute.py",           # native
        pkg_dir / "scripts" / "execute.py",  # scripts/ layout
        pkg_dir / "index.py",             # ClaWHub compat
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _parse_md(path: Path) -> dict:
    """Extract YAML frontmatter from SKILL.md / TOOL.md."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        try:
            end = lines.index("---", 1)
            return yaml.safe_load("\n".join(lines[1:end])) or {}
        except (ValueError, yaml.YAMLError):
            pass
    return {}


def _load_execute(name: str, path: Path) -> Callable:
    """Dynamically import execute.py and return its execute function."""
    module_name = f"_pkg_{name}"

    # Clean up previous version if reloading
    sys.modules.pop(module_name, None)

    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    fn = getattr(module, "execute", None)
    if fn is None:
        raise ValueError(f"Package {name}: {path} has no 'execute' function")
    return fn
