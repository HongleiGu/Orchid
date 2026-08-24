---
name: workspace_read
description: Read a file from a persistent per-experiment workspace inside the skill-runner container. Use to inspect experiment outputs, logs, or result files produced by workspace_exec. If the file is missing it returns a listing of the workspace so you can see what exists.
timeout: 30
parameters:
  type: object
  properties:
    path:
      type: string
      description: "Relative file path within the workspace (e.g. 'results.json', 'out.log'). No leading slash, no '..'."
    workspace:
      type: string
      default: "default"
      description: "Workspace name; must match the one used to write/run."
  required: [path]
---

Reads `/workspace/<workspace>/<path>` (truncated). If the file does not exist,
returns the list of files currently in the workspace.
