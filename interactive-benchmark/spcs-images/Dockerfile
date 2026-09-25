ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ARG SOURCE_URL=https://github.com/Snowflake-Labs/interactive-analytics
ARG SOURCE_REVISION=local
ARG OWNER_EMAIL=local-build
ARG OWNER_SLACK=local-build
ARG OWNER_TEAM=local-build
ARG JIRA_AREA=local-build
ARG JIRA_COMPONENT=local-build

LABEL org.opencontainers.image.source="${SOURCE_URL}" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      com.snowflake.owners.email="${OWNER_EMAIL}" \
      com.snowflake.owners.slack="${OWNER_SLACK}" \
      com.snowflake.owners.team="${OWNER_TEAM}" \
      com.snowflake.owners.jira_area="${JIRA_AREA}" \
      com.snowflake.owners.jira_component="${JIRA_COMPONENT}"

USER 0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH=/root/.local/bin:$PATH

RUN if ! command -v uv >/dev/null 2>&1; then \
      if command -v apt-get >/dev/null 2>&1; then \
        apt-get update \
        && apt-get install -y --no-install-recommends curl ca-certificates \
        && rm -rf /var/lib/apt/lists/*; \
      elif command -v apk >/dev/null 2>&1; then \
        apk add --no-cache curl ca-certificates; \
      else \
        echo "Base image must provide uv, apt-get, or apk" >&2; \
        exit 1; \
      fi; \
      curl -LsSf https://astral.sh/uv/install.sh | sh; \
    fi

WORKDIR /app

COPY api/pyproject.toml api/uv.lock /app/api/
RUN cd /app/api \
    && UV_PROJECT_ENVIRONMENT=/opt/venvs/api uv sync --frozen --no-dev --no-install-project

COPY locust/pyproject.toml locust/uv.lock /app/locust/
RUN cd /app/locust \
    && UV_PROJECT_ENVIRONMENT=/opt/venvs/locust uv sync --frozen --no-dev --no-install-project

COPY api/server.py api/entrypoint.sh /app/api/
COPY locust/locustfile.py locust/entrypoint.sh /app/locust/
COPY role-entrypoint.sh /usr/local/bin/benchmark-entrypoint

RUN chmod +x \
      /app/api/entrypoint.sh \
      /app/locust/entrypoint.sh \
      /usr/local/bin/benchmark-entrypoint

USER 65532:65532

EXPOSE 3000 8089

ENTRYPOINT ["/usr/local/bin/benchmark-entrypoint"]
