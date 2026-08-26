# ── Build stage ────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

# Ordered mirror chains — each is tried in turn, first one that works wins.
# Defaults are CN-first (Aliyun → Tsinghua → upstream) because this deploys in
# mainland China; override in .env to flip the order elsewhere.
ARG PIP_INDEX_URLS="https://pypi.org/simple https://mirrors.aliyun.com/pypi/simple/"
ARG APT_MIRRORS="deb.debian.org mirrors.aliyun.com"

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120

WORKDIR /build

# apt has no built-in mirror fallback, so restore pristine sources and retry
# `apt-get update` against each mirror in turn. bookworm ships the deb822
# sources file; older bases use the flat sources.list.
RUN set -eu; \
    src=/etc/apt/sources.list.d/debian.sources; \
    [ -f "$src" ] || src=/etc/apt/sources.list; \
    cp "$src" /tmp/sources.orig; \
    ok=0; \
    for m in $APT_MIRRORS; do \
      cp /tmp/sources.orig "$src"; \
      sed -i "s|deb.debian.org|$m|g; s|security.debian.org|$m|g" "$src"; \
      echo "apt: trying $m"; \
      if apt-get update -o Acquire::Retries=2; then ok=1; break; fi; \
      echo "apt: $m failed, falling back" >&2; \
    done; \
    [ "$ok" = 1 ] || { echo "apt: every mirror failed" >&2; exit 1; }; \
    apt-get install -y --no-install-recommends build-essential; \
    rm -rf /var/lib/apt/lists/* /tmp/sources.orig

COPY requirements.txt .

# --trusted-host is added only for http:// indexes (e.g. Aliyun's intranet
# endpoint), which have no TLS to verify in the first place.
RUN set -eu; \
    for idx in $PIP_INDEX_URLS; do \
      case "$idx" in \
        http://*) th="--trusted-host $(printf '%s' "$idx" | sed -E 's|^http://([^/]+).*|\1|')" ;; \
        *) th="" ;; \
      esac; \
      echo "pip: trying $idx"; \
      if pip install --no-cache-dir --prefix=/install -i "$idx" $th -r requirements.txt; then \
        exit 0; \
      fi; \
      echo "pip: $idx failed, falling back" >&2; \
    done; \
    echo "pip: every index failed" >&2; exit 1

# ── Runtime stage ──────────────────────────────────────────────────────────────
FROM python:3.11-slim

# ARGs do not cross stage boundaries — redeclare what this stage needs.
ARG APT_MIRRORS="deb.debian.org mirrors.aliyun.com"
ARG NODE_MIRRORS="https://nodejs.org/dist https://mirrors.aliyun.com/nodejs-release"
ARG NODE_VERSION=20.18.1
# Runtime installers read these; keep the single-value vars equal to the first
# entry of their list, for anything that only understands the conventional name.
ARG PIP_INDEX_URLS="https://pypi.org/simple https://mirrors.aliyun.com/pypi/simple/"
ARG PIP_INDEX_URL="https://pypi.org/simple"
ARG NPM_REGISTRIES="https://registry.npmjs.org https://registry.npmmirror.com"
ARG NPM_REGISTRY="https://registry.npmjs.org"

RUN set -eu; \
    src=/etc/apt/sources.list.d/debian.sources; \
    [ -f "$src" ] || src=/etc/apt/sources.list; \
    cp "$src" /tmp/sources.orig; \
    ok=0; \
    for m in $APT_MIRRORS; do \
      cp /tmp/sources.orig "$src"; \
      sed -i "s|deb.debian.org|$m|g; s|security.debian.org|$m|g" "$src"; \
      echo "apt: trying $m"; \
      if apt-get update -o Acquire::Retries=2; then ok=1; break; fi; \
      echo "apt: $m failed, falling back" >&2; \
    done; \
    [ "$ok" = 1 ] || { echo "apt: every mirror failed" >&2; exit 1; }; \
    apt-get install -y --no-install-recommends curl xz-utils; \
    rm -rf /var/lib/apt/lists/* /tmp/sources.orig

# Install Node.js (for npm — marketplace package installs). deb.nodesource.com
# has no CN mirror, so prefer the official binary tarball from NODE_MIRRORS
# (pinned to NODE_VERSION) and keep nodesource as the last resort.
RUN set -eu; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
      amd64) node_arch=x64 ;; \
      arm64) node_arch=arm64 ;; \
      *) echo "No Node.js tarball for architecture: $arch" >&2; exit 1 ;; \
    esac; \
    ok=0; \
    for m in $NODE_MIRRORS; do \
      url="$m/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${node_arch}.tar.xz"; \
      echo "node: trying $url"; \
      if curl -fsSL --max-time 180 -o /tmp/node.tar.xz "$url"; then ok=1; break; fi; \
      echo "node: $m failed, falling back" >&2; \
    done; \
    if [ "$ok" = 1 ]; then \
      tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 \
          --exclude=CHANGELOG.md --exclude=LICENSE --exclude=README.md; \
      rm -f /tmp/node.tar.xz; \
    else \
      echo "node: all mirrors failed, falling back to nodesource" >&2; \
      curl -fsSL https://deb.nodesource.com/setup_20.x | bash -; \
      apt-get install -y --no-install-recommends nodejs; \
      rm -rf /var/lib/apt/lists/*; \
    fi; \
    node --version

WORKDIR /app

COPY --from=builder /install /usr/local
COPY . .

# alembic/ and alembic.ini live at the repo root and are bind-mounted by
# docker-compose (see volumes:). docker-entrypoint.sh runs `alembic upgrade head`
# before uvicorn; the alembic CLI comes from requirements.txt.

# The marketplace runs `npm install` as a subprocess of the app and walks
# NPM_REGISTRIES in order (see marketplace/service.py).
ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URLS="${PIP_INDEX_URLS}" \
    PIP_INDEX_URL="${PIP_INDEX_URL}" \
    NPM_REGISTRIES="${NPM_REGISTRIES}" \
    npm_config_registry="${NPM_REGISTRY}"

EXPOSE 8000

# Invoke via `sh` so the bind-mount from Windows hosts (no exec bit) still works.
ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]
