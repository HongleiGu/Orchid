# Changelog

All notable changes to Orchid should be recorded here.

Format loosely follows Keep a Changelog. Versions should be tied to the
component that actually changed when useful, for example `skill-runner 0.3.0`
or `orchid 0.1.x`.

## Unreleased

### Added
- Added this changelog to track project and component-level version history.
- Added a Workflow Maker page for drafting import-ready personal DAGs from a
  natural-language request.
- Added `/api/v1/workflow-maker/draft`, which asks the configured LLM to plan a
  workflow, generate a `PipelineConfig`, and report missing required/optional
  skills without breaking import.
- Simplified the agent capability model to skills-only in the product surface:
  the Agents UI no longer exposes a separate Tools picker, examples now use
  `skills`, and create/update/import/export paths fold legacy `tools` values
  into `skills`.
- Added the first Skill Writer surface and `/api/v1/skill-writer/*` endpoints
  for drafting external `SKILL.md + execute.py` packages with env-var
  requirements and detailed setup/test documentation.
- Added ordered package-mirror chains for mainland-China deploys, defaulting
  to Aliyun -> Tsinghua -> upstream. `PIP_INDEX_URLS`, `APT_MIRRORS`,
  `NODE_MIRRORS`, and `NPM_REGISTRIES` are space-separated priority lists: each
  entry is tried in turn and the first that works wins, so a mirror outage
  degrades to the next instead of failing the build.
- Applied those chains to every install surface, including the two that run at
  runtime rather than build time: the marketplace's `npm install`
  (`marketplace/service.py`) and the skill-runner's `/install-deps` pip
  (`skill-runner/main.py`) now walk their chain in order, sharing a single
  timeout budget so retries do not extend the worst case. http:// indexes get
  `--trusted-host` automatically, for Aliyun's intranet endpoint.

- Added an nginx reverse proxy and certbot/Let's Encrypt TLS for the public
  domain, behind a `prod` compose profile so local dev is unaffected. nginx
  terminates TLS and proxies `/api/` (including the run-stream WebSocket) to
  the backend and everything else to Next.js; certbot renews on a 12h loop
  while nginx reloads every 6h to pick up new certificates.
- Added `scripts/init-letsencrypt.sh` for first issuance, which works around
  the bootstrap deadlock (nginx will not start without a certificate; certbot
  cannot issue one without nginx serving the HTTP-01 challenge) by installing
  a throwaway self-signed certificate first. Defaults to the staging CA.
- Resolved nginx upstreams through Docker's embedded DNS (127.0.0.11) with a
  variable-based `proxy_pass`, so they are re-resolved per request. With a
  literal upstream nginx resolves once at startup, which meant it refused to
  start if backend or frontend was briefly absent, and kept 502ing on a stale
  container IP after either was redeployed until the next reload.
- Added `scripts/pull-base-images.sh`, which pulls the base images by naming a
  mirror registry explicitly and retags them to their docker.io names. The
  daemon's `registry-mirrors` list is not a real fallback chain: it picks one
  and aborts if that mirror fails partway through a blob, so a broken
  accelerator blocks the build even with healthy mirrors listed after it.

- Made the nginx config selectable via `NGINX_TEMPLATE_DIR`: `templates-http`
  serves plain HTTP on port 80, `templates-tls` terminates TLS on 443. Both
  keep the `/.well-known/acme-challenge/` location, so a certificate can be
  issued later without editing nginx -- only the env var changes.
- Moved certbot into its own `tls` profile, so running plain HTTP no longer
  starts a renewal loop for a certificate that does not exist.

- Flipped every package-mirror default to upstream-first and moved the
  Aliyun-first chains into `docker-compose.cn.yml`, layered on via
  `COMPOSE_FILE` for a mainland-China host only. The axis that matters is
  network location rather than dev/prod: an overseas server wants the same
  upstream registries a local machine does.

