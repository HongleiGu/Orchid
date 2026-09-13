# Orchid Console — built once, then served as static files by nginx.
#
# Registry chain as in frontend/Dockerfile: each entry is probed in turn and the
# first usable one is written to .npmrc. Upstream-first by default; the
# docker-compose.cn.yml overlay flips it to npmmirror for mainland hosts.
# Never pnpm@latest: `corepack install` reads the pinned packageManager.

FROM node:20-alpine AS build
ARG NPM_REGISTRIES="https://registry.npmjs.org https://registry.npmmirror.com"
WORKDIR /src
RUN set -eu; \
    for r in $NPM_REGISTRIES; do \
      echo "npm: trying $r"; \
      if wget -q -T 10 -O /dev/null "$r/pnpm" \
         && COREPACK_NPM_REGISTRY="$r" corepack enable \
         && COREPACK_NPM_REGISTRY="$r" corepack install -g pnpm@10.34.5; then \
        printf 'registry=%s\n' "$r" > /root/.npmrc; \
        pnpm --version; \
        exit 0; \
      fi; \
      echo "npm: $r failed, falling back" >&2; \
    done; \
    echo "npm: no usable registry" >&2; exit 1

# Manifests first, so a source edit does not invalidate the dependency layer.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY packages/core/package.json packages/core/
COPY apps/console/package.json apps/console/
RUN pnpm install --frozen-lockfile

COPY . .
# Tests gate the image: the stream client is exactly what reaches production.
RUN pnpm --filter @orchid/client-core test \
 && pnpm --filter @orchid/console build

FROM nginx:1.27-alpine
COPY --from=build /src/apps/console/dist /usr/share/nginx/html/console
COPY nginx/console.conf /etc/nginx/conf.d/default.conf
COPY nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
EXPOSE 80
