import httpx
import pytest

from gridpulse.data.schema import DataQualityError
from gridpulse.data.sources import historical


def test_missing_entsoe_credentials_rejects(monkeypatch, tmp_path):
    monkeypatch.delenv("ENTSOE_API_KEY", raising=False)
    with pytest.raises(DataQualityError, match="ENTSOE_API_KEY"):
        historical("entsoe", "2024-01-01", "2024-01-02", tmp_path)


def test_upstream_failure_cannot_become_partial_dataset(monkeypatch, tmp_path):
    def offline(*_args, **_kwargs):
        raise httpx.ConnectError("Injected upstream outage")

    monkeypatch.setattr(httpx, "stream", offline)
    with pytest.raises(httpx.ConnectError):
        historical("opsd", "2019-01-01", "2019-01-02", tmp_path)


def test_cached_partial_upstream_rejected_before_weather(monkeypatch, tmp_path):
    (tmp_path / "opsd-2020-10-06.csv").write_text(
        "utc_timestamp,DE_load_actual_entsoe_transparency\n2019-01-01T00:00:00Z,50000\n"
    )
    with pytest.raises(DataQualityError, match="entire requested"):
        historical("opsd", "2019-01-01", "2019-01-02", tmp_path)
