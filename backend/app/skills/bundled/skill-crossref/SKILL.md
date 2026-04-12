---
name: crossref
description: Search CrossRef for published works with DOIs. Good coverage of journal articles and conference proceedings. Some abstracts available.
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
      description: Filter papers published from this year.
    type:
      type: string
      enum: [any, proceedings-article, journal-article]
      default: any
      description: Filter by work type.
  required:
    - query
---
