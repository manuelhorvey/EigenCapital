FROM python:3.14-slim AS base

WORKDIR /app

# System deps: build tools + Wine for optional MT5 bridge
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --ingroup appgroup appuser

FROM base AS runtime

COPY . .

EXPOSE 5000 9879

ENV PYTHONPATH=/app
ENV EIGENCAPITAL_BIND=127.0.0.1

USER appuser

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/ping', timeout=5)" || exit 1

ENTRYPOINT ["python3", "paper_trading/ops/monitor.py"]
