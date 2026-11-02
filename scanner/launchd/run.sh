#!/bin/zsh
# Run one scan. Secrets come from $JOB_SCANNER_HOME/env (default ~/.job-scanner/env):
# JOB_SCANNER_MAILER_DSN, JOB_SCANNER_MAIL_FROM. launchd starts this every 30 minutes.
set -e
REPO="${0:A:h:h:h}"
export JOB_SCANNER_HOME="${JOB_SCANNER_HOME:-$HOME/.job-scanner}"
[[ -f "$JOB_SCANNER_HOME/env" ]] && source "$JOB_SCANNER_HOME/env"
cd "$REPO"
echo "--- $(date "+%Y-%m-%d %H:%M")"
exec "$REPO/.venv/bin/python" -m scanner.run
