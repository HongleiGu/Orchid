---
name: multi_search
description: "Default web search (Tavily + DuckDuckGo aggregated). Use for general-purpose queries. For academic papers prefer the source-specific skills (semantic_scholar, openalex, arxiv_papers, dblp); for a single known URL use web_reader."
parameters:
  type: object
  properties:
    query:
      type: string
      description: Search query.
    engines:
      type: string
      description: "Comma-separated engines: tavily, duckduckgo. Default: all."
      default: "all"
    max_results:
      type: integer
      default: 10
    time_filter:
      type: string
      enum: [any, day, week, month, year]
      default: any
  required:
    - query
---
