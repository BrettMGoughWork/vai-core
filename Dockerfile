# S4.9.2 — Stratum-4 Container Image
#
# Reproducible, single-process OCI image for running S4 in a container.
# Cloud deployment is acknowledged but intentionally deferred.
#
# Build:
#   docker build -t s4:latest .
#
# Run:
#   docker run --rm -it s4:latest

# ---- Pinned base -----------------------------------------------------------
FROM python:3.12-slim-bookworm AS base

LABEL org.opencontainers.image.title="Stratum-4"
LABEL org.opencontainers.image.description="Platform runtime for the vai-core agent system"
LABEL org.opencontainers.image.source="https://github.com/BrettMGoughWork/vai-core"

# Prevent Python from buffering logs and writing .pyc files
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ---- Dependency layer (leverages Docker cache) ------------------------------
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- Application layer ------------------------------------------------------
COPY src/ src/
COPY config/config.yaml /app/config/config.yaml

# ---- Entrypoint -------------------------------------------------------------
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
