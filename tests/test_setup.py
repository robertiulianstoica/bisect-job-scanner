"""setup.sh, the pre-commit check and the launchd installer, each run in a
throwaway git repository or home directory: never the real profile."""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def sh(args, cwd, env=None, check=True):
    return subprocess.run(args, cwd=cwd, env={**os.environ, **(env or {})}, capture_output=True, text=True, check=check)


@pytest.fixture
def repo(tmp_path):
    """A git repository holding the files setup.sh and the hook need."""
    root = tmp_path / "repo"
    (root / "scanner").mkdir(parents=True)
    shutil.copy(REPO / "setup.sh", root / "setup.sh")
    shutil.copy(REPO / "scanner" / "config.example.toml", root / "scanner" / "config.example.toml")
    shutil.copytree(REPO / ".githooks", root / ".githooks")
    sh(["git", "init", "-q"], root)
    sh(["git", "config", "user.email", "test@example.com"], root)
    sh(["git", "config", "user.name", "Test"], root)
    return root


def test_setup_creates_the_profile_and_never_overwrites_it(repo, tmp_path):
    home = tmp_path / "profile"
    env = {"JOB_SCANNER_HOME": str(home), "SETUP_SKIP_VENV": "1"}
    out = sh(["zsh", "setup.sh"], repo, env).stdout
    assert "created" in out and "Next (README.md" in out
    assert (home / "config.toml").read_text() == (repo / "scanner" / "config.example.toml").read_text()
    env_file = home / "env"
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    assert stat.S_IMODE((home / "config.toml").stat().st_mode) == 0o600
    assert "export JOB_SCANNER_MAILER_DSN=\n" in env_file.read_text()
    assert sh(["git", "config", "core.hooksPath"], repo).stdout.strip() == ".githooks"

    (home / "config.toml").write_text("mine")
    env_file.write_text("export JOB_SCANNER_MAILER_DSN=secret\n")
    out = sh(["zsh", "setup.sh"], repo, env).stdout
    assert "kept" in out and "created" not in out
    assert (home / "config.toml").read_text() == "mine"
    assert env_file.read_text() == "export JOB_SCANNER_MAILER_DSN=secret\n"


@pytest.mark.parametrize("name, content", [
    ("notes.txt", "dsn: smtp://me:hunter2@mail.example.net:587\n"),
    ("notes.txt", "export JOB_SCANNER_MAILER_DSN='smtps://x'\n"),
    ("notes.txt", "JOB_SCANNER_MAILER_DSN=abc\n"),
    ("notes.txt", "my data is in ~/.job-scanner/state.sqlite3\n"),
    ("state.sqlite3", "SQLite format 3"),
    ("copy.sqlite3-journal", "x"),
    ("scanner/config.toml", "[email]\n"),
    ("env", "x=1\n"),
    ("pending.json", "{}"),
    ("scan.log", "x"),
])
def test_the_hook_refuses_personal_data(repo, name, content):
    sh(["git", "config", "core.hooksPath", ".githooks"], repo)
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(content)
    sh(["git", "add", "-f", name], repo)
    result = sh(["git", "commit", "-q", "-m", "dummy"], repo, check=False)
    assert result.returncode != 0 and "commit refused" in result.stderr


def test_the_hook_lets_ordinary_and_documentation_changes_through(repo):
    sh(["git", "config", "core.hooksPath", ".githooks"], repo)
    (repo / "notes.txt").write_text("JOB_SCANNER_MAILER_DSN=\nsmtp://user:password@smtp.example.com:587\n"
                                    "export JOB_SCANNER_MAILER_DSN='smtp://<you>%40gmail.com:<app password>@smtp.gmail.com:587'\n")
    (repo / "README.md").write_text("Data lives in ~/.job-scanner by default.\n")
    sh(["git", "add", "notes.txt", "README.md", "setup.sh", "scanner", ".githooks"], repo)
    assert sh(["git", "commit", "-q", "-m", "fine"], repo, check=False).returncode == 0


def test_install_refuses_a_second_agent_for_the_same_script(tmp_path):
    """A config without launchd_label must not install a duplicate of an agent
    already running run.sh under another label."""
    home, profile, bin_dir = tmp_path / "home", tmp_path / "profile", tmp_path / "bin"
    agents = home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    profile.mkdir()
    bin_dir.mkdir()
    (profile / "config.toml").write_text("[run]\n")
    run = REPO / "scanner" / "launchd" / "run.sh"
    (agents / "old.label.plist").write_text(f"<string>{run}</string>")
    (bin_dir / "launchctl").write_text("#!/bin/sh\necho \"launchctl $*\" >> \"$HOME/calls\"\n")
    (bin_dir / "launchctl").chmod(0o755)
    env = {"HOME": str(home), "JOB_SCANNER_HOME": str(profile), "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    result = sh(["zsh", str(REPO / "scanner" / "launchd" / "install.sh")], REPO, env, check=False)
    assert result.returncode != 0 and "launchd_label" in result.stderr
    assert sorted(p.name for p in agents.iterdir()) == ["old.label.plist"] and not (home / "calls").exists()

    (profile / "config.toml").write_text('[profile]\nlaunchd_label = "old.label"\n')
    result = sh(["zsh", str(REPO / "scanner" / "launchd" / "install.sh"), "--backup-only"], REPO, env)
    assert (agents / "old.label.backup.plist").is_file()
    assert (agents / "old.label.plist").read_text() == f"<string>{run}</string>"  # left as it was
    assert "bootstrap" in (home / "calls").read_text()
    assert f"<string>{profile}</string>" in (agents / "old.label.backup.plist").read_text()
