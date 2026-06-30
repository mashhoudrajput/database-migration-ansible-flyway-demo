# ── Build stage ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Non-root user for security
RUN useradd -m -u 1001 appuser

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source and demo UI
COPY app/ ./app/
COPY static/ ./static/

USER appuser

# Cloud Run injects PORT; default to 8080
ENV PORT=8080
EXPOSE 8080

# exec form so SIGTERM reaches uvicorn (graceful shutdown)
CMD exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --workers 1 \
    --log-config /dev/null \
    --no-access-log
