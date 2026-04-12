---
name: research_radar
description: "Broad research direction spotting. Scans arXiv (recent + trending), Semantic Scholar (citation velocity), HuggingFace (daily papers + trending models), and Papers With Code (SOTA benchmarks) to identify emerging research directions, hot topics, and underexplored gaps."
parameters:
  type: object
  properties:
    field:
      type: string
      description: "Research field to scan (e.g. 'multi-agent LLM', 'vision-language models', 'efficient inference')"
    time_window:
      type: string
      enum: [week, month, quarter]
      default: month
      description: "How far back to look for trends."
    breadth:
      type: string
      enum: [focused, broad, exploratory]
      default: broad
      description: "focused: stay tight on field. broad: include adjacent areas. exploratory: cast wide net across related fields."
    max_results_per_source:
      type: integer
      default: 5
      description: "Max papers/items per source."
  required:
    - field
---

# Research Radar

Scans multiple sources to build a panoramic view of a research field:

1. **arXiv** — recent papers sorted by submission date
2. **Semantic Scholar** — high citation-velocity papers (trending academically)
3. **HuggingFace Daily Papers** — community-curated trending papers
4. **HuggingFace Models** — trending model uploads (signals practical adoption)
5. **Papers With Code** — SOTA benchmark movements

Returns a structured report with:
- Top papers per source (deduplicated)
- Emerging themes (topics appearing across multiple sources)
- Adjacent directions (related fields gaining momentum)
