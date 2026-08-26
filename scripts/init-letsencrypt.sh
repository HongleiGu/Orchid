#!/usr/bin/env bash
# One-time Let's Encrypt bootstrap. Run on the server, from the repo root:
#
#     ./scripts/init-letsencrypt.sh
#
# Chicken-and-egg: nginx refuses to start when ssl_certificate points at a
# missing file, and Let's Encrypt cannot issue a certificate until nginx is
# answering the HTTP-01 challenge on port 80. So we install a throwaway
# self-signed cert, start nginx, swap in the real one, and reload.
#
# Renewal is NOT handled here — the certbot service in docker-compose.yml
# renews on a 12h loop and nginx reloads every 6h to pick up new certs.
set -euo pipefail

cd "$(dirname "$0")/.."

# Both profiles: nginx is in "prod", certbot is in "tls". Naming only "prod"
# would leave certbot outside the active set.
if docker compose version >/dev/null 2>&1; then
  DC="docker compose --profile prod --profile tls"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose --profile prod --profile tls"
else
  echo "ERROR: neither 'docker compose' nor 'docker-compose' found" >&2
  exit 1
fi

[ -f .env ] || { echo "ERROR: .env not found — copy .env.example first" >&2; exit 1; }
set -a
# shellcheck disable=SC1091
. ./.env
set +a

: "${DOMAIN:?set DOMAIN in .env (e.g. www.dotslash.cn)}"
: "${CERTBOT_EMAIL:?set CERTBOT_EMAIL in .env — the ACME contact address for expiry warnings}"
DOMAIN_ALT="${DOMAIN_ALT:-}"
CERTBOT_STAGING="${CERTBOT_STAGING:-1}"
# webroot    = HTTP-01, fully automatic, renews unattended.
# manual-dns = DNS-01, prints a TXT record for you to add by hand.
CERTBOT_MODE="${CERTBOT_MODE:-webroot}"

CERT_ROOT="./nginx/certbot/conf"
LIVE_DIR="$CERT_ROOT/live/$DOMAIN"

DOMAIN_ARGS=(-d "$DOMAIN")
[ -n "$DOMAIN_ALT" ] && DOMAIN_ARGS+=(-d "$DOMAIN_ALT")

case "$CERTBOT_MODE" in
  webroot|manual-dns) ;;
  *) echo "CERTBOT_MODE must be webroot or manual-dns (got: $CERTBOT_MODE)" >&2; exit 2 ;;
esac

STAGING_ARGS=()
if [ "$CERTBOT_STAGING" = "1" ]; then
  STAGING_ARGS=(--staging)
  echo "NOTE: using Let's Encrypt STAGING. The certificate will NOT be trusted by"
  echo "      browsers. Staging exists so a misconfiguration does not burn the"
  echo "      production rate limit (5 failures/hour, 50 certs/week per domain)."
  echo "      Once this succeeds, set CERTBOT_STAGING=0 in .env and re-run."
else
  echo "NOTE: using Let's Encrypt PRODUCTION. Failures count against a rate limit"
  echo "      of 5 per hour for this domain."
fi
echo

echo "Domain(s): $DOMAIN ${DOMAIN_ALT:+and $DOMAIN_ALT}"
echo "Contact  : $CERTBOT_EMAIL"
echo

# ── Preflight: DNS ───────────────────────────────────────────────────────────
# The overwhelmingly common failure is DNS not pointing here yet, which shows up
# as an opaque "Timeout during connect" from the ACME server.
if command -v getent >/dev/null 2>&1; then
  resolved="$(getent hosts "$DOMAIN" | awk '{print $1}' | head -1 || true)"
  if [ -z "$resolved" ]; then
    echo "WARNING: $DOMAIN does not resolve from this host. Issuance will fail"
    echo "         unless public DNS has an A record pointing at this server."
    echo
  else
    echo "DNS: $DOMAIN -> $resolved"
    echo "     Confirm that is this server's public IP before continuing."
    echo
  fi
fi

if [ -d "$LIVE_DIR" ]; then
  read -r -p "A certificate for $DOMAIN already exists. Replace it? [y/N] " reply
  case "$reply" in
    [yY]*) ;;
    *) echo "Aborted."; exit 0 ;;
  esac
fi

mkdir -p "$CERT_ROOT" ./nginx/certbot/www

# nginx cannot start when ssl_certificate points at a missing file, so a
# throwaway cert has to exist before nginx comes up -- and has to be put back
# if issuance fails, otherwise a failed run leaves nginx unable to boot at all.
make_dummy_cert() {
  mkdir -p "$LIVE_DIR"
  $DC run --rm --no-deps --entrypoint sh certbot -c "openssl req -x509 -nodes -newkey rsa:2048 -days 1 -keyout /etc/letsencrypt/live/$DOMAIN/privkey.pem -out /etc/letsencrypt/live/$DOMAIN/fullchain.pem -subj /CN=$DOMAIN" 2>&1 | sed "s/^/    /"
}

echo "==> 1/5 installing throwaway self-signed cert so nginx can start"
make_dummy_cert

echo "==> 2/5 starting nginx"
$DC up -d nginx

echo "==> 3/5 removing throwaway cert"
$DC run --rm --no-deps --entrypoint sh certbot -c "rm -rf /etc/letsencrypt/live/$DOMAIN /etc/letsencrypt/archive/$DOMAIN /etc/letsencrypt/renewal/$DOMAIN.conf"

echo "==> 4/5 requesting certificate from Let's Encrypt ($CERTBOT_MODE)"
if [ "$CERTBOT_MODE" = "manual-dns" ]; then
  echo
  echo "certbot will pause and print a TXT record per domain. Add each one in" >&2
  echo "your DNS console, WAIT for it to be visible from a public resolver, then" >&2
  echo "press Enter. Checking before you continue avoids a failed validation:" >&2
  echo "    dig +short TXT _acme-challenge.$DOMAIN @8.8.8.8" >&2
  echo
  echo "Note: certificates issued this way do NOT renew automatically -- the" >&2
  echo "certbot container cannot replay a manual step. Re-run this script before" >&2
  echo "the 90-day expiry, or move back to CERTBOT_MODE=webroot once DNS is sound." >&2
  echo
  # No --non-interactive and no -T: certbot must be able to prompt.
  CERTBOT_CMD=(certonly --manual --preferred-challenges dns)
else
  CERTBOT_CMD=(certonly --webroot -w /var/www/certbot --non-interactive)
fi

if ! $DC run --rm --no-deps --entrypoint certbot certbot "${CERTBOT_CMD[@]}" "${STAGING_ARGS[@]}" "${DOMAIN_ARGS[@]}" --email "$CERTBOT_EMAIL" --agree-tos --no-eff-email; then
  echo >&2
  echo "Issuance failed. Restoring the throwaway cert so nginx can still run," >&2
  echo "then restarting it -- otherwise nginx is left unable to start at all." >&2
  make_dummy_cert
  $DC up -d --force-recreate nginx
  echo >&2
  echo "nginx is serving again on port 80 with an untrusted cert, so the ACME" >&2
  echo "challenge path stays testable. Re-run this script once the cause is fixed." >&2
  exit 1
fi

echo "==> 5/5 reloading nginx"
$DC exec nginx nginx -s reload

echo
echo "Done. Bring the whole stack up with:  $DC up -d"
if [ "$CERTBOT_STAGING" = "1" ]; then
  echo
  echo "Reminder: that was a STAGING certificate. Set CERTBOT_STAGING=0 in .env"
  echo "and re-run this script to get a browser-trusted one."
fi
