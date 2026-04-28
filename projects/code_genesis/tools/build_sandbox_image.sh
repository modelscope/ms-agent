#!/usr/bin/env bash
# Build sandbox image using Docker HTTP API (PyPI `docker`); Colima supplies the daemon.
# No Docker Desktop and no standalone `docker` CLI required.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
  exec "${VIRTUAL_ENV}/bin/python" "${SCRIPT_DIR}/build_sandbox_image.py" "$@"
fi
exec python3 "${SCRIPT_DIR}/build_sandbox_image.py" "$@"
