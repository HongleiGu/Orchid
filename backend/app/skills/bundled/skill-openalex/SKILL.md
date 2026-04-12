---
name: openalex
description: Search OpenAlex for academic works. Large coverage, good venue/concept filtering, returns abstracts. Covers journals and conferences including NeurIPS, ICLR, ACL, EMNLP.
parameters:
  type: object
  properties:
    query:
      type: string
      description: Search query.
    max_results:
      type: integer
      default: 10
    year_from:
      type: integer
      description: Filter works published from this year onward.
    venue_type:
      type: string
      enum: [any, conference, journal]
      default: any
  required:
    - query
---
