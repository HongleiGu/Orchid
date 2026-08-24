# Ordered registry chain — probed in turn, first reachable one wins and is
# written to /root/.npmrc so pnpm picks it up. CN-first by default
# (npmmirror is Alibaba-operated); override in .env to flip the order.
# COREPACK_NPM_REGISTRY is separate from the .npmrc registry — corepack ignores
# .npmrc when fetching pnpm itself.

# ── Install deps ───────────────────────────────────────────────────────────────
FROM node:20-alpine AS deps
ARG NPM_REGISTRIES="https://registry.npmmirror.com https://registry.npmjs.org"
RUN set -eu; \
    for r in $NPM_REGISTRIES; do \
      echo "npm: trying $r"; \
      if wget -q -T 10 -O /dev/null "$r/pnpm" \
         && COREPACK_NPM_REGISTRY="$r" corepack enable \
         && COREPACK_NPM_REGISTRY="$r" corepack prepare pnpm@latest --activate; then \
        printf 'registry=%s\n' "$r" > /root/.npmrc; \
        exit 0; \
      fi; \
      echo "npm: $r failed, falling back" >&2; \
    done; \
    echo "npm: no usable registry" >&2; exit 1
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# ── Build ──────────────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder
ARG NPM_REGISTRIES="https://registry.npmmirror.com https://registry.npmjs.org"
RUN set -eu; \
    for r in $NPM_REGISTRIES; do \
      echo "npm: trying $r"; \
      if wget -q -T 10 -O /dev/null "$r/pnpm" \
         && COREPACK_NPM_REGISTRY="$r" corepack enable \
         && COREPACK_NPM_REGISTRY="$r" corepack prepare pnpm@latest --activate; then \
        printf 'registry=%s\n' "$r" > /root/.npmrc; \
        exit 0; \
      fi; \
      echo "npm: $r failed, falling back" >&2; \
    done; \
    echo "npm: no usable registry" >&2; exit 1
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# These are baked into the client bundle at build time
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_WS_URL=ws://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL

RUN pnpm build

# ── Runtime ────────────────────────────────────────────────────────────────────
FROM node:20-alpine
WORKDIR /app

COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

ENV PORT=3000
EXPOSE 3000

CMD ["node", "server.js"]
