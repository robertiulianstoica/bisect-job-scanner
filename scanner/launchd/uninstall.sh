#!/bin/zsh
# Remove both launchd agents (<label> and <label>.backup). Data in the profile
# directory is left alone.
HERE="${0:A:h}"
source "$HERE/label.sh"
for label in "$LABEL" "$LABEL.backup"; do
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/$label.plist"
  echo "removed $label"
done
