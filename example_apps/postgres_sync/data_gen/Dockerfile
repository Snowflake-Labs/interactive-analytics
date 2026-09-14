FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.9.13 /uv /uvx /usr/local/bin/

WORKDIR /app

COPY data_gen/pyproject.toml data_gen/uv.lock ./
RUN uv sync --frozen --no-dev

COPY data_gen/*.py ./
COPY .env pm.token ./

# ENTRYPOINT stays fixed; the service spec's `args` field overrides just the
# CMD portion (e.g. to run schema.py instead of generate.py for step 1).
ENTRYPOINT ["uv", "run"]
CMD ["generate.py", "--table", "all"]
