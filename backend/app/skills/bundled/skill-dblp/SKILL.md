---
name: dblp
description: CS publications, best for top-venue lookup (NeurIPS, ICLR, ICML, ACL, EMNLP). Metadata only — no abstracts. Use to confirm venue/year/authors, not to read content.
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
