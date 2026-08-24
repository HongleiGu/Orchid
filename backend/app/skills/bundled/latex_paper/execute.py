from __future__ import annotations

import asyncio
import shutil

from skill_lib.vault import sanitize_name, vault_dir

MAX_TEX_CHARS = 200_000


async def execute(project: str, filename: str, tex: str, compile: bool = False) -> str:
    try:
        project = sanitize_name(project)
        filename = sanitize_name(filename)
        if not filename.endswith(".tex"):
            filename += ".tex"

        source = (tex or "").strip()
        if not source:
            return "Error: tex must be non-empty."
        if len(source) > MAX_TEX_CHARS:
            return f"Error: tex is too long ({len(source)} chars, max {MAX_TEX_CHARS})."

        vd = vault_dir()
        project_dir = vd / project
        assets_dir = project_dir / "assets"
        project_dir.mkdir(parents=True, exist_ok=True)
        assets_dir.mkdir(exist_ok=True)

        tex_path = project_dir / filename
        tex_path.write_text(source, encoding="utf-8")
        saved = f"Saved LaTeX paper to vault: {project}/{filename} ({len(source)} chars)."

        if not compile:
            return saved

        engine = _find_engine()
        if not engine:
            return saved + " No LaTeX toolchain (tectonic/pdflatex) found in the runner; PDF not built."

        status, detail = await _compile(engine, tex_path, assets_dir)
        return f"{saved} {detail}"
    except Exception as exc:  # noqa: BLE001 - surface as a normal skill error string
        return f"latex_paper failed: {exc}"


def _find_engine() -> str | None:
    for name in ("tectonic", "pdflatex"):
        if shutil.which(name):
            return name
    return None


async def _compile(engine: str, tex_path, assets_dir) -> tuple[str, str]:
    if engine == "tectonic":
        cmd = ["tectonic", "--outdir", str(assets_dir), str(tex_path)]
    else:  # pdflatex
        cmd = ["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
               "-output-directory", str(assets_dir), str(tex_path)]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=150)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return "timeout", "PDF compile timed out after 150s."

    pdf = assets_dir / (tex_path.stem + ".pdf")
    if proc.returncode == 0 and pdf.exists():
        return "ok", f"Compiled PDF: {pdf.parent.name}/{pdf.name}."
    tail = (err_b or out_b).decode("utf-8", errors="replace")[-600:]
    return "error", f"PDF compile failed ({engine}, rc={proc.returncode}): ...{tail}"
