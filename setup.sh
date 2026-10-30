#!/usr/bin/env bash
set -euo pipefail
dashboard_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
python3 -m venv "$dashboard_dir/.venv"
"$dashboard_dir/.venv/bin/python" -m pip install -r "$dashboard_dir/requirements.txt"
if [[ "${1:-}" != "--skip-assets" ]]; then
  "$dashboard_dir/.venv/bin/python" "$dashboard_dir/prepare_armory_assets.py"
  "$dashboard_dir/.venv/bin/python" "$dashboard_dir/prepare_quest_assets.py"
  "$dashboard_dir/.venv/bin/python" "$dashboard_dir/prepare_profession_assets.py"
  "$dashboard_dir/.venv/bin/python" "$dashboard_dir/prepare_gear_assets.py"
  "$dashboard_dir/.venv/bin/python" "$dashboard_dir/prepare_tooltip_assets.py"
fi
printf '%s\n' 'Setup complete. Run ./start.sh, then create your first group on the Dashboard.'