- Added acme.sh as an alternative certificate issuer, driving DNS-01 through
  the Aliyun DNS API (`scripts/issue-cert-acmesh.sh`, `acme` compose profile).
  It needs no inbound port 80 and defaults to ZeroSSL rather than Let's
  Encrypt, and unlike certbot's manual DNS mode it renews unattended, since
  the DNS update is an API call rather than a hand-entered record.

- Added API-key authentication for the public API (OR-29). Keys come from
  `AUTH_API_KEYS`; the backend now refuses to start with authentication
  disabled when `APP_ENV=production`, and warns loudly otherwise. Enforced as
  one middleware rather than per-route dependencies, so a route added later
  cannot silently skip it. WebSockets authenticate via `?token=`, since a
  browser cannot set headers on the handshake.
- Added a deployment capability ceiling for skills (OR-31), mirroring n8n's
  `NODES_INCLUDE`/`NODES_EXCLUDE`. Enforced at `SkillRegistry.resolve`, the
  point every path converges on — the Agents UI, `POST /config/import`, a DAG
  definition, a marketplace package — rather than at the API edge. Lives in
  config rather than the database on purpose: every run consumes untrusted web
  content, so an agent talked into misbehaving must have no write path to the
  thing restricting it. `PRODUCT_PROFILE=app` denies `workspace_exec`,
  `workspace_write`, and `python_experiment` unless explicitly allowed.

- Replaced the run WebSocket with server-sent events. The socket was strictly
  server-to-client — it never called receive — so the bidirectional half was
  unused, and the frontend never connected to it at all. SSE authenticates
  with ordinary headers under the same middleware as every other route
  (removing the `?token=` query parameter, which access logs would capture),
  reconnects on its own, and needs no Upgrade plumbing in nginx.
- Made the run stream resumable: a reconnecting client sends Last-Event-ID and
  the server replays what it missed from the durable `run_events` table before
  resuming live. The WebSocket had no equivalent — a dropped connection simply
  stopped updating.

- Standardised on PostgreSQL and dropped SQLite. SQLite was never really
  supported: there are no dialect branches anywhere and no test ever exercised
  it — yet it was the default, so a fresh clone ran on the one untested
  dialect. Keeps dev matching prod and leaves pgvector available for the
  vault-retrieval epic. (Correction to the commit message: the existing
  migrations do use `op.batch_alter_table`, which is SQLite-safe, so they
  would not have failed there. `render_as_batch` only affects autogenerate.)
- Added a startup warning when the database schema is behind the migrations.
  A stale database otherwise surfaces as `UndefinedColumn` deep inside an
  unrelated request, which reads like an application bug; the check names the
  actual problem and the command that fixes it. Advisory, never fatal.

- Added the run-only API surface allowlist (OR-30). With `PRODUCT_PROFILE=app`
  only runs, budget usage, vault reads and task listing are reachable;
  everything else returns 403, including all of workflow-maker, skill-writer,
  marketplace and config import. Deny-by-default rather than a denylist, so a
  route added later is closed until someone opens it deliberately.
- Added a model ceiling (OR-32) via `MODELS_ALLOW`, enforced before the LiteLLM
  call — the point every model name funnels through, whether it came from an
  agent record, a DAG node override, or a task's runtime params.

- Added the template catalog (OR-34): curated, runnable workflows exposed at
  `GET /api/v1/templates`. Templates ship as files with the release, so there
  is no create/update route and nothing for the run-only profile to block.
  Inputs are derived from the pipeline's task `input_schema` rather than
  restated, keeping one source of truth; the pipeline itself is excluded from
  every response, since the workflow is the product.

- Added `POST /api/v1/templates/{id}/run` as the only way to start a run
  (OR-33). It resolves inputs against the template's declared schema,
  materialises the pipeline through the existing config-import path, and
  queues the run. Triggering an arbitrary task stays denied in the run-only
  profile, so what may run is exactly what shipped in the catalog. Unknown
  input names are rejected rather than ignored — a dropped typo would produce
  a plausible but wrong report.

