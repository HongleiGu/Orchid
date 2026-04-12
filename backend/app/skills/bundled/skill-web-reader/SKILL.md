---
name: web_reader
description: "Fetch a web page and extract its readable text content. Strips HTML, scripts, and navigation. Returns clean text suitable for LLM analysis. Useful for reading professor homepages, lab pages, publication lists, etc."
parameters:
  type: object
  properties:
    url:
      type: string
      description: "The URL to fetch and extract text from."
    max_chars:
      type: integer
      default: 8000
      description: "Maximum characters to return. Truncates from the end."
    selector:
      type: string
      default: ""
      description: "Optional CSS-like keyword to focus extraction (e.g. 'publications', 'research', 'students'). Tries to find the section containing this keyword and extracts around it."
  required:
    - url
---

# Web Reader

Fetches a URL, strips HTML/scripts/nav, and returns clean readable text.
Handles common academic page layouts (faculty pages, lab sites, Google Scholar).
