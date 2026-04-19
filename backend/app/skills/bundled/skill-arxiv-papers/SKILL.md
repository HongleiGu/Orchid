---
name: arxiv_papers
description: Fresh arXiv preprints + HuggingFace daily papers. Use for very recent (days/weeks old) AI/ML work; for older or peer-reviewed work prefer openalex or semantic_scholar.
parameters:
  type: object
  properties:
    query:
      type: string
      description: "Search query for arXiv (e.g. 'multi-agent LLM', 'RAG retrieval augmented'). Leave empty to fetch HuggingFace trending papers instead."
      default: ""
    max_results:
      type: integer
      description: Maximum number of papers to return.
      default: 5
    source:
      type: string
      enum: [arxiv, huggingface, both]
      description: "Which source to fetch from."
      default: both
  required: []
---

# arXiv Papers

Fetches the latest AI/ML research papers from:
- **arXiv** — search by query, sorted by most recent
- **HuggingFace Daily Papers** — trending papers curated by the HF community

Adapted from [ClaWHub daily-paper-digest](https://clawhub.ai/qjymary/daily-paper-digest).
