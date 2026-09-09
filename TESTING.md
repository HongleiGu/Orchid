# End-to-end acceptance: locked-down run-only edition (epic OR-28)

Everything in OR-29 … OR-42 is merged on `aliyun`. Nothing below has been run on
the server — it was verified on the dev machine against a local Postgres, which
is not the same thing. This is the list to work through on the real box.

Set these once per shell:

```bash
BASE=https://www.dotslash.cn          # or http://127.0.0.1:8000 on the box
KEY=<a key>                           # see §2
H="Authorization: Bearer $KEY"        # X-API-Key: $KEY also works
```

---

## 0. Read this first — the one thing that will confuse you

**A static `AUTH_API_KEYS` key bypasses plans, quotas and attestations.** It is
an operator credential with no user row behind it, so there is no subscription
to check and nobody to hold an attestation record. Every run it starts is
unattributed.

So: if you test the gating in §6–§8 with a static key, **everything will be
allowed and you will think the gates are broken.** Issue a per-user key first.

This is deliberate and documented, but it is also the sharpest edge in the
design — flag it if you would rather it fail closed instead.

---

## 1. Deploy and migrate

- [ ] `git pull` on the server, branch `aliyun`, expect `80ef61e` or later
- [ ] `docker compose build backend` completes (CN mirror chain: aliyun → tsinghua → upstream)
- [ ] `docker compose up -d` — all containers healthy
- [ ] Migrations reach head. There are **three new ones** since the last deploy:
      `0005_subscriptions`, `0006_user_attestations`, `0007_token_usage_span`
      ```bash
      docker compose exec backend alembic current    # expect 0007_token_usage_span
      ```
- [ ] Startup log says which credential source is active — one of
      `API authentication enabled (N static key(s), …)` or `(database keys, …)`
- [ ] `curl -s $BASE/health` → `{"status":"ok"}` **without** a key

> If `alembic current` is behind, the backend logs a stale-schema warning at
> startup rather than failing. Check for it.

## 2. Authentication (OR-29, OR-37, and the a5a32ee fix)

- [ ] No key → 401
      ```bash
      curl -s -o /dev/null -w '%{http_code}\n' $BASE/api/v1/templates
      ```
- [ ] Wrong key → 401
- [ ] Issue a user key and confirm it works:
      ```bash
      docker compose exec backend python -m app.auth.keys create alice --name laptop
      docker compose exec backend python -m app.auth.keys list
      ```
- [ ] **The security fix — test this specifically.** Empty `AUTH_API_KEYS` in
      `.env`, keep the issued key, restart. Requests **must still 401 without a
      key**. Before a5a32ee this configuration served the entire API anonymously
      while logging that authentication was enabled.
- [ ] Revoke the key → next request 401 **without restarting**
      ```bash
      docker compose exec backend python -m app.auth.keys revoke <key-id>
      ```
- [ ] Issuing the first key with no static keys turns auth on within ~30s, no
      restart needed
- [ ] `APP_ENV=production` with no static keys **and** no DB keys → backend
      refuses to start (do this last, then put it back)

## 3. Profile lockdown (OR-30)

With `PRODUCT_PROFILE=app`, all of these must 403 with *"Not available in this
edition"*:

- [ ] `POST /api/v1/agents`, `PUT|DELETE /api/v1/agents/{id}`
- [ ] anything under `/api/v1/workflow-maker` and `/api/v1/skill-writer`
- [ ] `/api/v1/marketplace`, `/api/v1/config`, `/api/v1/providers`
- [ ] `POST /api/v1/tasks/{id}/trigger` — the bypass that would make the
      template allowlist meaningless
- [ ] `GET /api/v1/runs/{id}/spans` — denied by design; node names are the
      workflow itself

And these must still work:

- [ ] `GET /api/v1/templates`, `GET /api/v1/templates/{id}`
- [ ] `POST /api/v1/templates/{id}/run`
- [ ] `GET /api/v1/runs`, `/runs/{id}`, `/runs/{id}/stream`, `POST /runs/{id}/cancel`
- [ ] `GET /api/v1/budget/usage*`, `GET /api/v1/vault/*`
- [ ] `GET /api/v1/attestations`, `POST /api/v1/attestations/{id}/(accept|withdraw)`

- [ ] Set `PRODUCT_PROFILE=full` again and confirm the authoring routes return

## 4. Capability ceilings (OR-31, OR-32)

- [ ] With `PRODUCT_PROFILE=app` and no `SKILLS_ALLOW`, a workflow using
      `@orchid/workspace_exec` fails with 403 *SkillNotPermitted* (denied by default)
- [ ] Naming it in `SKILLS_ALLOW` re-enables it (explicit allow beats default deny)
- [ ] `SKILLS_DENY` wins over `SKILLS_ALLOW` for the same skill
- [ ] `MODELS_ALLOW=deepseek/deepseek-chat` → a template pinned to another model
      is refused **before** the LiteLLM call (no spend)

## 5. Templates (OR-33, OR-34)

- [ ] `GET /api/v1/templates` lists `china-market-daily-brief`
- [ ] The response **never contains a `pipeline` key** — check explicitly, this
      is the product
- [ ] `requires` is present and shows `["attestation:securities_advisory"]`
- [ ] Inputs are listed with defaults derived from the pipeline
- [ ] An unknown input key → 422 naming the accepted ones
- [ ] A second run while one is pending → 409; `{"force": true}` overrides

