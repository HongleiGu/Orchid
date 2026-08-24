---
name: web_reader
description: Fetch one or several web pages and return their readable text with boilerplate (scripts, styles, nav, footers) stripped. Handles Chinese pages encoded as GB18030/GBK as well as UTF-8. Use after web_search or news_feeds to actually read the articles you cite.
timeout: 90
parameters:
  type: object
  properties:
    url:
      type: string
      description: "A single page URL to read."
    urls:
      type: array
      items:
        type: string
      default: []
      description: "Several URLs to read in one call (fetched concurrently). Cheaper than one call per article."
    max_chars:
      type: integer
      default: 6000
      minimum: 500
      maximum: 20000
      description: "Per-page character budget for the extracted text."
  required: []
---

Fetches each URL with a browser-like User-Agent, decodes the body (honouring the
declared charset and falling back to GB18030 for mainland-China pages that
mis-declare it), removes `script`/`style`/`nav`/`header`/`footer`/`aside`
blocks, unescapes entities, collapses whitespace, and returns per-page markdown
sections with the title, final URL, HTTP status and extracted text. Pages that
fail are reported with their error rather than silently dropped, so a caller can
tell "blocked/unreachable" apart from "nothing there".
