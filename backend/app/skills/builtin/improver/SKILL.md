---
name: improver
description: "Self-improving content refiner. Takes content, evaluates it against criteria, critiques weaknesses, then rewrites. Runs multiple improvement passes (default 2). Each pass builds on the previous."
parameters:
  type: object
  properties:
    content:
      type: string
      description: The content to improve.
    criteria:
      type: string
      default: ""
      description: "Evaluation criteria (e.g. 'accuracy, clarity, completeness, engagement'). If empty, uses sensible defaults for the content type."
    passes:
      type: integer
      default: 2
      description: "Number of critique-then-rewrite passes (1-3). More passes = higher quality but more tokens."
    focus:
      type: string
      default: ""
      description: "Specific aspect to focus improvement on (e.g. 'make the introduction more engaging', 'add more technical depth', 'shorten to half the length')."
  required:
    - content
---
