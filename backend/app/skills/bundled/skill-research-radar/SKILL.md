---
name: research_radar
description: "Broad research direction spotting. Scans configurable sources: arXiv, Semantic Scholar, OpenAlex, DBLP, CrossRef, ACL Anthology, HuggingFace (papers + models), and Papers With Code."
parameters:
  type: object
  properties:
    field:
      type: string
      description: "Research field to scan (e.g. 'multi-agent LLM', 'vision-language models')."
    time_window:
      type: string
      enum: [week, month, quarter]
      default: month
    breadth:
      type: string
      enum: [focused, broad, exploratory]
      default: broad
    max_results_per_source:
      type: integer
      default: 5
    sources:
      type: string
      description: "Comma-separated list of sources to use. Options: arxiv, semantic_scholar, openalex, dblp, crossref, acl, huggingface_papers, huggingface_models, papers_with_code. Use 'all' for everything."
      default: "all"
    venues:
      type: string
      description: "Comma-separated venue filter for DBLP/OpenAlex (e.g. 'NeurIPS,ICLR,ICML,EMNLP')."
      default: ""
  required:
    - field
---
