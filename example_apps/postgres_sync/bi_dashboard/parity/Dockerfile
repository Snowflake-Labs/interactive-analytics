FROM python:3.12-slim
RUN pip install --no-cache-dir psycopg2-binary==2.9.10
WORKDIR /app
COPY check_parity.py ./
COPY config.py ./
# .env and config.py are copied in from the parent directory (see README) so the
# job reads exactly the same configuration as everything else.
COPY .env ./
CMD ["python", "-u", "check_parity.py"]
