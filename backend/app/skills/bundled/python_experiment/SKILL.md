---
name: python_experiment
description: Run a small Python experiment inside the skill-runner container. Use for quick simulations, metric checks, synthetic-data experiments, and validation scripts. Execution is bounded by timeout, output caps, resource limits, and an isolated temporary working directory.
timeout: 45
parameters:
  type: object
  properties:
    code:
      type: string
      description: "Complete Python code to run. Keep it self-contained. Print JSON or concise text results to stdout."
    timeout_seconds:
      type: integer
      default: 20
      minimum: 1
      maximum: 30
      description: "Execution timeout. Hard-capped at 30 seconds."
  required: [code]
---

Runs small Python experiments in an isolated temporary directory with process
resource limits. The skill-runner container is the isolation boundary; Python
syntax/runtime/import errors are returned as normal stderr instead of being
pre-rejected by a separate AST policy layer. This is for lightweight research
probes, not for installing dependencies or long-running workloads.
