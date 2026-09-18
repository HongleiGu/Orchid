import type { ReactNode } from "react";

/**
 * A deliberately small markdown renderer that emits React elements, never HTML.
 *
 * Vault content is produced by our own agents, but it summarises untrusted web
 * pages and could carry anything. Under the console's CSP there is no
 * dangerouslySetInnerHTML and no external anything; rendering to elements keeps
 * it that way — a `<script>` or `<img onerror>` in the text becomes literal
 * characters, not a node. This covers what the templates actually emit
 * (headings, tables, lists, code, bold, inline code, links as text); anything
 * unrecognised falls through as plain text, which is the safe direction.
 */

type Inline = ReactNode;

// Bold, inline code, and links — links rendered as their text, since the CSP's
// connect/navigation rules make live links from generated content undesirable.
function inline(text: string, keyBase: string): Inline[] {
  const out: Inline[] = [];
  const pattern = /(\*\*(.+?)\*\*|`([^`]+?)`|\[([^\]]+?)\]\(([^)]+?)\))/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = pattern.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[2] !== undefined) out.push(<strong key={`${keyBase}-b${i}`}>{m[2]}</strong>);
    else if (m[3] !== undefined) out.push(<code key={`${keyBase}-c${i}`}>{m[3]}</code>);
    else if (m[4] !== undefined) out.push(<span key={`${keyBase}-l${i}`} className="md-link">{m[4]}</span>);
    last = m.index + m[0].length;
    i++;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function splitRow(line: string): string[] {
  return line.replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
}

const isDivider = (line: string) => /^\|?[\s:|-]+\|?$/.test(line) && line.includes("-");

export function Markdown({ text }: { text: string }): ReactNode {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i]!;

    // fenced code
    if (line.startsWith("```")) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i]!.startsWith("```")) body.push(lines[i++]!);
      i++; // closing fence
      blocks.push(<pre key={key++} className="md-pre"><code>{body.join("\n")}</code></pre>);
      continue;
    }

    // heading
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      const level = Math.min(heading[1]!.length, 6);
      const Tag = `h${level === 1 ? 2 : level}` as "h2" | "h3" | "h4" | "h5" | "h6";
      blocks.push(<Tag key={key++} className="md-h">{inline(heading[2]!, `h${key}`)}</Tag>);
      i++;
      continue;
    }

    // table: a header row, a divider, then body rows
    if (line.includes("|") && i + 1 < lines.length && isDivider(lines[i + 1]!)) {
      const header = splitRow(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i]!.includes("|") && lines[i]!.trim() !== "") {
        rows.push(splitRow(lines[i]!));
        i++;
      }
      blocks.push(
        <div key={key++} className="md-table-wrap">
          <table className="md-table">
            <thead><tr>{header.map((c, j) => <th key={j}>{inline(c, `th${key}-${j}`)}</th>)}</tr></thead>
            <tbody>
              {rows.map((r, ri) => (
                <tr key={ri}>{header.map((_, ci) => <td key={ci}>{inline(r[ci] ?? "", `td${key}-${ri}-${ci}`)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }

    // list (bulleted or numbered) — a run of consecutive item lines
    if (/^\s*([-*+]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\.\s+/.test(line);
      const items: string[] = [];
      while (i < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[i]!)) {
        items.push(lines[i]!.replace(/^\s*([-*+]|\d+\.)\s+/, ""));
        i++;
      }
      const inner = items.map((it, j) => <li key={j}>{inline(it, `li${key}-${j}`)}</li>);
      blocks.push(ordered ? <ol key={key++} className="md-list">{inner}</ol> : <ul key={key++} className="md-list">{inner}</ul>);
      continue;
    }

    // blank line
    if (line.trim() === "") { i++; continue; }

    // paragraph: gather until a blank line or a block starter
    const para: string[] = [];
    while (
      i < lines.length && lines[i]!.trim() !== "" &&
      !lines[i]!.startsWith("#") && !lines[i]!.startsWith("```") &&
      !/^\s*([-*+]|\d+\.)\s+/.test(lines[i]!) &&
      !(lines[i]!.includes("|") && i + 1 < lines.length && isDivider(lines[i + 1]!))
    ) {
      para.push(lines[i]!);
      i++;
    }
    blocks.push(<p key={key++} className="md-p">{inline(para.join(" "), `p${key}`)}</p>);
  }

  return <div className="md">{blocks}</div>;
}