- Surfaced per-run cost on the run object (OR-36): every run carries
  `cost` (USD, tokens, LLM calls), so a catalog list does not need a second
  call per row, and run detail adds a per-agent/per-model breakdown. Aggregated
  from `token_usage` rather than denormalised onto the row, since usage keeps
  arriving while a run is in flight and a stored copy would be stale exactly
  when someone is watching.
- Added DeepSeek to the pricing table and made the unknown-model fallback log
  once per model. Unlisted models silently used a $1/$3 per-Mtok fallback,
  which for DeepSeek overstated a run by roughly 3-4x — tolerable when nothing
  displayed it, misleading now that runs report their cost.

- Added run-trace verbosity (OR-35): `summary` / `info` / `debug` on run detail
  and the SSE stream, in the logging idiom. Everything is still recorded, so
  changing level never means re-running. `PRODUCT_PROFILE=app` caps at `info`,
  since `debug` carries prompts and inter-agent messages. Errors are shown at
  every level with their diagnostics — deliberately not escalated to full
  debug, which would let anyone able to induce a failure read the prompts.

- Added users and individually revocable API keys (OR-37), with a CLI to issue,
  list and revoke them. Keys are 32 random bytes, shown once, stored as an
  indexed SHA-256 hash. Revocation and user disabling take effect on the next
  request without a restart — the reason identity belongs in the database while
  the capability ceiling stays in config. Static `AUTH_API_KEYS` keep working
  alongside, so an upgrade cannot lock an operator out of their own server.

### Fixed
- Bound the backend, frontend, PostgreSQL, and Redis published ports to
  127.0.0.1. They were published on all interfaces, which on a public host
  would expose an unauthenticated API and a PostgreSQL with default
  credentials alongside the new HTTPS endpoint.
- Pinned the frontend's pnpm via `packageManager` in `frontend/package.json`
  and switched the Dockerfile to `corepack install`, which reads that field.
  The Dockerfile previously used `corepack prepare pnpm@latest`, which floats:
  pnpm 11 raised its floor to Node >= 22.13 and pulls in `node:sqlite`, so the
  Node 20 base started failing `pnpm install` with ERR_UNKNOWN_BUILTIN_MODULE.

## 2026-05-08

### Added
- Added `backend/skill-runner/contracts.py` with public skill-runner contract
  types: `ErrorCode`, `ErrorEnvelope`, `RequestContext`, and header parsing.
- Added `/version` contract semantics for the skill-runner, exposing
  `runner_version` and `api_version`.
- Added skill-runner contract response headers:
  `X-Orchid-Runner-Version` and `X-Orchid-Runner-Api-Version`.
- Added explicit request/response-only long-running semantics for
  skill-runner API v2.
- Added DAG `previous_output` compatibility handoff from direct predecessor
  nodes, including labeled fan-in output.
- Added task descriptions to DAG node prompts so entry nodes receive the same
  human-readable task context as single-agent runs.

### Changed
- Bumped skill-runner to `0.3.0` and API contract to `2`.
- Changed skill-runner `/execute` errors to use structured `ErrorEnvelope`
  values instead of bare strings.
- Changed skill-runner 4xx errors and validation errors to return
  `{"detail": ErrorEnvelope}`.
- Changed `/install-deps` to return a typed response with structured dependency
  install errors.
- Made `previous_output` explicit in DAG prompts for pipeline-style agents.
- Strengthened `arxiv_search` rate limiting with serialized requests, a
  conservative 3.5 second interval, shared 429 cooldown, retry-after parsing,
  configurable user agent, and a short in-memory cache.
- Updated `future.md` to promote the personal AI workflow/DAG maker as the
  Tier 2.1 product wedge and marked Tier 1.1 as done.

### Fixed
- Fixed DAG downstream nodes not seeing expected `previous_output` input.
- Fixed arXiv calls being too sharp around the documented public API pacing,
  which could contribute to frequent 429s during parallel DAG runs.
