# Orchid — Roadmap

This is a working plan, not a contract. Re-evaluate after each tier ships.

The strategic frame: the wedge is **personal AI workflow authoring +
predictable cost + verified skills + clean sandbox boundaries** ("OpenClaw, but
boring, with a real workbench"). Everything below either builds that moat or is
foundation work that lets us build it without rewriting later.

The product should not compete as a generic CI/CD pipeline tool. The memorable
thing is: a person can describe a recurring knowledge-work process, Orchid turns
it into an inspectable DAG/workflow, runs it with trusted skills, and leaves
behind durable artifacts plus a cost/debug trace.

The split:
- **`orchid` (this repo)** — agent framework. MIT, hobbyist-runnable with
  `docker-compose up`. Default sandbox = the current skill-runner container.
- **`orchid-platform` (separate, commercial)** — per-run microVMs, multi-tenancy,
  auth, billing, signed-skill registry, one-click deploy. Implements the same
  contracts this repo defines, never forks the framework.

The contracts between the two (skill-runner HTTP API, auth headers, tenant
context) are the most valuable artifact in Tier 1. Get them right first.

---

## Tier 1 — Commercial-split foundation (next 4-6 weeks)

Cheap prep work that's brutal to retrofit. Do this before either codebase
grows further.

### 1.1 Skill-runner HTTP contract spec
**Status: done.** The runner exposes `/version`, contract headers, shared
Pydantic contract types, request-context headers, structured error envelopes,
and explicit request/response-only long-running semantics.

Today the skill-runner is a private implementation detail. Make it a versioned
public spec so `orchid-platform`'s microVM runner can implement the same surface
without forking. Pin: request/response schemas, error envelope, version header,
streaming semantics for long-running skills.
- **Why now:** every later change (microVMs, signed packages, telemetry) flows
  through this boundary.
- **Scope:** ~half day. Mostly documenting what already exists in
  [skill-runner/main.py](backend/skill-runner/main.py), plus a `/version` endpoint.

### 1.2 `tenant_id` everywhere
Add `tenant_id` (string, indexed) to: `runs`, `agents`, `tasks`, `budgets`,
`vault index`, `installed_packages`, `run_events`. Default to `"default"` for
OSS single-user. One Alembic migration; trivial today, weeks of work later.
- **Why now:** the platform layer needs this; OSS users get a no-op default.
- **Scope:** ~1 day. Migration + a `tenant_context` middleware that reads
  `X-Tenant-Id` (defaults to `"default"`).

### 1.3 Auth-proxy contract
The framework does not implement auth. It trusts `X-Tenant-Id` / `X-User-Id`
headers from a reverse proxy (Caddy forward-auth, oauth2-proxy, or the platform
layer). In production mode, refuse to start without `TRUST_PROXY_AUTH=true`.
Document the contract: which headers, what they mean, how to rotate.
- **Why now:** hobbyists shouldn't need auth; commercial deployments must
  never run without it. Encoding the contract now prevents people from baking
  half-built auth into the OSS core.
- **Scope:** ~half day. Middleware + docs.

### 1.4 Per-tenant cost SLO + interdiction
The wedge against OpenClaw's 442k-token subagent loop bug. Two layers, framed
as a *contract* the agent runs under, not just a soft cap:
- **Projection.** Before any tool call fires, compute projected cost (tokens ×
  model price) based on the agent's plan. Surface it; optionally require
  approval over a threshold.
- **Enforcement + graceful degradation.** Agents commit to "complete this task
  under $X or fail safe." If the primary model burns 80% of budget, the
  framework auto-degrades to a cheaper one (Sonnet → Haiku) for the remaining
  steps rather than blowing through the cap.
Builds on existing [`check_budget`](backend/app/core/agent.py#L188-L198) and
`record_usage`.
- **Why now:** this is the demo. Nobody else interrupts pre-execution; everyone
  bills you after. The *contract* framing — not just "we estimated $X" but
  "this run cannot exceed $X" — is what turns it from a feature into a product
  story.
- **Scope:** projection ~1.5 weeks. Auto-degradation ~1 more week; can defer
  past Tier 1 if needed.

---

## Tier 2 — Product differentiation (1-3 months)

The features that make people actually choose this over OpenClaw / forks.
All of these depend on Tier 1 being clean.

### 2.1 Personal AI workflow/DAG maker
The main user-facing wedge. Orchid should help a single person turn fuzzy,
recurring work into an explicit workflow they can inspect, edit, run, and reuse.
This is not just a canvas; it is a workflow co-author.

- **Natural-language workflow creation.** User describes a process ("track new
  papers weekly, write a brief, save to vault, email me"). Orchid drafts agents,
  DAG nodes, edges, task inputs, skill choices, and prompts.
- **Visual DAG editor as first-class product surface.** The current editor moves
  out of "JSON helper" territory: node prompt editing, skill selection,
  input/output previews, edge conditions, test-run-one-node, and graph-level
  validation before save.
- **Personal templates.** Save a workflow as a reusable template with input
  schema, defaults, schedule, vault destination, budget cap, and examples.
- **Run-to-edit loop.** After a failed or weak run, Orchid suggests concrete
  edits: missing input field, bad edge condition, too much context, tool failed,
  cost cap hit. One click applies a patch to the DAG/prompt.
- **Why:** Harness/Airflow-style tools are powerful once the workflow is known.
  Orchid wins earlier: helping the user discover and maintain the workflow
  itself.
- **Scope:** ~2 weeks for NL-to-DAG scaffolding and graph validation; another
  ~2 weeks for the polished editor + run-to-edit loop.

### 2.2 Skills ecosystem & AI skill writer
The user-named pillar. Two halves:
- **Skill writer agent** — given a description and example I/O, generates a
  scaffolded skill (SKILL.md + execute.py + tests), runs it in the sandbox,
  iterates until tests pass. Ships as a built-in workflow.
- **Signed skill registry** — answer to ClawHavoc (1184 malicious packages,
  9000+ compromised installs on ClawHub). Every skill in the registry is
  signed, sandbox-tested in CI before publish, has a reputation score, and
  declares its required network egress + filesystem scope upfront. The
  framework refuses to load unsigned skills in production mode.
- **Scope:** writer = ~2 weeks; registry = ~1 month including frontend.

### 2.3 Plan-driven orchestrator workflow
The fifth workflow type we discussed earlier: agent receives a user-supplied
plan (markdown checklist), can call other tasks/agents/tools as it goes,
updates a TodoWrite-style live task list. Reuses existing `_llm_loop` and the
`_PeerCallTool` pattern; adds a new `_TaskCallTool` that wraps tasks as
callables.
- **Why:** trades the rigidity of pipelines/DAGs for adaptive execution while
  keeping observability via the live plan.
- **Scope:** ~1 week including UI for plan editing.

### 2.4 Memory layer
Per the 2026 framework comparison, only CrewAI / Mastra / Google ADK ship real
built-in memory. Orchid agents are stateless across runs. Add: per-agent memory
store (vector + key/value), opt-in retrieval into the system prompt, explicit
memory-write tool. Scope decisions (per-agent? per-tenant? per-task?) need a
short design doc.
- **Scope:** ~2-3 weeks.

### 2.5 Observability — OTel traces + replay debugger
Two pieces, ship together:
- **OTel instrumentation.** Wrap `_llm_loop`, every tool call, every skill
  invocation in spans. Export to OTLP. Pairs with cost SLOs (1.4) to make
  "what just cost $50?" debuggable.
- **Replay debugger.** Step through a finished run frame-by-frame using the
  immutable [`run_events`](backend/app/db/models/run.py) table; fork from any
  frame with a different prompt / model / skill version and re-execute.
  Pairs with evals (2.6) — every regression becomes a forkable scenario.
  This is the visually unforgettable feature: "Chrome DevTools for agent
  execution." No major framework ships this.
- **Scope:** instrumentation ~3 days; replay UI ~1 week; fork-and-rerun ~1
  more week.

### 2.6 Evals
Regression tests for agents/prompts. Without these, every prompt tweak
(like the description rewrites we just did) is uninsured production change.
Borrow the format Anthropic uses: fixture inputs + judge model rubric +
threshold for pass. Wire into CI.
- **Scope:** ~1 week for the harness; ongoing for fixture coverage.

### 2.7 Air-gap / local-first deploy mode
First-class support for running the framework with zero egress: BYO LLM via
vLLM / Ollama / private Bedrock endpoint (already supported through LiteLLM),
no telemetry phoning home, signed-skill registry mirrored to a local cache,
eval fixtures and judge models also local. Ships with an `offline-mode
self-test` that fails if anything tries to reach the public internet.
- **Why:** defense, healthcare, finance, EU public sector all want this and
  cannot use any current "enterprise" agent platform credibly. Closes
  procurement conversations the SaaS competitors structurally can't.
- **Scope:** ~2 weeks framework changes (telemetry kill switch, local
  registry mirror, offline self-test). Ongoing CI to keep it from breaking.
- **Tradeoff:** raises support surface; buyers are slower-moving than
  commercial SaaS, so don't lead the early commercial pipeline with this —
  treat it as a moat that opens specific verticals later.

---

## Tier 3 — `orchid-platform` launch (3-6 months)

A separate repo and product. Buys it the right to be opinionated and complex.

### 3.1 Per-run microVM sandbox runtime
Replaces the single shared skill-runner container with one Firecracker (or
gVisor / Kata) microVM per run. Implements the Tier 1.1 HTTP contract so the
framework code is unchanged. Network egress allowlist per skill. Memory + CPU
caps per run.
- **Why:** answers OpenClaw's CVE-2026-25253 class of vulnerabilities at the
  architectural layer, not via prompt prayer.

### 3.2 Multi-tenancy + billing
Per-tenant: budget enforcement, run queue with fair scheduling, vault
isolation, skill allowlist, BYOK credentials. Stripe usage records keyed off
`record_usage`. The framework already accepts the tenant context from Tier 1.2
— this is the layer that supplies it.

### 3.3 One-click deploy
A Helm chart + a Coolify recipe + a "press button on a VPS" installer. Whatever
the target audience uses. The hobbyist still uses `docker-compose up` against
the OSS repo; this is for paying customers who want zero-ops.

### 3.4 Marketplace UI
Discovery, install, ratings, signed-publisher verification. Sits on top of the
Tier 2.2 registry.

---

## Ongoing / lower priority

- **MCP server support** — partially present in [main.py:71-74](backend/app/main.py#L71-L74); make first-class with a UI to add servers and bridge MCP tools to the skill registry.
- **Frontend / workflow builder polish** — no longer a lower-priority concept;
  Tier 2.1 makes it the main product surface. Ongoing work here is refinement:
  keyboard UX, templates, diff views, import/export, screenshots for docs.
- **Token streaming** — WebSocket exists for run events ([app/ws/](backend/app/ws/)); add per-token streaming for live agent UX.
- **Documentation** — minimal today. Tier 1.1 spec is the cornerstone; everything else builds on it.
- **Skill description quality reviews** — periodic sweep similar to the one in this session. Tied to evals (Tier 2.6) so regressions get caught.

---

## What we are deliberately NOT building

- **Native auth.** Always external (Tier 1.3).
- **Bundled VM/microVM.** Lives in `orchid-platform` only (Tier 3.1).
- **Multi-channel chat gateway** (WhatsApp/Slack/Discord/etc.). That's
  OpenClaw's strength; we don't compete there. If users want it, they wire
  Orchid behind their own gateway.
- **Our own LLM.** Provider-agnostic via LiteLLM, full stop.
- **Generic RPA / browser automation.** Adjacent space; out of scope unless a
  customer pays for it.

---

## Decision points to revisit

- After Tier 1.4 ships: is dry-run cost projection actually a buying signal?
  Run it past 5 prospective users before investing in Tier 2 differentiators.
- After Tier 2.1: can a non-author user create a useful workflow from a plain
  English process description in under 10 minutes? If not, keep narrowing the
  workflow maker before adding more platform features.
- After Tier 2.2: does the skill registry have organic contribution? If not,
  Tier 3.4 is premature.
- After Tier 3.1: do we need our own deploy tooling (3.3) or is "BYO Helm"
  sufficient for early customers?
- After Tier 2.7: are air-gap inquiries actually closing deals, or just
  window-shopping? If only the latter, deprioritize the ongoing CI cost.
