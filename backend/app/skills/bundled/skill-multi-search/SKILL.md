---
name: multi_search
description: "Web search using Tavily API (primary, requires TAVILY_API_KEY) and DuckDuckGo JSON API (fallback). Aggregates and deduplicates results."
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
