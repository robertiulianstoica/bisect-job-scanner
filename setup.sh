#!/bin/zsh
# First-time setup of the job scanner for a new user (macOS; on Linux use cron
# instead of the launchd agents). Safe to run again: an existing config.toml or
# env is never overwritten.
#
#   ./setup.sh                                  # profile in ~/.job-scanner
#   JOB_SCANNER_HOME=~/jobs-profile ./setup.sh  # somewhere else
set -e
REPO="${0:A:h}"
PROFILE="${JOB_SCANNER_HOME:-$HOME/.job-scanner}"
cd "$REPO"

if [[ -z "$SETUP_SKIP_VENV" ]]; then
  if [[ ! -x .venv/bin/python ]]; then
    if command -v uv >/dev/null; then uv venv --python 3.12 .venv
    else python3 -m venv .venv; fi  # Python 3.11 or later (tomllib)
  fi
  if command -v uv >/dev/null; then uv pip install --python .venv/bin/python -q -e . pytest
  else .venv/bin/python -m pip install -q -e . pytest; fi
fi

mkdir -p "$PROFILE"
chmod 700 "$PROFILE"

if [[ -e "$PROFILE/config.toml" ]]; then
  echo "kept $PROFILE/config.toml (exists; not overwritten)"
else
  cp scanner/config.example.toml "$PROFILE/config.toml"
  chmod 600 "$PROFILE/config.toml"  # it will hold your email address
  echo "created $PROFILE/config.toml from scanner/config.example.toml"
fi

if [[ -e "$PROFILE/env" ]]; then
  echo "kept $PROFILE/env (exists; not overwritten)"
else
  (umask 077; cat > "$PROFILE/env" <<'ENV'
# Secrets for the job scanner, read by scanner/launchd/run.sh. Never commit this file.
# SMTP in Symfony Mailer DSN form, e.g. smtp://user:password@smtp.example.com:587
# Gmail: smtp://<you>%40gmail.com:<app password>@smtp.gmail.com:587 (app password from
# https://myaccount.google.com/apppasswords; the @ in the user name is written %40)
export JOB_SCANNER_MAILER_DSN=
# The sender, e.g. 'Job scanner <jobs@example.com>'
export JOB_SCANNER_MAIL_FROM=
ENV
  )
  chmod 600 "$PROFILE/env"
  echo "created $PROFILE/env (empty values, mode 600)"
fi

git config core.hooksPath .githooks
echo "enabled the pre-commit check (.githooks/pre-commit)"

cat <<NEXT

Next (README.md, "Quick start", has the details):
  1. Edit $PROFILE/config.toml: [search] terms and include, [eligibility] home,
     home_cities and contract_ok, [email] to, and your country in the LinkedIn
     and Himalayas sections. The scanner names any placeholder left.
  2. Try it (a few minutes, sends nothing):
       JOB_SCANNER_HOME=$PROFILE .venv/bin/python -m scanner.run --dry-run
  3. Put your SMTP details in $PROFILE/env (with Gmail: an app password from
     https://myaccount.google.com/apppasswords).
  4. Run it every 30 minutes (macOS):  JOB_SCANNER_HOME=$PROFILE scanner/launchd/install.sh
NEXT
