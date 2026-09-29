import numpy as np
import pandas as pd

from gridpulse.data.sources import synthetic
from gridpulse.features import at_origin, split_points, supervised


def test_future_mutation_cannot_change_origin_features():
    data = synthetic(60)
    before = at_origin(data.iloc[:168])
    data.loc[168:, "demand"] *= 10
    data.loc[168:, "temperature"] = -70
    pd.testing.assert_frame_equal(before, at_origin(data.iloc[:168]))
    x, _, _, _ = supervised(data)
    pd.testing.assert_frame_equal(before, x.iloc[:24].reset_index(drop=True))


def test_known_lags_and_rolling_window():
    data = synthetic(8)
    data["demand"] = np.arange(1, len(data) + 1)
    row = at_origin(data.iloc[:168]).iloc[0]
    assert row.demand_lag_1h == 168
    assert row.demand_lag_7d == 1
    assert row.demand_roll_3h_mean == 167
    assert row.horizon == 1


def test_disjoint_chronological_target_splits():
    x, y, baseline, times = supervised(synthetic(60))
    train, valid = split_points(len(x))
    assert times[train - 1] < times[train] < times[valid - 1] < times[valid]
    assert train % 24 == valid % 24 == 0
    assert len(x) == len(y) == len(baseline) == len(times)


def test_dst_uses_utc_continuity_and_local_calendar():
    data = synthetic(10, start="2023-03-19")
    x = at_origin(data.iloc[:168])
    assert len(x) == 24
    assert 2 not in x.hour.values  # Spring-forward day in Berlin.
