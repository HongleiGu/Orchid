#!/usr/bin/env bash
# Automated slice of TESTING.md — the checks that are just HTTP.
#
#     ./scripts/acceptance-check.sh                 # read-only, safe anywhere
#     ./scripts/acceptance-check.sh --write         # + accept/withdraw an attestation
#     ./scripts/acceptance-check.sh --write --run   # + actually start a run (SPENDS MONEY)
#
# Reads TEST_BASE_URL, TEST_API_KEY and AUTH_API_KEYS from .env. The checks that
# need a config change and a restart — the profile allowlist, PLAN_REQUIRED,
# skill and model ceilings — stay manual; this covers what can be asserted
# against a running deployment without touching it.
#
# Deliberately dependency-free: no jq. A server that has just been provisioned
# usually has curl and nothing else, and a missing tool at this point reads as
# a product failure rather than a harness one.
set -u

cd "$(dirname "$0")/.."

WRITE=0
DO_RUN=0
for arg in "$@"; do
  case "$arg" in
    --write) WRITE=1 ;;
    --run)   DO_RUN=1 ;;
    *) echo "usage: $0 [--write] [--run]" >&2; exit 2 ;;
  esac
done

# Environment first, then .env. The environment wins so a deployment can be
# checked without editing its config -- and so this still works on a box whose
# .env does not carry the TEST_* convenience pair.
val() { [ -f .env ] && grep -E "^$1=" .env | tail -1 | cut -d= -f2- | tr -d '\r'; }

BASE="${TEST_BASE_URL:-$(val TEST_BASE_URL)}"
USER_KEY="${TEST_API_KEY:-$(val TEST_API_KEY)}"
STATIC_KEY="$(printf '%s' "${AUTH_API_KEYS:-$(val AUTH_API_KEYS)}" | cut -d, -f1)"
TEMPLATE="china-market-daily-brief"
ATTESTATION="securities_advisory"

if [ -z "$BASE" ]; then
  echo "ERROR: no base URL. Set TEST_BASE_URL in .env, or pass it:" >&2
  echo "       TEST_BASE_URL=https://www.dotslash.cn TEST_API_KEY=orc_... $0" >&2
  exit 1
fi
[ -n "$USER_KEY" ] || echo "WARNING: TEST_API_KEY not set — per-user checks will be skipped" >&2

PASS=0; FAIL=0; SKIP=0
ok()   { PASS=$((PASS+1)); printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  \033[31mFAIL\033[0m  %s\n       %s\n' "$1" "$2"; }
skip() { SKIP=$((SKIP+1)); printf '  \033[33mSKIP\033[0m  %s (%s)\n' "$1" "$2"; }
sec()  { printf '\n\033[1m%s\033[0m\n' "$1"; }

# code <method> <path> [key] -> prints the HTTP status
code() {
  local method="$1" path="$2" key="${3:-}" hdr=()
  [ -n "$key" ] && hdr=(-H "Authorization: Bearer $key")
  curl -sS -o /dev/null -m 20 -w '%{http_code}' -X "$method" "${hdr[@]}" "$BASE$path" 2>/dev/null
}

# body <path> [key] -> prints the response body
body() {
  local path="$1" key="${2:-}" hdr=()
  [ -n "$key" ] && hdr=(-H "Authorization: Bearer $key")
  curl -sS -m 20 "${hdr[@]}" "$BASE$path" 2>/dev/null
}

expect() {  # expect <label> <expected-code> <actual-code>
  if [ "$3" = "$2" ]; then ok "$1"; else bad "$1" "expected $2, got $3"; fi
}

echo "base : $BASE"
echo "keys : static=$([ -n "$STATIC_KEY" ] && echo yes || echo no)  user=$([ -n "$USER_KEY" ] && echo yes || echo no)"
[ "$WRITE" = 1 ] && echo "mode : WRITE (attestation accept/withdraw)"
[ "$DO_RUN" = 1 ] && echo "mode : RUN — this starts a real run and spends tokens"

# ── §1/§2 Reachability and authentication ────────────────────────────────────
sec "§2  Authentication"

expect "health is public"                200 "$(code GET /health)"
expect "no key is refused"               401 "$(code GET /api/v1/templates)"
expect "a wrong key is refused"          401 "$(code GET /api/v1/templates wrong-key-entirely)"

if [ -n "$STATIC_KEY" ]; then
  expect "the static key authenticates"  200 "$(code GET /api/v1/templates "$STATIC_KEY")"
else
  skip "the static key authenticates" "AUTH_API_KEYS empty"
fi

if [ -n "$USER_KEY" ]; then
  expect "the issued key authenticates"  200 "$(code GET /api/v1/templates "$USER_KEY")"
else
  skip "the issued key authenticates" "TEST_API_KEY empty"
fi

KEY="${USER_KEY:-$STATIC_KEY}"
[ -n "$KEY" ] || { echo; echo "No usable key — cannot continue."; exit 1; }

# ── §5 Templates ─────────────────────────────────────────────────────────────
sec "§5  Templates"

TPL="$(body "/api/v1/templates" "$KEY")"
case "$TPL" in
  *"$TEMPLATE"*) ok "the catalog lists $TEMPLATE" ;;
  *) bad "the catalog lists $TEMPLATE" "not found in the response" ;;
esac
case "$TPL" in
  *'"pipeline"'*) bad "the pipeline never leaves the server" "a 'pipeline' key is present — this is the product" ;;
  *) ok "the pipeline never leaves the server" ;;
