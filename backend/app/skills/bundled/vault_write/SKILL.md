---
name: vault_write
description: Save a markdown document to the vault. Organizes by project folder. Use for persisting pipeline outputs, research reports, digests, etc.
timeout: 30
parameters:
  type: object
  properties:
    project:
      type: string
      description: "Project/folder name (e.g. 'daily-digests', 'professor-reports')."
    filename:
      type: string
      description: Filename without extension. .md is added automatically.
    content:
      type: string
      description: Markdown content to save.
    tags:
      type: string
      default: ""
      description: Comma-separated tags for indexing.
  required: [project, filename, content]
---

Writes to `<vault>/<project>/<filename>.md` and updates `.orchid/index.json`.
