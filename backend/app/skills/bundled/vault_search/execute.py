from __future__ import annotations

from skill_lib.vault import sanitize_name, vault_dir


async def execute(query: str, project: str = "", max_results: int = 10) -> str:
    try:
        query_lower = query.lower()
        results: list[dict] = []
        vd = vault_dir()

        if project:
            p = vd / sanitize_name(project)
            search_dirs = [p] if p.exists() else []
        else:
            search_dirs = [d for d in vd.iterdir() if d.is_dir() and d.name != ".orchid"]

        for proj_dir in search_dirs:
            for md_file in proj_dir.glob("*.md"):
                content = md_file.read_text(encoding="utf-8")
                if query_lower in md_file.stem.lower() or query_lower in content.lower():
                    idx = content.lower().find(query_lower)
                    snippet = ""
                    if idx >= 0:
                        start = max(0, idx - 50)
                        end = min(len(content), idx + len(query) + 100)
                        snippet = content[start:end].replace("\n", " ")
                    results.append({
                        "path": f"{proj_dir.name}/{md_file.name}",
                        "snippet": snippet,
                    })
                if len(results) >= max_results:
                    break

        if not results:
            return f"No vault documents matching '{query}'."

        lines = [f"Found {len(results)} documents matching '{query}':\n"]
        for r in results:
            lines.append(f"- **{r['path']}**")
            if r["snippet"]:
                lines.append(f"  ...{r['snippet']}...")
        return "\n".join(lines)
    except Exception as exc:
        return f"Vault search failed: {exc}"
