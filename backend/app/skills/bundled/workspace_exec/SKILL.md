---
name: workspace_exec
description: Run a shell command in a persistent per-experiment workspace directory inside the skill-runner container. A real execution environment — network, pip install, and the configured LLM provider keys are all available, with a long timeout (up to ~9 minutes) so genuine multi-step experiments (including many live LLM calls) can run. Use together with workspace_write and workspace_read to build, run, and inspect an experiment like a coding agent.
timeout: 600
parameters:
  type: object
  properties:
    command:
      type: string
      description: "Shell command to run (e.g. 'python run.py', 'pip install numpy', 'ls -la'). Runs with the workspace as the working directory."
    workspace:
      type: string
      default: "default"
      description: "Workspace name; files persist across calls under this name. Use one consistent slug per experiment."
    timeout_seconds:
      type: integer
      default: 300
      minimum: 1
      maximum: 570
      description: "Wall-clock timeout. Hard-capped at 570s. Use a high value for experiments that make many live LLM calls."
  required: [command]
---

Runs `command` in `/workspace/<workspace>/` with the full runner environment
(so `OPENROUTER_API_KEY`, PATH, etc. are present), network access, and pip.
Files written by `workspace_write` (or by the command itself) persist across
calls in the same workspace. Returns returncode, stdout, and stderr (truncated).
The skill-runner container is the isolation boundary.
