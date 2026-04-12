---
name: semantic_scholar
description: Search Semantic Scholar for academic papers. Returns titles, authors, abstracts, citation counts, and venues. Good for finding well-cited and recent AI/ML research.
parameters:
  type: object
  properties:
    query:
      type: string
      description: Search query (matches title + abstract).
    max_results:
      type: integer
      default: 10
    year_from:
      type: integer
      description: Filter papers published from this year onward.
    venues:
      type: string
      description: "Comma-separated venue filter applied client-side (e.g. 'NeurIPS,ICLR,EMNLP')."
      default: ""
  required:
    - query
---
