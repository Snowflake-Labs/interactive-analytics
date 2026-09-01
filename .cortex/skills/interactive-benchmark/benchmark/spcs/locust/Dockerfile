# Locust load test image for the benchmark API.
FROM python:3.12-slim

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

COPY benchmark/locust/pyproject.toml benchmark/locust/uv.lock /app/
RUN uv sync --frozen --no-dev --no-install-project

COPY benchmark/locust/locustfile.py /app/

# Include benchmark queries so locust can read them.
COPY benchmark/test/ /app/test/

COPY benchmark/spcs/locust/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8089

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
