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
