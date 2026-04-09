# --- Stage 1: Build Environment ---
FROM python:3.12-slim AS builder

# Prevent Python from writing .pyc files and ensure output is sent to terminal.
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev \
    libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Install dependencies into a wheels directory for easy copying.
# Include transitive dependencies so runtime install can stay offline.
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /build/wheels -r requirements.txt


# --- Stage 2: Runtime Environment ---
FROM python:3.12-slim

# Build arguments for non-root user
ARG USER_ID=10001
ARG GROUP_ID=10001

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/home/appuser/.local/bin:${PATH}"

# Install only runtime libraries (minimal dependencies)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 \
    libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user and group
RUN addgroup --gid "$GROUP_ID" appgroup && \
    adduser --disabled-password --gecos '' --uid "$USER_ID" --gid "$GROUP_ID" appuser

WORKDIR /app

# Copy wheels from builder stage and install
COPY --from=builder /build/wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

# Copy application source code
COPY . .

# Initialize directories and set ownership
RUN mkdir -p /app/data /app/output /app/logs && \
    chown -R appuser:appgroup /app/data /app/output /app/logs /app

USER appuser

# Entrypoint for the ETL process
ENTRYPOINT ["python", "main.py"]
CMD []
