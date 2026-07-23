# TPC-H Benchmark API image for SPCS.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:/root/.local/bin:$PATH

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && curl -LsSf https://astral.sh/uv/install.sh | sh

WORKDIR /app

# Install deps first for good layer caching.
COPY api/pyproject.toml api/uv.lock /app/api/
RUN cd /app/api && uv sync --frozen --no-dev --no-install-project

# App code + benchmark SQL.
COPY api/ /app/api/
COPY sql/ /app/sql/

# Entrypoint writes ~/.snowflake/connections.toml from SPCS-injected env vars,
# then execs uvicorn via the project's server.py.
COPY spcs/dashboard/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 3000

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
