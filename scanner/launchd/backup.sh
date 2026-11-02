#!/bin/zsh
# One backup of the state database and config (python -m scanner.backup) into
# $JOB_SCANNER_HOME/backups. launchd starts this once a day; see backup.plist.template.
# The env file is not read: a backup needs no secrets.
set -e
REPO="${0:A:h:h:h}"
export JOB_SCANNER_HOME="${JOB_SCANNER_HOME:-$HOME/.job-scanner}"
cd "$REPO"
exec "$REPO/.venv/bin/python" -m scanner.backup
