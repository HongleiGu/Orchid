---
name: multi_search
description: "Search multiple web engines simultaneously without API keys. Aggregates results from DuckDuckGo, Brave Search, Bing, and Google. Deduplicates and ranks results. Adapted from ClaWHub gpyangyoujun/multi-search-engine."
parameters:
  type: object
  properties:
    query:
      type: string
      description: Search query. Supports operators like site:, filetype:, "exact phrase", -exclude.
    engines:
      type: string
      description: "Comma-separated engines to use: duckduckgo, brave, bing, google. Default: all."
      default: "all"
    max_results:
      type: integer
      default: 10
      description: Total results after deduplication and ranking.
    time_filter:
      type: string
      enum: [any, day, week, month, year]
      default: any
      description: Restrict results to a time period.
  required:
    - query
---

# Multi Search Engine

Searches multiple web engines in parallel without requiring any API keys.
Aggregates, deduplicates, and ranks results by cross-engine agreement.

Adapted from [ClaWHub multi-search-engine](https://clawhub.ai/gpyangyoujun/multi-search-engine).
