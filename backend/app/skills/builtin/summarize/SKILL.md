---
name: summarize
description: Summarize a piece of text into a concise paragraph using an LLM.
parameters:
  type: object
  properties:
    text:
      type: string
      description: The text to summarize.
    max_words:
      type: integer
      description: Target length of the summary in words.
      default: 150
  required:
    - text
---

# Summarize

Uses the configured default LLM to produce a concise summary of the provided
text. Useful as a post-processing step after retrieval or web research.
