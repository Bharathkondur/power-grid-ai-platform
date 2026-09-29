"""Exercise rejection and post-promotion rollback against an actual local MLflow registry."""

import json

from gridpulse.config import Settings
from gridpulse.data.storage import Store
from gridpulse.models.registry import alias_version, promote
from gridpulse.models.training import train


def main():
    settings = Settings()
    previous = alias_version(settings, settings.model_alias)
    if not previous:
        raise ValueError("Run gridpulse demo first")
    candidate = train(
        Store(settings).read_data(settings.data_source), settings, settings.data_source
    )
    version = candidate["model_version"]
    strict = settings.model_copy(update={"max_mae": 0.00001})
    rejected = promote(strict, version)
    assert not rejected["accepted"]
    assert alias_version(settings, settings.model_alias) == previous

    def fail_after_deployment(_):
        raise RuntimeError("Injected post-deployment smoke failure")

    try:
        promote(settings, version, post_check=fail_after_deployment)
    except RuntimeError:
        pass
    else:
        raise AssertionError("Injected failure did not execute")
    restored = alias_version(settings, settings.model_alias)
    assert restored == previous
    print(json.dumps({"candidate": version, "rejection": rejected, "restored": restored}, indent=2))


if __name__ == "__main__":
    main()
