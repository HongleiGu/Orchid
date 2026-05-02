"""
Tiny markdown → HTML converter for skills that need to embed formatted bodies
(gmail_send, wechat_publish). Two style flavours:

- "email"  — inline styles tuned for email clients
- "wechat" — bare HTML, WeChat applies its own styling
"""
from __future__ import annotations

import re


def looks_like_markdown(text: str) -> bool:
    indicators = [
        r"^#{1,6}\s",       # headers
        r"\*\*.+\*\*",      # bold
        r"^\s*[-*]\s",       # list items
        r"^\s*\d+\.\s",     # numbered lists
        r"\[.+\]\(.+\)",    # links
        r"^>\s",             # blockquotes
        r"```",              # code blocks
        r"^---\s*$",         # horizontal rules
    ]
    for pattern in indicators:
        if re.search(pattern, text, re.MULTILINE):
            return True
    return False


def to_html(md: str, style: str = "email") -> str:
    if style == "wechat":
        return _wechat_html(md)
    return _email_html(md)


def _inline(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


def _wechat_html(content: str) -> str:
    """WeChat draft API accepts HTML — keep it minimal, no inline styles."""
    if "<p>" in content or "<h1>" in content or "<div>" in content:
        return content

    lines = content.split("\n")
    out: list[str] = []
    in_list = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append("<br/>")
            continue
        if stripped.startswith("#### "):
            out.append(f"<h4>{_inline(stripped[5:])}</h4>")
        elif stripped.startswith("### "):
            out.append(f"<h3>{_inline(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            out.append(f"<h2>{_inline(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            out.append(f"<h1>{_inline(stripped[2:])}</h1>")
        elif stripped in ("---", "***", "___"):
            out.append("<hr/>")
        elif stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(stripped[2:])}</li>")
        elif re.match(r"^\d+\.\s", stripped):
            text = re.sub(r"^\d+\.\s", "", stripped)
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(text)}</li>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<p>{_inline(stripped)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def _email_html(md: str) -> str:
    """Inline-styled HTML for email clients."""
    lines = md.split("\n")
    out: list[str] = []
    in_list = False
    in_code = False
    in_blockquote = False

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code:
                out.append("</pre>")
                in_code = False
            else:
                out.append('<pre style="background:#f4f4f4;padding:12px;border-radius:6px;font-size:13px;overflow-x:auto;">')
                in_code = True
            continue
        if in_code:
            out.append(line)
            continue

        if in_list and not (stripped.startswith("- ") or stripped.startswith("* ") or re.match(r"^\d+\.\s", stripped)):
            out.append("</ul>")
            in_list = False
        if in_blockquote and not stripped.startswith("> "):
            out.append("</blockquote>")
            in_blockquote = False

        if not stripped:
            out.append("<br/>")
            continue

        if stripped.startswith("#### "):
            out.append(f'<h4 style="color:#333;margin:16px 0 8px;">{_inline(stripped[5:])}</h4>')
        elif stripped.startswith("### "):
            out.append(f'<h3 style="color:#333;margin:18px 0 8px;">{_inline(stripped[4:])}</h3>')
        elif stripped.startswith("## "):
            out.append(f'<h2 style="color:#222;margin:20px 0 10px;border-bottom:1px solid #eee;padding-bottom:6px;">{_inline(stripped[3:])}</h2>')
        elif stripped.startswith("# "):
            out.append(f'<h1 style="color:#111;margin:24px 0 12px;">{_inline(stripped[2:])}</h1>')
        elif stripped in ("---", "***", "___"):
            out.append('<hr style="border:none;border-top:1px solid #ddd;margin:16px 0;"/>')
        elif stripped.startswith("> "):
            if not in_blockquote:
                out.append('<blockquote style="border-left:3px solid #ddd;padding-left:12px;margin:8px 0;color:#666;">')
                in_blockquote = True
            out.append(f"<p>{_inline(stripped[2:])}</p>")
        elif stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                out.append('<ul style="margin:8px 0;padding-left:20px;">')
                in_list = True
            out.append(f"<li>{_inline(stripped[2:])}</li>")
        elif re.match(r"^\d+\.\s", stripped):
            text = re.sub(r"^\d+\.\s", "", stripped)
            if not in_list:
                out.append('<ul style="margin:8px 0;padding-left:20px;">')
                in_list = True
            out.append(f"<li>{_inline(text)}</li>")
        else:
            out.append(f'<p style="margin:6px 0;line-height:1.6;">{_inline(stripped)}</p>')

    if in_list:
        out.append("</ul>")
    if in_blockquote:
        out.append("</blockquote>")
    if in_code:
        out.append("</pre>")

    body = "\n".join(out)
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:680px;margin:0 auto;padding:20px;color:#333;font-size:15px;line-height:1.6;">
{body}
<hr style="border:none;border-top:1px solid #eee;margin-top:24px;"/>
<p style="font-size:11px;color:#999;">Sent by Orchid AI</p>
</body>
</html>"""
