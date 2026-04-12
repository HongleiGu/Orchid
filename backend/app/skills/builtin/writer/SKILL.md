---
name: writer
description: "Write polished content from raw notes, research, or bullet points. Supports multiple output formats: blog post, report, email, academic, executive summary."
parameters:
  type: object
  properties:
    content:
      type: string
      description: The raw content, notes, or bullet points to write from.
    format:
      type: string
      enum: [blog, report, email, academic, executive_summary, general]
      default: general
      description: Output format/style.
    tone:
      type: string
      enum: [professional, casual, technical, persuasive, neutral]
      default: professional
    max_words:
      type: integer
      default: 1000
      description: Target word count.
    instructions:
      type: string
      default: ""
      description: Additional instructions (e.g. 'include a call to action', 'write for a non-technical audience').
  required:
    - content
---
