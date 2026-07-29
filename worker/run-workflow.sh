#!/usr/bin/env bash
# Запускает только конечный автомат утверждённого workflow.
set -Eeuo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$root/worker/workflow_runner.py" --repo "$root" "$@"
