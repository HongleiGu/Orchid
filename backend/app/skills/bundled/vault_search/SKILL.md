---
name: vault_search
description: Search the vault for documents by keyword. Searches file names and content across all projects.
timeout: 30
parameters:
  type: object
  properties:
    query:
      type: string
      description: Search keyword.
    project:
      type: string
      default: ""
      description: Limit search to a specific project. Empty = search all.
    max_results:
      type: integer
      default: 10
  required: [query]
---
