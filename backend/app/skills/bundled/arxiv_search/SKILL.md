---
name: arxiv_search
description: Search arxiv.org for academic papers by keyword and date range. Returns titles, authors, abstracts, and PDF URLs — the actual primary source for AI/ML/science research, not blog posts. Prefer this over web_search for "latest papers on X" questions.
timeout: 60
parameters:
  type: object
  properties:
    query:
      type: string
      description: Free-text search query. Combines title/abstract matching. Quote phrases for exact match.
    max_results:
      type: integer
      default: 10
      description: 1-50.
    year_from:
      type: integer
      description: Optional. Only return papers submitted on or after this year.
    sort_by:
      type: string
      enum: [relevance, submitted_date]
      default: submitted_date
      description: "submitted_date sorts newest first; relevance uses arxiv's ranking."
  required: [query]
---

Hits arxiv's public Atom API at https://export.arxiv.org/api/query. No
key required. Free-tier rate limit is 1 request/3 seconds — call this
sparingly per loop.
