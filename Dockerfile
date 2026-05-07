FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DB_PATH=/data/balanceamento.db \
    FLASK_DEBUG=0 \
    PORT=8080

WORKDIR /app

# System deps (build tools removed after install for smaller image)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persistent data dir (mounted volume in production)
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8080

# Healthcheck (Fly uses HTTP probe, but useful for local docker run too)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:${PORT}/api/stats || exit 1

# Production WSGI server (gunicorn)
# Workers: 2 = enough for SQLite single-write contention
# Threads: 4 per worker = ~8 concurrent requests
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 60 --access-logfile - --error-logfile - app:app"]