## 6. Attestations (OR-40) — use a **user** key, not a static one

- [ ] Run the gated template with no attestation → **403** naming
      `attestation:securities_advisory`
- [ ] `GET /api/v1/attestations` returns the text, `accepted: false`
- [ ] Accept with the wrong version → 409
      ```bash
      curl -s -X POST -H "$H" -H 'Content-Type: application/json' \
        -d '{"version":"999"}' $BASE/api/v1/attestations/securities_advisory/accept
      ```
- [ ] Accept with the current version → 201, `accepted: true`
- [ ] Run the template again → **201**
- [ ] Withdraw → running it again → **403**
- [ ] Operator view shows the trail:
      ```bash
      docker compose exec backend python -m app.attestations.cli show alice
      ```
- [ ] Bump `version` in `backend/app/attestations/catalog/attestations.json`,
      restart → the old acceptance goes stale and the template locks again
- [ ] Edit the text **without** bumting the version → also stale, and the log
      carries an error telling you to bump it

⚠️ **The shipped Chinese wording is a placeholder.** It is the text a regulator
would read. Have counsel review it before this template is offered commercially.

## 7. Plans (OR-38) — again, a **user** key

- [ ] `docker compose exec backend python -m app.plans.cli plans` lists `trial`, `standard`
- [ ] `… subscribe alice trial --days 30`
- [ ] `… show alice` — templates limited, `cost/day 1.0`
- [ ] A template outside the plan → **403** naming the plan
- [ ] `… subscribe alice standard` → all templates allowed (latest row wins)
- [ ] `… cancel alice` → access **continues** to `period_end`; `--now` ends it
- [ ] `PLAN_REQUIRED=true` + a user with no subscription → nothing runnable
- [ ] A plan naming a skill that `SKILLS_ALLOW` omits does **not** grant it
      (a plan may only narrow)

## 8. Per-user attribution and quota (OR-39)

- [ ] A run started with alice's key records `user_id` on the run and on its
      `token_usage` rows
- [ ] `GET /api/v1/budget/usage` reflects her spend
- [ ] Set a low `max_cost_per_day` on the trial plan → a run stops with
      *Daily cost limit exceeded* rather than burning through it
- [ ] Two users' spend does not contaminate each other

## 9. Streaming (OR-41)

- [ ] `curl -N -H "$H" $BASE/api/v1/runs/{id}/stream` streams events live
- [ ] Reconnect with `Last-Event-ID: <seq>` → replays from that seq, no gap and
      no duplicate
- [ ] Keepalives arrive on an idle stream and the stream **survives** them
      (this is where the earlier subscription bug lived)
- [ ] **Through nginx**, not just against the backend directly — buffering is
      what usually breaks SSE in production. Watch for events arriving in a
      clump at the end instead of as they happen.
- [ ] `POST /runs/{id}/cancel` ends the stream cleanly

## 10. Verbosity and diagnostics (OR-35, OR-36)

- [ ] `?verbosity=debug` in the `app` profile is capped at `info` — prompts and
      inter-agent messages must not appear
- [ ] A **failed** run surfaces the debug detail anyway, so you do not have to
      re-run it
- [ ] `_withheld` lists what was redacted rather than silently dropping it
- [ ] `cost` on the run object matches `/budget/usage` for that run

## 11. Per-span cost (OR-42) — `PRODUCT_PROFILE=full`

- [ ] Run a DAG workflow, then `GET /api/v1/runs/{id}/spans`
- [ ] Each span shows `cost_usd` (own) and `subtree_cost_usd` (with children)
- [ ] `subtree_share` on the root ≈ 1.0 minus whatever is unattributed
- [ ] Sibling shares identify the expensive node — *"the verifier is 60% of this run"*
- [ ] `cost_unattributed_usd` on `/runs/{id}` is **0** for a new run
- [ ] An **old** run (from before this deploy) shows all of its cost as
      unattributed and zero shares — expected, not a bug; there is no backfill

## 12. A real run, start to finish

- [ ] Run `china-market-daily-brief` against the live DeepSeek key with a real
      watchlist
- [ ] Watch it over SSE from the browser through nginx
- [ ] Output lands in the vault and is readable via `GET /api/v1/vault/...`
- [ ] Cost is attributed per span and rolls up to a number that matches
      `/budget/usage`
- [ ] Cancel a run mid-flight and confirm it stops rather than finishing

## 13. Infrastructure regression

- [ ] TLS: `https://www.dotslash.cn` valid; acme.sh renewal timer in place
- [ ] nginx re-resolves the backend after a container restart (the
      `resolver 127.0.0.11` + variable `proxy_pass` fix) — restart `backend`
      alone and confirm nginx does not 502 permanently
- [ ] `docker compose down && up -d` comes back clean, migrations included

---

## Known gaps — my list, not yours to discover

| | |
|---|---|
| Attestation wording | placeholder, needs counsel before commercial use |
| Per-span cost UI | nothing renders it; `useRunSpans` exists, no component consumes it |
| Frontend types | stale — `Run` has no cost fields at all, though the API returns them |
| Static-key exemption | bypasses plans, quotas and attestations by design (§0) |
| `/spans` in `app` profile | denied deliberately; per-span cost is a full-profile feature |
| Server verification | none of the above has run on the server — that is what this list is for |
