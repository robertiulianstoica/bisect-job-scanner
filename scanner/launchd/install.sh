#!/bin/zsh
# Install (or reinstall) the launchd agents: a scan every 30 minutes (agent
# <label>), and a backup every day at 03:00 (agent <label>.backup). The label is
# [profile] launchd_label in the config; logs go to the profile directory,
# $JOB_SCANNER_HOME (default ~/.job-scanner).
#   install.sh                 both
#   install.sh --backup-only   the backup agent only; the scan agent is left as it is
set -e
HERE="${0:A:h}"
source "$HERE/label.sh"
mkdir -p "$PROFILE" "$HOME/Library/LaunchAgents"

install_agent() {  # label template script log
  local plist="$HOME/Library/LaunchAgents/$1.plist"
  # Never a second agent for the same script under another label.
  local other=$(grep -l -F "$HERE/$3<" "$HOME"/Library/LaunchAgents/*.plist 2>/dev/null | grep -v -F "/$1.plist" | head -1)
  if [[ -n "$other" ]]; then
    echo "$other already runs $3; set [profile] launchd_label to its label (${other:t:r}), or remove it first" >&2
    exit 1
  fi
  sed -e "s#__RUN__#$HERE/$3#g" -e "s#__LOG__#$4#g" -e "s#__LABEL__#$1#g" -e "s#__HOME__#$PROFILE#g" "$HERE/$2" > "$plist"
  launchctl bootout "gui/$(id -u)/$1" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$plist"
  echo "installed $plist; log in $4"
}

[[ "$1" == "--backup-only" ]] || install_agent "$LABEL" agent.plist.template run.sh "$PROFILE/scan.log"
install_agent "$LABEL.backup" backup.plist.template backup.sh "$PROFILE/backup.log"
