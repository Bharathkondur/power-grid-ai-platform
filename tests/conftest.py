import pytest

from gridpulse.config import Settings
from gridpulse.data.sources import synthetic
from gridpulse.models.registry import promote
from gridpulse.models.training import train


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    path = tmp_path_factory.mktemp("tracking")
    settings = Settings(
        runtime=path,
        database_url=f"sqlite:///{path}/data.db",
        mlflow_uri=f"sqlite:///{path}/mlflow.db",
        baseline_ratio=2.0,
    )
    data = synthetic(120)
    manifest = train(data, settings, "synthetic")
    assert promote(settings, manifest["model_version"])["accepted"]
    return settings, data, manifest
