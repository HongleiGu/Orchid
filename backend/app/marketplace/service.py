"""
MarketplaceService — handles npm install/uninstall, validation, and
coordination with the skill-runner container.
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.config import get_settings
from app.db.models.package import InstalledPackage
from app.marketplace.validator import ValidationResult, validate_package

logger = logging.getLogger(__name__)

# In Docker: /app/packages (bind-mounted to backend/data/packages)
# Local dev: backend/data/packages
PACKAGES_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "packages"
NODE_MODULES = PACKAGES_DIR / "node_modules"

SKILL_RUNNER_URL = "http://skill-runner:9000"


@dataclass
class InstallResult:
    success: bool
    name: str
    npm_name: str
    pkg_type: str
    version: str
    error: str | None = None


@dataclass
class UninstallResult:
    success: bool
    npm_name: str
    error: str | None = None


class MarketplaceService:
    def __init__(self) -> None:
        self._ensure_packages_dir()

    def _ensure_packages_dir(self) -> None:
        PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
        pkg_json = PACKAGES_DIR / "package.json"
        if not pkg_json.exists():
            pkg_json.write_text(json.dumps({"name": "orchid-packages", "private": True}))

    async def install(self, npm_name: str, db: AsyncSession) -> InstallResult:
        """Install an external skill package via npm. Accepts:
          @author/skill-name        → npm scoped package
          some-npm-package          → npm registry
          file:/path/to/skill       → local path
        Note: @orchid/ skills are bundled and auto-loaded — they don't go through here.
        """
        install_target = npm_name
        registry_name = npm_name

        # Check if already installed
        existing = await db.execute(
            select(InstalledPackage).where(InstalledPackage.npm_name == registry_name)
        )
        if existing.scalar_one_or_none():
            return InstallResult(
                success=False, name="", npm_name=registry_name, pkg_type="", version="",
                error=f"Package {registry_name!r} is already installed",
            )

        # npm install
        try:
            result = subprocess.run(
                ["npm", "install", "--save", "--install-links", install_target],
                cwd=str(PACKAGES_DIR),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                return InstallResult(
                    success=False, name="", npm_name=registry_name, pkg_type="", version="",
                    error=f"npm install failed: {result.stderr.strip()}",
                )
        except FileNotFoundError:
            return InstallResult(
                success=False, name="", npm_name=registry_name, pkg_type="", version="",
                error="npm not found — ensure Node.js is installed in the backend container",
            )
        except subprocess.TimeoutExpired:
            return InstallResult(
                success=False, name="", npm_name=registry_name, pkg_type="", version="",
                error="npm install timed out",
            )

        # Find the installed package directory
        # npm uses the name from package.json, not the install target path
        pkg_dir = self._find_pkg_dir(install_target)
        if not pkg_dir:
            pkg_dir = self._find_latest_pkg()
        if not pkg_dir:
            self._npm_uninstall(install_target)
            return InstallResult(
                success=False, name="", npm_name=registry_name, pkg_type="", version="",
                error=f"Could not locate installed package directory for {registry_name!r}",
            )

        # Validate structure
        validation = validate_package(pkg_dir)
        if not validation.valid:
            self._npm_uninstall(install_target)
            return InstallResult(
                success=False, name=validation.name, npm_name=registry_name,
                pkg_type=validation.pkg_type or "", version="",
                error=validation.error,
            )

        # Read version from package.json
        version = self._read_version(pkg_dir)

        # Install Python deps if requirements.txt exists
        req_txt = pkg_dir / "requirements.txt"
        if req_txt.exists():
            await self._install_python_deps(registry_name, req_txt)

        # Tell skill-runner to reload and register proxy into agent framework
        await self._notify_runner_reload()
        self._register_proxy(registry_name, validation)

        # Save to DB — use registry_name (namespace format) as the key
        pkg = InstalledPackage(
            id=str(ULID()),
            npm_name=registry_name,
            version=version,
            pkg_type=validation.pkg_type or "skill",
            registered_name=validation.name,
            description=validation.description,
            parameters=validation.parameters,
            enabled=True,
        )
        db.add(pkg)
        await db.commit()

        return InstallResult(
            success=True,
            name=validation.name,
            npm_name=registry_name,
            pkg_type=validation.pkg_type or "skill",
            version=version,
        )

    async def uninstall(self, npm_name: str, db: AsyncSession) -> UninstallResult:
        """Uninstall a package."""
        result = await db.execute(
            select(InstalledPackage).where(InstalledPackage.npm_name == npm_name)
        )
        pkg = result.scalar_one_or_none()
        if not pkg:
            return UninstallResult(success=False, npm_name=npm_name, error="Package not installed")

        # Deregister from agent framework (keyed by npm_name)
        self._deregister_proxy(pkg.npm_name, pkg.pkg_type)

        # Tell skill-runner to unload
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(f"{SKILL_RUNNER_URL}/unload/{pkg.registered_name}")
        except Exception as exc:
            logger.warning("Failed to notify skill-runner about unload: %s", exc)

        # npm uninstall
        self._npm_uninstall(npm_name)

        # Remove from DB
        await db.delete(pkg)
        await db.commit()

        return UninstallResult(success=True, npm_name=npm_name)

    async def toggle_enabled(self, npm_name: str, enabled: bool, db: AsyncSession) -> bool:
        """Enable or disable a package without uninstalling."""
        result = await db.execute(
            select(InstalledPackage).where(InstalledPackage.npm_name == npm_name)
        )
        pkg = result.scalar_one_or_none()
        if not pkg:
            return False

        pkg.enabled = enabled
        await db.commit()

        # Reload or unload in skill-runner + register/deregister proxy
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                if enabled:
                    await client.post(f"{SKILL_RUNNER_URL}/reload/{pkg.registered_name}")
                    self._register_proxy_from_pkg(pkg)
                else:
                    await client.post(f"{SKILL_RUNNER_URL}/unload/{pkg.registered_name}")
                    self._deregister_proxy(pkg.npm_name, pkg.pkg_type)
        except Exception as exc:
            logger.warning("Failed to notify skill-runner: %s", exc)

        return True

    async def list_installed(self, db: AsyncSession) -> list[InstalledPackage]:
        result = await db.execute(
            select(InstalledPackage).order_by(InstalledPackage.installed_at.desc())
        )
        return list(result.scalars().all())

    async def get_runner_skills(self) -> list[dict]:
        """Get the list of currently loaded skills from skill-runner."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{SKILL_RUNNER_URL}/list")
                return resp.json()
        except Exception as exc:
            logger.warning("Failed to reach skill-runner: %s", exc)
            return []

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _find_pkg_dir(self, npm_name: str) -> Path | None:
        """Locate the installed package in node_modules."""
        # Handle scoped packages: @org/name → node_modules/@org/name
        candidate = NODE_MODULES / npm_name
        if candidate.exists():
            return candidate
        return None

    def _find_latest_pkg(self) -> Path | None:
        """Scan node_modules for any package with a SKILL.md, TOOL.md, or mcp.json.
        Used as fallback when npm_name doesn't match the directory (e.g. file: installs)."""
        if not NODE_MODULES.exists():
            return None
        for entry in NODE_MODULES.iterdir():
            if entry.name.startswith("."):
                continue
            if entry.name.startswith("@"):
                for sub in entry.iterdir():
                    if sub.is_dir() and _is_orchid_pkg(sub):
                        return sub
            elif entry.is_dir() and _is_orchid_pkg(entry):
                return entry
        return None

    def _read_version(self, pkg_dir: Path) -> str:
        pkg_json = pkg_dir / "package.json"
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text())
                return data.get("version", "unknown")
            except json.JSONDecodeError:
                pass
        return "unknown"

    def _npm_uninstall(self, npm_name: str) -> None:
        try:
            subprocess.run(
                ["npm", "uninstall", npm_name],
                cwd=str(PACKAGES_DIR),
                capture_output=True,
                text=True,
                timeout=60,
            )
        except Exception as exc:
            logger.warning("npm uninstall failed for %s: %s", npm_name, exc)

    async def _install_python_deps(self, npm_name: str, req_path: Path) -> None:
        """Ask skill-runner to install Python deps."""
        rel_path = req_path.relative_to(NODE_MODULES)
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{SKILL_RUNNER_URL}/install-deps",
                    json={"requirements_path": str(rel_path)},
                )
                data = resp.json()
                if data.get("status") != "ok":
                    logger.error("Python deps install failed for %s: %s", npm_name, data)
        except Exception as exc:
            logger.error("Failed to install Python deps for %s: %s", npm_name, exc)

    async def _notify_runner_reload(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(f"{SKILL_RUNNER_URL}/reload")
        except Exception as exc:
            logger.warning("Failed to notify skill-runner reload: %s", exc)

    # ── Proxy registration (bridges skill-runner ↔ agent framework) ───────────
    #
    # Registry key = npm_name (e.g. "orchid-skill-weather", "@scope/tool-x")
    # All Orchid tools/skills use "@orchid/name". External use "@author/name".
    # This guarantees no collision between built-in, local, and marketplace.

    def _register_proxy(self, registry_name: str, validation: ValidationResult) -> None:
        """Register a RemoteSkill into the skill registry.
        Uses registry_name as the lookup key, validation.name as the
        skill-runner execution name."""
        from app.marketplace.proxy import RemoteSkill
        from app.skills.registry import skill_registry

        proxy = RemoteSkill(
            name=registry_name,
            description=validation.description,
            parameters=validation.parameters,
            runner_name=validation.name,
        )
        skill_registry.register(proxy)
        logger.info("Registered RemoteSkill %r → runner:%r", registry_name, validation.name)

    def _register_proxy_from_pkg(self, pkg: InstalledPackage) -> None:
        """Register proxy from an InstalledPackage DB record."""
        from app.marketplace.validator import ValidationResult
        v = ValidationResult(
            valid=True,
            pkg_type=pkg.pkg_type,
            name=pkg.registered_name,
            description=pkg.description,
            parameters=pkg.parameters or {"type": "object", "properties": {}, "required": []},
        )
        self._register_proxy(pkg.npm_name, v)

    def _deregister_proxy(self, npm_name: str, pkg_type: str) -> None:
        """Remove a proxy from the skill registry by its npm_name key."""
        from app.skills.registry import skill_registry
        if skill_registry.deregister(npm_name):
            logger.info("Deregistered RemoteSkill %r", npm_name)

    async def register_all_from_db(self, db: AsyncSession) -> None:
        """Re-register proxies for all enabled packages on startup."""
        packages = await self.list_installed(db)
        enabled = [p for p in packages if p.enabled]

        # Try to get rich metadata from skill-runner
        runner_skills = await self.get_runner_skills()
        runner_map = {s.get("name"): s for s in runner_skills}

        for pkg in enabled:
            runner_info = runner_map.get(pkg.registered_name)
            if runner_info:
                from app.marketplace.validator import ValidationResult
                v = ValidationResult(
                    valid=True,
                    pkg_type=pkg.pkg_type,
                    name=pkg.registered_name,
                    description=runner_info.get("description", pkg.description),
                    parameters=runner_info.get("parameters", {}),
                )
                self._register_proxy(pkg.npm_name, v)
            else:
                self._register_proxy_from_pkg(pkg)

        logger.info("Re-registered %d marketplace proxies from DB", len(enabled))


def _is_orchid_pkg(d: Path) -> bool:
    return (d / "SKILL.md").exists() or (d / "TOOL.md").exists() or (d / "mcp.json").exists()


# Module-level singleton
marketplace = MarketplaceService()
