---
name: dblp
description: Search DBLP for computer science publications. Best for finding papers from top venues (NeurIPS, ICLR, EMNLP, ACL, ICML etc). Returns metadata only (no abstracts).
parameters:
  type: object
  properties:
    query:
      type: string
      description: Search query.
    max_results:
      type: integer
      default: 10
    venue:
      type: string
      description: "Venue keyword to filter (e.g. 'NeurIPS', 'ICLR'). Added to search query."
      default: ""
  required:
    - query
---
