#!/bin/bash
#
# entrypoint.sh — Stratum-4 container entrypoint.
#
# Loads configuration, starts the S4 daemon and worker pool,
# and blocks until shutdown.  Handles SIGTERM for graceful
# container shutdown.
#
# S4.9.2 — Deployment Targets (container mode).

set -euo pipefail

# Default config path; override with S4_CONFIG_FILE env var.
CONFIG_FILE="${S4_CONFIG_FILE:-/app/config/config.yaml}"

echo "[entrypoint] Starting Stratum-4 (container mode)"
echo "[entrypoint] Config: ${CONFIG_FILE}"

# exec replaces PID 1 so that signals (SIGTERM etc.) reach Python directly.
exec python -m src.platform.deployment \
    --mode container \
    --config-file "${CONFIG_FILE}"
