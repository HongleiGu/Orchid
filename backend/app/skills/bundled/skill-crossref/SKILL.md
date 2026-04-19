---
name: crossref
description: DOI-anchored published works (journals + proceedings). Use when you need a citable DOI or peer-reviewed journal coverage; abstracts are often missing — pair with openalex for content.
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
