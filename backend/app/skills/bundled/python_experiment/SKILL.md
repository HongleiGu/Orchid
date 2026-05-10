---
name: python_experiment
description: Run a small, stdlib-only Python experiment inside the skill-runner sandbox. Use for quick simulations, metric checks, synthetic-data experiments, and validation scripts. This is intentionally constrained: no filesystem access, network access, subprocesses, dynamic imports, or third-party packages.
timeout: 45
parameters:
  type: object
  properties:
    code:
      type: string
      description: "Complete Python code to run. Keep it self-contained and stdlib-only. Print JSON or concise text results to stdout."
    timeout_seconds:
      type: integer
      default: 20
      minimum: 1
      maximum: 30
      description: "Execution timeout. Hard-capped at 30 seconds."
  required: [code]
---

Runs small Python experiments in an isolated temporary directory with a denylist
AST check and process resource limits. This is for lightweight research probes,
not for running untrusted production workloads or installing dependencies.
