import pytest

from scanner import settings


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_SCANNER_HOME", str(tmp_path / "profile"))
    monkeypatch.setattr(settings, "LEGACY_CONFIG", tmp_path / "repo" / "config.toml")
    (tmp_path / "profile").mkdir()
    (tmp_path / "repo").mkdir()
    return tmp_path


def test_reads_the_profile_config_first(home):
    (home / "profile" / "config.toml").write_text('[email]\nto = "profile@example.com"\n')
    settings.LEGACY_CONFIG.write_text('[email]\nto = "legacy@example.com"\n')
    said = []
    config = settings.load_config(log=said.append)
    assert config["email"]["to"] == "profile@example.com"
    assert said == [f"config: {home / 'profile' / 'config.toml'}"]


def test_falls_back_to_the_config_in_the_repo(home):
    settings.LEGACY_CONFIG.write_text('[email]\nto = "legacy@example.com"\n')
    config, file = settings.load_config(with_path=True)
    assert config["email"]["to"] == "legacy@example.com" and file == settings.LEGACY_CONFIG


def test_state_path_defaults_to_the_profile(home):
    (home / "profile" / "config.toml").write_text("[run]\nsend_hours = [8]\n")
    assert settings.load_config()["run"]["state_path"] == str(home / "profile" / "state.sqlite3")
    (home / "profile" / "config.toml").write_text('[run]\nstate_path = "/elsewhere/state.sqlite3"\n')
    assert settings.load_config()["run"]["state_path"] == "/elsewhere/state.sqlite3"


def test_an_explicit_path_wins_and_a_missing_config_says_where(home):
    other = home / "other.toml"
    other.write_text('[email]\nto = "other@example.com"\n')
    (home / "profile" / "config.toml").write_text('[email]\nto = "profile@example.com"\n')
    assert settings.load_config(other)["email"]["to"] == "other@example.com"
    with pytest.raises(SystemExit, match="no config at .*missing.toml"):
        settings.load_config(home / "missing.toml")
    (home / "profile" / "config.toml").unlink()
    with pytest.raises(SystemExit, match="setup.sh"):
        settings.load_config()


def test_home_defaults_to_dot_job_scanner(monkeypatch):
    monkeypatch.delenv("JOB_SCANNER_HOME", raising=False)
    assert settings.profile_home() == settings.Path("~/.job-scanner").expanduser()


def test_the_example_config_is_complete_and_neutral(home):
    from scanner.rules import check_applicants, check_content, check_location

    example = settings.Path(settings.__file__).parent / "config.example.toml"
    text = example.read_text()
    assert not any(word in text.lower() for word in ("robert", "bucharest", "romania\""))
    config = settings.load_config(example)
    job = {"title": "Senior Laravel Developer", "company": "Acme", "description": "Laravel and Vue, fully remote.",
           "location": "Remote, Europe", "site": "greenhouse"}
    assert check_content(job, config["search"]).keep
    assert check_location(job, config["eligibility"]).keep
    assert check_applicants(job, config["linkedin"]["max_applicants"]).keep


def test_placeholders_left_from_the_example_are_named(home):
    example = settings.Path(settings.__file__).parent / "config.example.toml"
    assert settings.placeholders(settings.load_config(example)) == [
        "eligibility.home", "eligibility.home_cities", "email.to", "himalayas.country",
        "linkedin.searches.location"]
    filled = example.read_text().replace("Your Country", "Portugal").replace("Your City", "Lisbon") \
        .replace("your-country", "portugal").replace("you@example.com", "me@mail.pt")
    (home / "profile" / "config.toml").write_text(filled)
    assert settings.placeholders(settings.load_config()) == []
