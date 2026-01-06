FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps (kept minimal). Some python wheels (numpy/pandas) are available prebuilt,
# but build tools help when wheels are unavailable for the target platform.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install python deps first for better layer caching
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy application code
COPY backend/ /app/backend/

# Default: SQLite file will be resolved relative to BASE_DIR (see config.py).
# In containers, you typically want to set DATABASE_URL to an absolute path, e.g.
# sqlite+aiosqlite:////data/demo.db and mount /data.

EXPOSE 8088

WORKDIR /app/backend

# Note: For K8s multi-replica deployments, consider setting ENABLE_SCHEDULER=false
# (or keep replicas=1) to avoid duplicated scheduled jobs.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088"]
