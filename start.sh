#!/usr/bin/env bash
set -euo pipefail
dashboard_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
dashboard_python=python3
if [[ -x "$dashboard_dir/.venv/bin/python" ]]; then dashboard_python="$dashboard_dir/.venv/bin/python"; fi
"$dashboard_python" "$dashboard_dir/package_release.py" --if-changed
mkdir -p "$dashboard_dir/.run"
nohup "$dashboard_python" "$dashboard_dir/package_release.py" --watch >> "$dashboard_dir/.run/package-watch.log" 2>&1 < /dev/null &
exec "$dashboard_python" "$dashboard_dir/dashboard.py" "$@"
