---
name: web_search
description: Multi-provider web/news search (Tavily -> Brave -> SerpAPI, whichever keys are configured). Supports several queries in one call, a news mode with a recency window, and domain include/exclude filters. Returns a deduplicated markdown result table with snippets. Use this to FIND sources; use web_reader to actually READ them.
timeout: 90
parameters:
  type: object
  properties:
    query:
      type: string
      description: "Primary search query. Chinese queries are fine and are recommended for mainland-China sources."
    queries:
      type: array
      items:
        type: string
      default: []
      description: "Extra queries run in the same call. Results across all queries are deduplicated by URL."
    topic:
      type: string
      enum: [general, news, finance]
      default: news
      description: "'news' biases toward fresh reporting (and enables the days window). 'finance' = news plus a finance-source bias."
    days:
      type: integer
      default: 3
      minimum: 1
      maximum: 30
      description: "Recency window in days for topic=news/finance."
    max_results:
      type: integer
      default: 10
      minimum: 1
      maximum: 25
      description: "Maximum deduplicated results returned per call."
    include_domains:
      type: array
      items:
        type: string
      default: []
      description: "Restrict results to these domains, e.g. ['eastmoney.com','cs.com.cn','stcn.com']."
    exclude_domains:
      type: array
      items:
        type: string
      default: []
      description: "Drop results from these domains."
  required: [query]
---

Searches the web through whichever provider keys are present in the environment
(`TAVILY_API_KEY`, `BRAVE_API_KEY`, `SERPAPI_API_KEY`), trying them in that
order and falling through on failure. Every query is run against the first
working provider; results are merged, deduplicated by normalized URL, and
returned as a markdown table plus per-result snippets, with a coverage note
listing which provider answered and which queries returned nothing.
