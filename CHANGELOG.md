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
