---
name: semantic_scholar
description: Academic search returning citation counts + abstracts. Best when you want to rank by influence or find well-cited work. AI/ML coverage is strongest; for broader fields prefer openalex.
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
