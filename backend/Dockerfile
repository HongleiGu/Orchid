# ── Build stage ────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime stage ──────────────────────────────────────────────────────────────
FROM python:3.11-slim

# Install Node.js (for npm — marketplace package installs)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /install /usr/local
COPY . .

# alembic/ and alembic.ini live at the repo root and are bind-mounted by
# docker-compose (see volumes:). docker-entrypoint.sh runs `alembic upgrade head`
# before uvicorn; the alembic CLI comes from requirements.txt.

ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Invoke via `sh` so the bind-mount from Windows hosts (no exec bit) still works.
ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]
