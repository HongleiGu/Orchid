# End-to-end acceptance: locked-down run-only edition (epic OR-28)

Everything in OR-29 … OR-42 is merged on `aliyun`. Nothing below has been run on
the server — it was verified on the dev machine against a local Postgres, which
is not the same thing. This is the list to work through on the real box.

Set these once per shell. `TEST_BASE_URL` and `TEST_API_KEY` live in `.env`
(gitignored), so there is nothing to paste:

```bash
eval "$(grep -E '^TEST_(BASE_URL|API_KEY)=' .env | sed 's/^/export /')"
BASE=$TEST_BASE_URL
H="Authorization: Bearer $TEST_API_KEY"   # X-API-Key: $TEST_API_KEY also works
```

Only those two lines are read, not the whole file — `.env` has values that
would not survive `source`.

The key already in `.env` belongs to DB user **`local-tester`**, on the **trial**
plan. It is a per-user key, so the plan and attestation gates genuinely apply to
it. Point `TEST_BASE_URL` at the server and swap the key when you move on.

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

## 0b. Testing locally first — what differs

Worth doing: §2–§8, §10 and §11 are all fully exercisable on this machine, and
finding a bug here is cheaper than finding it on the box. What follows is what
is *different* locally, so a difference does not read as a failure.

**Cannot be tested locally at all** — do these on the server:

- §9's *"through nginx"* line and all of §13. nginx locally would need a cert
  for `dotslash.cn`. SSE buffering is precisely the class of bug that only
  appears behind a proxy, so this is the one gap that matters.

**Different, and will surprise you:**

- **The local API is currently open.** `AUTH_API_KEYS` is empty *and* the local
  DB has no other keys besides the one just issued — so before that key existed,
  every endpoint answered anonymously. That is correct behaviour for localhost
  (the backend warns loudly at startup), but it means §2's "no key → 401" only
  holds now that `local-tester` has a key.
- **Auth latches on.** Once the process has seen a database key it enforces for
  its whole lifetime. Revoking every key does *not* reopen the API until you
  restart — deliberate, it fails closed. Don't read it as a stuck cache.
- **Every `.env` change needs a restart.** Settings are cached at import, so
  flipping `PRODUCT_PROFILE`, `PLAN_REQUIRED`, `SKILLS_ALLOW` etc. does nothing
  until the backend restarts — even under `--reload`.
- **`PRODUCT_PROFILE=full` locally**, so §3 needs you to switch it to `app` and
  restart, then switch back.
- **No DeepSeek key here.** `LLM_DEFAULT_MODEL` is `openrouter/openai/gpt-4o-mini`.
  Anything in the catalog naming `deepseek/*` will fail locally unless you add
  a key or repoint the model.
- **CORS is set for port 3000 but `FRONTEND_PORT=4000`.** If you test from the
  browser rather than curl, the browser will block it. Either set
  `APP_CORS_ORIGINS=http://localhost:4000` or run the frontend on 3000.
- **`REDIS_URL` is empty** → in-process pub/sub. Fine for one backend, but it
  means the local setup does not exercise the multi-worker path the server may
  eventually use.
- **Old runs in the local DB predate `span_id`**, so they show all cost as
  unattributed. Expected (§11), not a regression.

**Windows, specifically:**

- Use **Git Bash**, not PowerShell. In PowerShell `curl` is an alias for
  `Invoke-WebRequest`, which does not understand `-H`, `-N` or `-o /dev/null`
  and will fail confusingly. If you must use PowerShell, call `curl.exe`.
- SSE (§9) needs `curl.exe -N`; `Invoke-WebRequest` buffers the whole response
  and you will see nothing until the run ends.

**Run the stack with `docker compose up -d`**, not bare uvicorn on the host.
Every bundled skill is a proxy that forwards to `http://skill-runner:9000`, and
that URL is a hardcoded constant in `backend/app/marketplace/proxy.py` — there
is no env var to repoint it. Off the compose network the hostname does not
resolve and every skill call fails. Fine for §2–§8 and §11, which touch no
skills; fatal for §12.

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
- [ ] Edit the text **without** bumping the version → also stale, and the log
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
- [ ] A plan naming a skill that `SKILLS_ALLOW` omits does **not** grant it —
      `plans.cli show alice` proves the narrowing, but see the caveat below

> ⚠️ **A plan's `skills` and `models` lists are computed but not yet enforced.**
> `permissions_for()` is consumed in exactly two places — the template gate and
> the cost caps — so a plan can restrict *which templates* and *how much spend*,
> and `plans.cli show` displays the correctly-narrowed skill and model sets, but
> nothing checks them at skill-resolution or model-call time. The deployment
> **ceiling** (`SKILLS_ALLOW` / `MODELS_ALLOW`) *is* enforced, in §4. Do not read
> a passing §4 as proof that per-plan skill limits work — they do not exist yet.

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

- [ ] Run `china-market-daily-brief` with a real watchlist. **Locally this runs
      on OpenRouter** (`LLM_DEFAULT_MODEL=openrouter/openai/gpt-4o-mini`); there
      is no DeepSeek key in the local `.env`. Real money either way — keep the
      watchlist short the first time.
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
| Plan skill/model limits | computed and displayed, but not enforced anywhere (§7) |
| Static-key exemption | bypasses plans, quotas and attestations by design (§0) |
| `/spans` in `app` profile | denied deliberately; per-span cost is a full-profile feature |
| Server verification | none of the above has run on the server — that is what this list is for |
