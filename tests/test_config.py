from gridpulse.config import Settings


def test_environment_override(monkeypatch):
    monkeypatch.setenv("GRIDPULSE_ENV", "test")
    assert Settings(_env_file=None).env == "test"
