# Sourced by install.sh and uninstall.sh: sets PROFILE, and LABEL from
# [profile] launchd_label in the config (default "job-scanner").
REPO="${0:A:h:h:h}"
export JOB_SCANNER_HOME="${JOB_SCANNER_HOME:-$HOME/.job-scanner}"
PROFILE="$JOB_SCANNER_HOME"
LABEL=$(cd "$REPO" && .venv/bin/python -c \
  'from scanner.settings import load_config; print(load_config().get("profile", {}).get("launchd_label") or "job-scanner")')
[[ -n "$LABEL" ]] || { echo "could not read the label from the config" >&2; exit 1; }
