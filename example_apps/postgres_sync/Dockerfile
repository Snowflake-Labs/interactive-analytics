FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.9.13 /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY check_env.py ./
COPY .env pm.token ./

CMD ["uv", "run", "check_env.py"]
