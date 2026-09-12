# Shell variables for poking at a running deployment. Source it, don't run it:
#
#     source scripts/testenv.sh
#     curl -H "$H" $BASE/api/v1/templates
#
# Sets BASE, KEY (a per-user issued key), AUTH_KEY (the static operator key)
# and H (a ready-made Authorization header).
#
# Not a docker-compose concern: these are for your shell, and the backend
# already receives AUTH_API_KEYS through env_file. Putting them in the
# container would not make them appear in your terminal.
#
# Note the two keys are not interchangeable. KEY carries a user identity, so
# plans, quotas and attestations apply to it. AUTH_KEY is the operator
# credential and bypasses all three, which makes it useless for testing any
# gate and the right thing to reach for when the database is unreachable.

_env_val() {
  [ -f .env ] || { echo "testenv: no .env in $(pwd)" >&2; return 1; }
  grep -E "^$1=" .env | tail -1 | cut -d= -f2- | tr -d '\r'
}

export BASE="$(_env_val TEST_BASE_URL)"
export KEY="$(_env_val TEST_API_KEY)"
export AUTH_KEY="$(_env_val AUTH_API_KEYS | cut -d, -f1)"
export H="Authorization: Bearer ${KEY:-$AUTH_KEY}"

unset -f _env_val

if [ -z "$BASE" ]; then
  echo "testenv: TEST_BASE_URL is not set in .env" >&2
else
  printf 'BASE     %s\n' "$BASE"
  # Prefixes only. Echoing a whole credential into the terminal puts it in
  # scrollback and shell history for anyone who later reads either.
  if [ -n "$KEY" ]; then
    printf 'KEY      %.10s… (per-user: plans and attestations apply)\n' "$KEY"
  else
    printf 'KEY      (unset — per-user checks will not work)\n'
  fi
  if [ -n "$AUTH_KEY" ]; then
    printf 'AUTH_KEY %.6s… (operator: bypasses plans and attestations)\n' "$AUTH_KEY"
  else
    printf 'AUTH_KEY (unset)\n'
  fi
fi
