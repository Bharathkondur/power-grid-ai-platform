import pytest

from gridpulse.models.registry import alias_version, load, promote, rollback
from gridpulse.models.training import train


@pytest.mark.integration
def test_real_registration_reload_and_promotion(trained):
    settings, data, manifest = trained
    result = promote(settings, manifest["model_version"])
    assert result["accepted"], result
    bundle = load(settings)
    _, forecast = bundle.forecast(data.iloc[-168:])
    assert len(forecast) == 24
    assert bundle.version == manifest["model_version"]


@pytest.mark.integration
def test_rejected_candidate_keeps_champion(trained):
    settings, _, manifest = trained
    before = alias_version(settings, settings.model_alias)
    strict = settings.model_copy(update={"max_mae": 0.00001})
    assert not promote(strict, manifest["model_version"])["accepted"]
    assert alias_version(settings, settings.model_alias) == before


@pytest.mark.integration
def test_post_promotion_failure_restores_previous(trained):
    settings, data, first = trained
    second = train(data, settings, "synthetic")

    def failed_check(_):
        raise RuntimeError("Injected deployment failure")

    with pytest.raises(RuntimeError, match="Injected"):
        promote(settings, second["model_version"], post_check=failed_check)
    assert alias_version(settings, settings.model_alias) == first["model_version"]
    assert promote(settings, second["model_version"])["accepted"]
    assert rollback(settings)["restored"] == first["model_version"]
