import copy

import numpy as np
import pytest

from gridpulse.config import Settings
from gridpulse.models.registry import acceptance
from gridpulse.models.training import metrics


def test_metrics():
    result = metrics(np.array([10, 20]), np.array([12, 18]))
    assert result == {"mae": 2.0, "rmse": 2.0, "mape": 15.000000000000002}


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), -1, 1e9])
def test_gate_rejects_bad_metrics(bad):
    manifest = {
        group: {"mae": 100, "rmse": 150, "mape": 1}
        for group in ("validation", "test", "baseline_validation", "baseline_test")
    }
    assert acceptance(manifest, Settings()) == []
    broken = copy.deepcopy(manifest)
    broken["validation"]["mae"] = bad
    assert acceptance(broken, Settings())
