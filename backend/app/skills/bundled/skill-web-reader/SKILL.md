---
name: web_reader
description: "Fetch a single known URL and return clean readable text (HTML/scripts/nav stripped). Use after a search to read a specific page (homepage, paper, blog post). Not a search tool — use multi_search to find URLs first."
parameters:
  type: object
  properties:
    url:
      type: string
      description: "The URL to fetch and extract text from. Supports HTML and PDF."
    query:
      type: string
      default: ""
      description: "Optional question or topic to focus the extraction on. When set, returns only paragraphs that match the query terms (with one paragraph of context on each side). This is the most token-efficient mode — use it whenever you have a specific question about the page."
    max_chars:
      type: integer
      default: 3000
      description: "Soft cap on returned characters. Truncation respects sentence/paragraph boundaries."
    selector:
      type: string
      default: ""
      description: "Optional keyword to center extraction around (e.g. 'publications', 'research'). Less precise than `query` — prefer `query` when possible."
  required:
    - url
---

# Web Reader

Fetches a URL, strips HTML/scripts/nav, and returns clean readable text.
Handles common academic page layouts (faculty pages, lab sites, Google Scholar).
