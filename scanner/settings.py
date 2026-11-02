"""Where your own data lives, and the one way to read your config.

Everything personal sits in one profile directory, $JOB_SCANNER_HOME
(default ~/.job-scanner), outside the repository:

    config.toml         your searches, places and email address
    env                 secrets: JOB_SCANNER_MAILER_DSN, JOB_SCANNER_MAIL_FROM
    state.sqlite3       what the scanner has seen and what you decided
    pending.json        jobs waiting for the next send hour
    scan.log, backup.log
    backups/

The config is read from $JOB_SCANNER_HOME/config.toml, or, for an older
setup, from scanner/config.toml when only that one exists.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

HOME_ENV = "JOB_SCANNER_HOME"
LEGACY_CONFIG = Path(__file__).resolve().parent / "config.toml"


def profile_home() -> Path:
    return Path(os.environ.get(HOME_ENV) or "~/.job-scanner").expanduser()


def config_path(explicit: str | Path | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    home = profile_home() / "config.toml"
    if not home.exists() and LEGACY_CONFIG.exists():
        return LEGACY_CONFIG
    return home


def load_config(path: str | Path | None = None, log=None, with_path: bool = False):
    """The config as a dict, with run.state_path defaulting to the profile
    directory. `log` is told which file was read."""
    file = config_path(path)
    if not file.is_file():
        raise SystemExit(f"no config at {file}: copy scanner/config.example.toml there, or run ./setup.sh")
    with open(file, "rb") as handle:
        config = tomllib.load(handle)
    config.setdefault("run", {}).setdefault("state_path", str(profile_home() / "state.sqlite3"))
    if log:
        log(f"config: {file}")
    return (config, file) if with_path else config


# Values in config.example.toml that only make sense once replaced.
PLACEHOLDERS = {"Your Country", "Your City", "your-country", "you@example.com"}


def placeholders(config: dict) -> list[str]:
    """The fields that still hold one of the example's placeholders, as section.key."""
    found = set()

    def walk(value, path):
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{path}.{key}" if path else key)
        elif isinstance(value, list):
            for item in value:
                walk(item, path)
        elif value in PLACEHOLDERS:
            found.add(path)

    walk(config, "")
    return sorted(found)


def lock_path(state_path: str | Path) -> Path:
    """The file a scan holds locked while it runs (scanner/run.py)."""
    return Path(state_path).expanduser().with_suffix(".lock")
