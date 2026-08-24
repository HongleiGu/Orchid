---
name: python_experiment
description: Run a small Python experiment inside the skill-runner container. Use for quick simulations, metric checks, synthetic-data experiments, and validation scripts. Can make real LLM inference calls via stdlib urllib using the configured provider key when a hypothesis genuinely needs a live model. Execution is bounded by timeout, output caps, resource limits, and an isolated temporary working directory.
timeout: 150
parameters:
  type: object
  properties:
    code:
      type: string
      description: "Complete Python code to run. Keep it self-contained (stdlib only — no third-party imports). Print JSON or concise text results to stdout."
    timeout_seconds:
      type: integer
      default: 20
      minimum: 1
      maximum: 120
      description: "Execution timeout in seconds. Hard-capped at 120. Use a higher value (e.g. 90-120) for experiments that make live LLM API calls."
  required: [code]
---

Runs small Python experiments in an isolated temporary directory with process
resource limits. The skill-runner container is the isolation boundary; Python
syntax/runtime/import errors are returned as normal stderr instead of being
pre-rejected by a separate AST policy layer. Stdlib only — no dependency
installation.

LLM calls: the experiment subprocess receives the provider credentials
(`OPENROUTER_API_KEY` / `OPENAI_API_KEY`, base URLs, `LLM_DEFAULT_MODEL`) — and
only those keys — so an experiment can call a model over HTTPS with stdlib
`urllib`. Keep the number of calls small so the run fits inside the timeout.
