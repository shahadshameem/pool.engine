# ==============================================================================
# Multi-stage Dockerfile for Pool Engine API Service
# Provider-independent, unprivileged, reproducible container build.
# ==============================================================================

# Stage 1: Build wheels and compile dependencies
FROM python:3.13-slim AS builder

WORKDIR /build

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc python3-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip wheel --no-cache-dir --wheel-dir=/build/wheels ".[postgres,service]"

# Stage 2: Minimal runtime image
FROM python:3.13-slim AS runtime

# Create dedicated non-root application user and group
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /sbin/nologin -d /app appuser

WORKDIR /app

# Install pre-built wheels from builder stage
COPY --from=builder /build/wheels /wheels
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir /wheels/*.whl && \
    rm -rf /wheels

# Copy application source, configuration, and maintenance scripts
COPY src/ /app/src/
COPY scripts/ /app/scripts/
COPY config/ /app/config/

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SERVICE_HOST=0.0.0.0 \
    SERVICE_PORT=8000

# Drop all privileges
USER 10001:10001

EXPOSE 8000

# In-container liveness healthcheck without external curl dependency
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/health/liveness')" || exit 1

ENTRYPOINT ["uvicorn", "engine.service.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
