---
name: literature_search
description: Search academic literature with rate-limit-safe defaults. Uses arXiv and OpenAlex by default, and only queries Semantic Scholar when explicitly requested and SEMANTIC_SCHOLAR_API_KEY is configured.
timeout: 45
parameters:
  type: object
  properties:
    query:
      type: string
      description: "Academic search query, e.g. 'LLM agent tool failure recovery reflection'."
    year_from:
      type: integer
      default: 2022
      description: "Earliest publication year to include where the source supports filtering."
    max_results:
      type: integer
      default: 12
      minimum: 1
      maximum: 25
      description: "Maximum deduplicated papers to return."
    include_semantic_scholar:
      type: boolean
      default: false
      description: "Only set true when SEMANTIC_SCHOLAR_API_KEY is configured. Otherwise the skill skips Semantic Scholar to avoid 429s."
  required: [query]
---

Searches arXiv and OpenAlex, deduplicates by normalized title, and returns a
compact markdown literature map. Semantic Scholar is opt-in because its
unauthenticated API commonly returns `429 Too Many Requests`.
