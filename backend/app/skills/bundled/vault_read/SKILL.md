---
name: vault_read
description: Read a markdown document from the vault. Can read a specific file or list files in a project.
timeout: 30
parameters:
  type: object
  properties:
    project:
      type: string
      description: Project/folder name.
    filename:
      type: string
      default: ""
      description: Specific file to read. Empty = list all files in project.
  required: [project]
---
