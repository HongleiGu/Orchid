---
name: workspace_write
description: Write a file into a persistent per-experiment workspace inside the skill-runner container. Use to author experiment scripts, config, and data that workspace_exec then runs. Files persist across calls under the same workspace name.
timeout: 30
parameters:
  type: object
  properties:
    path:
      type: string
      description: "Relative file path within the workspace (e.g. 'run.py', 'src/eval.py'). No leading slash, no '..'."
    content:
      type: string
      description: "Full file content to write (overwrites)."
    workspace:
      type: string
      default: "default"
      description: "Workspace name; use one consistent slug per experiment."
  required: [path, content]
---

Writes `content` to `/workspace/<workspace>/<path>`, creating parent
directories. Overwrites any existing file. Pairs with workspace_read and
workspace_exec.
