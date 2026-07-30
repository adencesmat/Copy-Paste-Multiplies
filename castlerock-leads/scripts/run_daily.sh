#!/usr/bin/env bash
# Daily runner for the Castle Rock lead pipeline. Intended for cron on the
# machine/server that will host it (must be able to reach the county sites).
#
# Example crontab entry (runs 07:00 America/Denver every day):
#   0 7 * * *  /path/to/castlerock-leads/scripts/run_daily.sh >> /path/to/cron.log 2>&1
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

# Use the project virtualenv if present, else system python.
if [[ -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# SMTP creds for the optional email digest come from the environment. Put them
# in a file readable only by this user and source it here if you use email:
#   [[ -f .env ]] && set -a && source .env && set +a
[[ -f .env ]] && { set -a; source .env; set +a; }

python -m castlerock_leads --config config.yaml run
