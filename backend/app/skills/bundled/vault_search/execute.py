from __future__ import annotations

import re

from skill_lib.vault import sanitize_name, vault_dir


async def execute(query: str, project: str = "", max_results: int = 10) -> str:
    try:
        query_lower = query.lower()
        tokens = _tokens(query_lower)
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
                content_lower = content.lower()
                stem_lower = md_file.stem.lower()
                score = _score(query_lower, tokens, stem_lower, content_lower)
                if score > 0:
                    idx = _first_match_index(query_lower, tokens, content_lower)
                    snippet = ""
                    if idx >= 0:
                        start = max(0, idx - 50)
                        end = min(len(content), idx + max(len(query), 40) + 100)
                        snippet = content[start:end].replace("\n", " ")
                    results.append({
                        "path": f"{proj_dir.name}/{md_file.name}",
                        "snippet": snippet,
                        "score": score,
                    })

        if not results:
            return f"No vault documents matching '{query}'."

        results.sort(key=lambda r: (-r["score"], r["path"]))
        results = results[:max_results]

        lines = [f"Found {len(results)} documents matching '{query}':\n"]
        for r in results:
            lines.append(f"- **{r['path']}**")
            if r["snippet"]:
                lines.append(f"  ...{r['snippet']}...")
        return "\n".join(lines)
    except Exception as exc:
        return f"Vault search failed: {exc}"


def _tokens(query: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9][a-z0-9_.-]*", query.lower()) if len(t) >= 2]


def _score(query: str, tokens: list[str], stem: str, content: str) -> int:
    score = 0
    if query and query in stem:
        score += 30
    if query and query in content:
        score += 20
    for token in tokens:
        if token in stem:
            score += 5
        if token in content:
            score += 1
    if tokens and not any(token in stem or token in content for token in tokens):
        return 0
    return score


def _first_match_index(query: str, tokens: list[str], content: str) -> int:
    if query:
        idx = content.find(query)
        if idx >= 0:
            return idx
    matches = [content.find(token) for token in tokens if content.find(token) >= 0]
    return min(matches) if matches else -1
