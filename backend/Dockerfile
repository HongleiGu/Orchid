# ── Build stage ────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

# Package mirrors. Defaults are the upstream registries, so builds outside
# mainland China are unchanged; docker-compose passes CN mirrors in from .env.
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG APT_MIRROR
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120

WORKDIR /build

# bookworm ships the deb822 sources file; older bases use the flat sources.list.
RUN if [ -n "$APT_MIRROR" ]; then \
        sed -i "s|deb.debian.org|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null \
        || sed -i "s|deb.debian.org|$APT_MIRROR|g" /etc/apt/sources.list; \
    fi

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime stage ──────────────────────────────────────────────────────────────
FROM python:3.11-slim

# ARGs do not cross stage boundaries — redeclare what this stage needs.
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG NPM_REGISTRY=https://registry.npmjs.org/
ARG APT_MIRROR
ARG NODE_MIRROR
ARG NODE_VERSION=20.18.1

RUN if [ -n "$APT_MIRROR" ]; then \
        sed -i "s|deb.debian.org|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null \
        || sed -i "s|deb.debian.org|$APT_MIRROR|g" /etc/apt/sources.list; \
    fi

# Install Node.js (for npm — marketplace package installs).
# deb.nodesource.com has no CN mirror and is effectively unreachable from
# mainland China; when NODE_MIRROR is set we take the official binary tarball
# from that mirror instead (pinned to NODE_VERSION).
RUN apt-get update && apt-get install -y --no-install-recommends curl xz-utils \
    && if [ -n "$NODE_MIRROR" ]; then \
         arch="$(dpkg --print-architecture)"; \
         case "$arch" in \
           amd64) node_arch=x64 ;; \
           arm64) node_arch=arm64 ;; \
           *) echo "No Node.js tarball for architecture: $arch" >&2; exit 1 ;; \
         esac; \
         curl -fsSL "${NODE_MIRROR}/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${node_arch}.tar.xz" \
           | tar -xJ -C /usr/local --strip-components=1 \
                 --exclude=CHANGELOG.md --exclude=LICENSE --exclude=README.md; \
       else \
         curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
         && apt-get install -y --no-install-recommends nodejs; \
       fi \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /install /usr/local
COPY . .

# alembic/ and alembic.ini live at the repo root and are bind-mounted by
# docker-compose (see volumes:). docker-entrypoint.sh runs `alembic upgrade head`
# before uvicorn; the alembic CLI comes from requirements.txt.

# The marketplace runs `npm install` as a subprocess of the app (see
# marketplace/service.py) — it inherits npm_config_registry from here.
ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    npm_config_registry=${NPM_REGISTRY}

EXPOSE 8000

# Invoke via `sh` so the bind-mount from Windows hosts (no exec bit) still works.
ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]
