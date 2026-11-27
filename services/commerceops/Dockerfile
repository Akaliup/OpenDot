# Build context is services/commerceops.
FROM python:3.12-slim AS build

WORKDIR /src
COPY pyproject.toml README.md ./
COPY commerceops ./commerceops
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim

COPY --from=build /install /usr/local
RUN useradd --create-home --uid 10001 commerceops \
    && mkdir -p /data \
    && chown -R commerceops:commerceops /data

ENV PYTHONUNBUFFERED=1 \
    COMMERCEOPS_HOST=0.0.0.0 \
    COMMERCEOPS_PORT=8077 \
    COMMERCEOPS_AUTO_SEED=1 \
    COMMERCEOPS_DATABASE_URL=sqlite:////data/commerceops.db \
    COMMERCEOPS_NOTIFY_LOG=/data/notifications.jsonl \
    COMMERCEOPS_EVAL_DIR=/data/evals

USER commerceops
WORKDIR /data
EXPOSE 8077

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8077/health', timeout=2).read()"]

CMD ["commerceops-api"]
