# Deploying to a fresh mainland-China server

Written for the Beijing box. Hong Kong needed almost none of §1 or §2 — mainland
does. Work top to bottom; each step assumes the one above succeeded.

Acceptance testing after this lives in [TESTING.md](TESTING.md).

---

## 0. Before anything: is the domain filed?

A domain served from a mainland host on port 80/443 needs **ICP 备案**. Without
it the IDC drops those ports for that domain — not a refusal, a silent drop that
looks exactly like a firewall misconfiguration and will cost you an evening.

```bash
curl -sI http://www.dotslash.cn | head -1     # from off-box
```

Certificate issuance still works unfiled: acme.sh below uses DNS-01 and never
needs inbound port 80. So you can end up holding a perfectly valid certificate
for a domain nobody can reach. Don't read a successful `issue-cert-acmesh.sh` as
proof the site is up.

Also open 80 and 443 in the security group — a new instance gets a new one.

## 1. Host-level: Docker registry

Compose cannot set this; it lives in the host daemon.

```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json >/dev/null <<'JSON'
{ "registry-mirrors": ["https://<your-accelerator>.mirror.aliyuncs.com"] }
JSON
sudo systemctl restart docker
docker pull postgres:16-alpine       # prove it before going further
```

If Docker Hub stays unreachable, use the ACR route instead — `docker login`,
then `ACR_REPO=... ./scripts/pull-from-acr.sh`. Use the **public** endpoint, not
`-vpc`: the `-vpc` name resolves anywhere via wildcard DNS, but its
`100.64.0.0/10` address is unroutable outside the registry's own region and the
pull simply hangs. Check the region with
`curl -s http://100.100.100.200/latest/meta-data/region-id`.

## 2. `.env`

```bash
cp .env.example .env
```

Then set, in this order of importance:

```bash
# ── Runs in production, and refuses to boot unauthenticated ──
APP_ENV=production

# ── Mainland mirror chains for pip / apt / npm / node ──
COMPOSE_FILE=docker-compose.yml:docker-compose.cn.yml

# ── Public origin ──
COMPOSE_PROFILES=prod,acme
NGINX_TEMPLATE_DIR=templates-http        # switch to templates-tls in §3
DOMAIN=www.dotslash.cn
DOMAIN_ALT=dotslash.cn
APP_CORS_ORIGINS=https://www.dotslash.cn
NEXT_PUBLIC_API_URL=https://www.dotslash.cn

# ── Certificates (acme.sh + Aliyun DNS-01) ──
ACME_EMAIL=you@example.com
ACME_CA=zerossl
ALI_KEY=<RAM AccessKey ID with AliyunDNSFullAccess>
ALI_SECRET=<matching secret>

# ── Authentication ──
AUTH_API_KEYS=<generate: python -c "import secrets; print(secrets.token_urlsafe(32))">

# ── LLM: domestic provider ──
DEEPSEEK_API_KEY=<key>
LLM_DEFAULT_MODEL=deepseek/deepseek-chat
LLM_FALLBACK_MODEL=deepseek/deepseek-reasoner
```

Leave `DATABASE_URL` and `REDIS_URL` **unset** — compose sets both to the
in-network hosts, and a value here only misleads anything you run from the host
shell.

Use a RAM sub-account key for `ALI_KEY`, never your root account's: it needs
only `AliyunDNSFullAccess`, and it is the credential that can reissue
certificates for your domain if it leaks.

Two things worth knowing about this file:

- **Duplicate keys silently last-win.** Both compose and pydantic take the last
  definition. Appending a correction to the bottom works, but leaves the top of
  the file lying to the next reader. Edit in place.
- **Windows line endings break values.** If this file was ever edited on
  Windows, a trailing `\r` becomes part of the value and a correct-looking API
  key will never match. Check with
  `grep '^AUTH_API_KEYS=' .env | cat -A | tail -c 40` — `^M$` means run
  `sed -i 's/\r$//' .env`.

## 3. Certificates

`NGINX_TEMPLATE_DIR=templates-http` for now: the TLS template refuses to start
without a certificate file, and you don't have one yet.

```bash
./scripts/issue-cert-acmesh.sh
```

The script is idempotent and self-explaining. It installs a throwaway
self-signed cert so nginx can boot, starts nginx, registers with ZeroSSL,
issues via the Aliyun DNS API, installs the result where nginx reads it, and
reloads. If it fails, re-run with `--debug 2` appended — that is what surfaces
the DNS provider's actual error code rather than a generic failure.

Then switch to TLS and bring everything up:

```bash
sed -i 's/^NGINX_TEMPLATE_DIR=.*/NGINX_TEMPLATE_DIR=templates-tls/' .env
docker compose up -d
curl -vI https://www.dotslash.cn 2>&1 | grep -E 'issuer|subject|HTTP/'
```

Renewal is unattended: the `acme` container runs acme.sh's cron in daemon mode,
and nginx reloads itself every 6h, so a renewed certificate is picked up without
being signalled.

## 4. Bring the stack up and migrate

```bash
docker compose up -d
docker compose exec backend alembic current      # expect 0007_token_usage_span
docker compose logs --tail=40 backend
```

The backend entrypoint runs `alembic upgrade head` before uvicorn, so a first
deploy migrates itself. The startup log should say
`API authentication enabled (1 static key(s), profile=full)`.

**Which command applies which kind of change** — this costs an hour otherwise:

| changed | command |
|---|---|
| code (bind-mounted) | `docker compose restart backend` |
| anything in `.env` | `docker compose up -d --force-recreate backend` |
| `requirements.txt` | `docker compose build backend && docker compose up -d backend` |

A container's environment is fixed when it is **created**, so `restart` reuses
the old values and a newly added variable never reaches the process. Verify with
`docker compose exec backend printenv AUTH_API_KEYS`, not by reading the file.

## 5. Seed a user and check it end to end

```bash
docker compose exec backend python scripts/seed_test_user.py \
  --identifier server-tester --plan trial --base-url https://www.dotslash.cn
```

Put the two `TEST_*` lines it prints into `.env`, then:

```bash
export AUTH_KEY=$(grep '^AUTH_API_KEYS=' .env | cut -d= -f2- | cut -d, -f1)
curl -s -o /dev/null -w '%{http_code}\n' https://www.dotslash.cn/api/v1/templates                      # 401
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $AUTH_KEY" \
     https://www.dotslash.cn/api/v1/templates                                                          # 200
```

Two 401s and a 200 means the deploy is sound. Continue with
[TESTING.md](TESTING.md).

---

## Things that will look broken but aren't

- **The web UI 401s on everything.** `frontend/src/lib/api.ts` sends no
  credentials at all — no `Authorization`, no cookie. Any deployment with
  authentication enabled has a dark UI until the new UI ships with real login.
  Do **not** work around it by putting a key in `NEXT_PUBLIC_*`: that value
  ships inside the client bundle, readable by anyone, and a static key bypasses
  plans, quotas and attestations.
- **`NEXT_PUBLIC_*` changes need a rebuild**, not a restart — they are baked in
  at build time. `docker compose build frontend`.
- **Old runs report all their cost as unattributed.** `token_usage.span_id`
  arrived in migration 0007 with no backfill; there is nothing to attribute
  rows written before it to.
- **The market-brief template refuses to run with 403.** It requires the
  `securities_advisory` attestation, which the *user* must accept — an operator
  cannot do it for them by design. See TESTING.md §6.
