# TPC-H Dashboard API image for SPCS.
# Multi-stage build using uv for fast reproducible installs.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:/root/.local/bin:$PATH

# uv gives us `uv sync --frozen` from the existing uv.lock.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && curl -LsSf https://astral.sh/uv/install.sh | sh

WORKDIR /app

# Install deps first for good layer caching.
COPY api/pyproject.toml api/uv.lock /app/api/
RUN cd /app/api && uv sync --frozen --no-dev --no-install-project

# App code + static assets.
COPY api/ /app/api/
COPY public/ /app/public/

# SPCS public ingress applies a strict CSP (default-src 'self'), so external
# CDN scripts (chart.js from jsdelivr) get blocked. Vendor them into
# /app/public/vendor/ and rewrite index.html to use relative paths.
RUN mkdir -p /app/public/vendor \
 && curl -fsSL -o /app/public/vendor/chart.umd.min.js \
      https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js \
 && curl -fsSL -o /app/public/vendor/chartjs-adapter-date-fns.bundle.min.js \
      https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3/dist/chartjs-adapter-date-fns.bundle.min.js \
 && sed -i \
      -e 's|https://cdn.jsdelivr.net/npm/chart.js@4|/static/vendor/chart.umd.min.js|g' \
      -e 's|https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3|/static/vendor/chartjs-adapter-date-fns.bundle.min.js|g' \
      /app/public/index.html

# Entrypoint writes ~/.snowflake/connections.toml from SPCS-injected env vars,
# then execs uvicorn via the project's server.py.
COPY spcs/dashboard/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 3000

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
