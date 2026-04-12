---
name: web_research
description: Search the web for a query and synthesize findings into a concise report.
parameters:
  type: object
  properties:
    query:
      type: string
      description: The research question or topic.
    max_sources:
      type: integer
      description: Maximum number of web sources to consult.
      default: 5
  required:
    - query
---

# Web Research

Searches the web using the configured search provider and returns a synthesized
summary of the top results. Suitable for fact-finding, news lookups, and
gathering background information on a topic.
