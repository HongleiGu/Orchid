import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Markdown } from "../src/markdown";

const html = (text: string) => renderToStaticMarkup(<Markdown text={text} />);

describe("Markdown (safe, element-only)", () => {
  it("renders headings, bold and inline code", () => {
    const out = html("# 每日简报\n\nThis is **bold** and `code`.");
    expect(out).toContain("<h2");
    expect(out).toContain("每日简报");
    expect(out).toContain("<strong>bold</strong>");
    expect(out).toContain("<code>code</code>");
  });

  it("renders a table with a header and rows", () => {
    const out = html("| 指数 | 涨跌 |\n|---|---|\n| 上证 | +0.3% |\n| 深证 | -0.1% |");
    expect(out).toContain("<table");
    expect(out).toContain("<th>指数</th>");
    expect(out).toContain("<td>上证</td>");
    expect(out).toContain("+0.3%");
  });

  it("renders bulleted and numbered lists", () => {
    expect(html("- one\n- two")).toContain("<ul");
    expect(html("1. first\n2. second")).toContain("<ol");
  });

  it("renders fenced code as a block", () => {
    const out = html("```\nrm -rf /\n```");
    expect(out).toContain("<pre");
    expect(out).toContain("rm -rf /");
  });

  it("neutralises injected HTML — a script becomes text, never a node", () => {
    const out = html("Hello <script>alert('xss')</script> <img src=x onerror=alert(1)>");
    expect(out).not.toContain("<script>");
    expect(out).not.toContain("<img");
    expect(out).toContain("&lt;script&gt;");
    expect(out).toContain("onerror=alert(1)");
  });

  it("shows a markdown link as its text, not a live anchor", () => {
    const out = html("See [the site](https://evil.example).");
    expect(out).not.toContain("<a ");
    expect(out).not.toContain("href");
    expect(out).toContain("the site");
  });
});
