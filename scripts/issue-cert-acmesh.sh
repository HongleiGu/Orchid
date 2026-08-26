#!/usr/bin/env bash
# Issue a certificate with acme.sh, using the Aliyun DNS API (DNS-01).
#
#     ./scripts/issue-cert-acmesh.sh
#
# Why this instead of certbot's webroot flow: HTTP-01 needs Let's Encrypt to
# reach port 80 AND to resolve the domain from several vantage points, and that
# is what was failing (A-record timeouts, CAA SERVFAIL). DNS-01 driven by the
# Aliyun API removes the inbound requirement, and acme.sh defaults to ZeroSSL,
# which validates less aggressively than Let's Encrypt's multi-perspective
# checks. Renewal stays automatic because the API call is scriptable -- unlike
# certbot's --manual mode, which cannot be replayed.
#
# Certificates land in the same paths nginx already reads, so no nginx change.
set -euo pipefail

cd "$(dirname "$0")/.."

if docker compose version >/dev/null 2>&1; then
  DC="docker compose --profile prod --profile acme"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose --profile prod --profile acme"
else
  echo "ERROR: neither 'docker compose' nor 'docker-compose' found" >&2
  exit 1
fi

[ -f .env ] || { echo "ERROR: .env not found" >&2; exit 1; }
set -a
# shellcheck disable=SC1091
. ./.env
set +a

: "${DOMAIN:?set DOMAIN in .env}"
: "${ACME_EMAIL:?set ACME_EMAIL in .env}"
: "${ALI_KEY:?set ALI_KEY in .env - Aliyun RAM AccessKey ID with DNS permissions}"
: "${ALI_SECRET:?set ALI_SECRET in .env - the matching AccessKey Secret}"
DOMAIN_ALT="${DOMAIN_ALT:-}"
ACME_CA="${ACME_CA:-zerossl}"

DOMAIN_ARGS=(-d "$DOMAIN")
[ -n "$DOMAIN_ALT" ] && DOMAIN_ARGS+=(-d "$DOMAIN_ALT")

CERT_DIR="./nginx/certbot/conf"          # what nginx mounts as /etc/letsencrypt
LIVE_DIR="$CERT_DIR/live/$DOMAIN"
mkdir -p "$LIVE_DIR" ./nginx/acme

echo "CA      : $ACME_CA"
echo "Domains : $DOMAIN ${DOMAIN_ALT:+and $DOMAIN_ALT}"
echo "Contact : $ACME_EMAIL"
echo

# nginx will not start without a certificate file present, so make sure one
# exists before touching anything else.
if [ ! -s "$LIVE_DIR/fullchain.pem" ]; then
  echo "==> 1/4 no certificate yet - installing a throwaway so nginx can start"
  $DC run --rm --no-deps --entrypoint sh acme -c "openssl req -x509 -nodes -newkey rsa:2048 -days 1 -keyout /certs/live/$DOMAIN/privkey.pem -out /certs/live/$DOMAIN/fullchain.pem -subj /CN=$DOMAIN" 2>&1 | sed 's/^/    /'
else
  echo "==> 1/4 certificate already present, leaving it in place"
fi

echo "==> 2/4 starting nginx"
$DC up -d nginx

echo "==> 3/4 registering with $ACME_CA and issuing via Aliyun DNS API"
# ZeroSSL requires an EAB binding; acme.sh fetches it from the email. Harmless
# for the other CAs, and idempotent once registered.
$DC run --rm --no-deps acme --register-account -m "$ACME_EMAIL" --server "$ACME_CA"
# Extra args pass through, so a failure can be re-run as:
#     ./scripts/issue-cert-acmesh.sh --debug 2
# which is what surfaces the DNS provider's actual error code.
$DC run --rm --no-deps acme --issue --dns dns_ali --server "$ACME_CA" "${DOMAIN_ARGS[@]}" "$@"

echo "==> 4/4 installing the certificate where nginx reads it"
# --reloadcmd is deliberately a no-op: the acme container cannot signal nginx in
# another container, and nginx already reloads itself every 6h (see its command
# in docker-compose.yml), so a renewed cert is picked up without help.
$DC run --rm --no-deps acme --install-cert -d "$DOMAIN" \
  --key-file "/certs/live/$DOMAIN/privkey.pem" \
  --fullchain-file "/certs/live/$DOMAIN/fullchain.pem" \
  --reloadcmd "true"

$DC exec nginx nginx -s reload

echo
echo "Done. Verify with:"
echo "  curl -vI https://$DOMAIN 2>&1 | grep -E 'issuer|subject|HTTP/'"
echo
echo "Renewal: start the acme daemon so it renews unattended --"
echo "  COMPOSE_PROFILES=prod,acme docker compose up -d"