esac
case "$TPL" in
  *'"requires"'*) ok "templates declare their requirements (OR-40)" ;;
  *) bad "templates declare their requirements (OR-40)" "no 'requires' key — is the deploy current?" ;;
esac

expect "an unknown template is 404"      404 "$(code GET /api/v1/templates/no-such-template "$KEY")"

# ── §6 Attestations ──────────────────────────────────────────────────────────
sec "§6  Attestations"

ATT="$(body /api/v1/attestations "$KEY")"
case "$ATT" in
  *"$ATTESTATION"*) ok "the attestation catalog is readable" ;;
  *) bad "the attestation catalog is readable" "$ATTESTATION not present" ;;
esac

VERSION="$(printf '%s' "$ATT" | grep -o '"version":"[^"]*"' | head -1 | cut -d'"' -f4)"
[ -n "$VERSION" ] && ok "current version is $VERSION" || bad "attestation version readable" "could not parse it"

ACCEPTED="$(printf '%s' "$ATT" | grep -o '"accepted":[a-z]*' | head -1 | cut -d: -f2)"
echo "        (currently accepted: ${ACCEPTED:-unknown})"

if [ -n "$USER_KEY" ]; then
  expect "a bad version is refused"      409 \
    "$(curl -sS -o /dev/null -m 20 -w '%{http_code}' -X POST \
        -H "Authorization: Bearer $USER_KEY" -H 'Content-Type: application/json' \
        -d '{"version":"definitely-not-a-version"}' \
        "$BASE/api/v1/attestations/$ATTESTATION/accept" 2>/dev/null)"
else
  skip "a bad version is refused" "needs a per-user key"
fi

# ── §7/§8 Runs, budget ───────────────────────────────────────────────────────
sec "§7/§8  Runs and budget"

expect "the run list is readable"        200 "$(code GET /api/v1/runs "$KEY")"
expect "budget usage is readable"        200 "$(code GET /api/v1/budget/usage "$KEY")"

# ── §3 Profile ───────────────────────────────────────────────────────────────
sec "§3  Profile surface"

AGENTS="$(code GET /api/v1/agents "$KEY")"
if [ "$AGENTS" = "403" ]; then
  echo "        profile appears to be 'app' (authoring is refused)"
  expect "agents are refused"            403 "$AGENTS"
  expect "workflow-maker is refused"     403 "$(code GET /api/v1/workflow-maker "$KEY")"
  expect "skill-writer is refused"       403 "$(code GET /api/v1/skill-writer "$KEY")"
  expect "marketplace is refused"        403 "$(code GET /api/v1/marketplace "$KEY")"
  expect "spans are refused"             403 "$(code GET /api/v1/runs/x/spans "$KEY")"
else
  echo "        profile appears to be 'full' (PRODUCT_PROFILE unset or 'full')"
  skip "the run-only allowlist" "set PRODUCT_PROFILE=app and force-recreate to test §3"
fi

# ── Writes ───────────────────────────────────────────────────────────────────
if [ "$WRITE" = 1 ] && [ -n "$USER_KEY" ]; then
  sec "§6  Attestation gate (write)"

  curl -sS -o /dev/null -m 20 -X POST -H "Authorization: Bearer $USER_KEY" \
    "$BASE/api/v1/attestations/$ATTESTATION/withdraw" 2>/dev/null
  expect "gated template refused without it" 403 \
    "$(curl -sS -o /dev/null -m 20 -w '%{http_code}' -X POST \
        -H "Authorization: Bearer $USER_KEY" -H 'Content-Type: application/json' \
        -d '{"inputs":{}}' "$BASE/api/v1/templates/$TEMPLATE/run" 2>/dev/null)"

  expect "accepting the current version"   201 \
    "$(curl -sS -o /dev/null -m 20 -w '%{http_code}' -X POST \
        -H "Authorization: Bearer $USER_KEY" -H 'Content-Type: application/json' \
        -d "{\"version\":\"$VERSION\"}" \
        "$BASE/api/v1/attestations/$ATTESTATION/accept" 2>/dev/null)"

  if [ "$DO_RUN" = 1 ]; then
    RESP="$(curl -sS -m 30 -X POST -H "Authorization: Bearer $USER_KEY" \
        -H 'Content-Type: application/json' -d '{"inputs":{},"force":true}' \
        "$BASE/api/v1/templates/$TEMPLATE/run" 2>/dev/null)"
    RUN_ID="$(printf '%s' "$RESP" | grep -o '"run_id":"[^"]*"' | cut -d'"' -f4)"
    if [ -n "$RUN_ID" ]; then
      ok "the run started once accepted ($RUN_ID)"
      # Cancel immediately: the point is the gate, not the output, and this
      # template is a multi-agent DAG that costs real money to finish.
      sleep 2
      expect "and can be cancelled"        200 \
        "$(code POST "/api/v1/runs/$RUN_ID/cancel" "$USER_KEY")"
    else
      bad "the run started once accepted" "no run_id in: $(printf '%s' "$RESP" | head -c 160)"
    fi
  else
    skip "starting a run" "pass --run (it spends tokens)"
  fi

  expect "withdrawing revokes it"          200 \
    "$(code POST "/api/v1/attestations/$ATTESTATION/withdraw" "$USER_KEY")"
  expect "and the template locks again"    403 \
    "$(curl -sS -o /dev/null -m 20 -w '%{http_code}' -X POST \
        -H "Authorization: Bearer $USER_KEY" -H 'Content-Type: application/json' \
        -d '{"inputs":{}}' "$BASE/api/v1/templates/$TEMPLATE/run" 2>/dev/null)"
elif [ "$WRITE" = 1 ]; then
  sec "§6  Attestation gate (write)"
  skip "the whole write section" "needs TEST_API_KEY, a per-user key"
fi

# ── Summary ──────────────────────────────────────────────────────────────────
printf '\n\033[1m%d passed, %d failed, %d skipped\033[0m\n' "$PASS" "$FAIL" "$SKIP"
echo
echo "Still manual (each needs a .env change + 'docker compose up -d --force-recreate backend'):"
echo "  §3  PRODUCT_PROFILE=app        the run-only allowlist"
echo "  §4  SKILLS_ALLOW / MODELS_ALLOW  capability ceilings"
echo "  §7  PLAN_REQUIRED=true         no plan, no access"
echo "  §9  SSE through nginx          curl -N on /runs/{id}/stream"
echo "  §11 per-span cost              needs a completed DAG run"
[ "$FAIL" -eq 0 ]
