---
name: web_search
description: Basic single-provider web search (Tavily or Brave, whichever is configured via SEARCH_PROVIDER). Prefer multi_search when available — it aggregates multiple engines. Use this when you need a quick, low-overhead query.
timeout: 60
parameters:
  type: object
  properties:
    query:
      type: string
      description: The search query.
    max_results:
      type: integer
      default: 5
      description: Maximum number of results to return.
  required: [query]
---

Configure with TAVILY_API_KEY or BRAVE_API_KEY in env, plus SEARCH_PROVIDER=tavily|brave.
