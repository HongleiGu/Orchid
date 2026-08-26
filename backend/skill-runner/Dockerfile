FROM python:3.11-slim

# Ordered mirror chains — each is tried in turn, first one that works wins.
# CN-first by default; override in .env to flip the order elsewhere.
# PIP_INDEX_URLS persists into the running container on purpose: /install-deps
# shells out to pip at runtime and walks the same chain (see main.py).
ARG PIP_INDEX_URLS="https://pypi.org/simple https://mirrors.aliyun.com/pypi/simple/"
ARG PIP_INDEX_URL="https://pypi.org/simple"
ARG APT_MIRRORS="deb.debian.org mirrors.aliyun.com"

ENV PIP_INDEX_URLS="${PIP_INDEX_URLS}" \
    PIP_INDEX_URL="${PIP_INDEX_URL}" \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120

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
    apt-get install -y --no-install-recommends curl; \
    rm -rf /var/lib/apt/lists/* /tmp/sources.orig

WORKDIR /app

COPY requirements.txt .

RUN set -eu; \
    for idx in $PIP_INDEX_URLS; do \
      case "$idx" in \
        http://*) th="--trusted-host $(printf '%s' "$idx" | sed -E 's|^http://([^/]+).*|\1|')" ;; \
        *) th="" ;; \
      esac; \
      echo "pip: trying $idx"; \
      if pip install --no-cache-dir -i "$idx" $th -r requirements.txt; then exit 0; fi; \
      echo "pip: $idx failed, falling back" >&2; \
    done; \
    echo "pip: every index failed" >&2; exit 1

COPY . .

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 9000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9000"]
