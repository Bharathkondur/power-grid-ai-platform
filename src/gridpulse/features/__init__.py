from functools import lru_cache

import holidays
import numpy as np
import pandas as pd

from gridpulse.data.schema import WEATHER, validate

FEATURE_VERSION = "direct24-origin-v1"
LOOKBACK = 168
HORIZON = 24


@lru_cache(maxsize=16)
def german_holidays(year: int) -> set:
    return set(holidays.country_holidays("DE", years=[year]))


def at_origin(history: pd.DataFrame, *, checked: bool = False) -> pd.DataFrame:
    """24 rows built entirely from an observed prefix; target times start one hour later."""
    history = history if checked else validate(history, min_rows=LOOKBACK)
    if len(history) < LOOKBACK:
        raise ValueError("168 complete observed hours are required")
    demand = history.demand
    common = {
        f"demand_lag_{label}": float(demand.iloc[-lag])
        for label, lag in [("1h", 1), ("2h", 2), ("24h", 24), ("48h", 48), ("7d", 168)]
    }
    for window in (3, 24, 168):
        values = demand.iloc[-window:]
        for operation in ("mean", "max", "min", "std"):
            common[f"demand_roll_{window}h_{operation}"] = float(getattr(values, operation)())
    common.update({f"observed_{name}": float(history[name].iloc[-1]) for name in WEATHER})
    # Strict rejection keeps these zero; no undocumented imputation during training/serving.
    common.update(missing_feature_count=0.0, stale_data_flag=0.0)
    origin = history.timestamp.iloc[-1]
    rows = []
    for horizon in range(1, HORIZON + 1):
        timestamp = (origin + pd.Timedelta(hours=horizon)).tz_convert("Europe/Berlin")
        rows.append(
            dict(
                common,
                horizon=horizon,
                hour=timestamp.hour,
                weekday=timestamp.dayofweek,
                month=timestamp.month,
                weekend=int(timestamp.dayofweek >= 5),
                holiday=int(timestamp.date() in german_holidays(timestamp.year)),
            )
        )
    return pd.DataFrame(rows, dtype=float)


def supervised(data: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray, np.ndarray, pd.DatetimeIndex]:
    data = validate(data, min_rows=LOOKBACK + 30 * HORIZON)
    blocks, targets, baselines, times = [], [], [], []
    for cutoff in range(LOOKBACK, len(data) - HORIZON + 1, HORIZON):
        blocks.append(at_origin(data.iloc[cutoff - LOOKBACK : cutoff], checked=True))
        targets.extend(data.demand.iloc[cutoff : cutoff + HORIZON])
        baselines.extend(data.demand.iloc[cutoff - LOOKBACK : cutoff - LOOKBACK + HORIZON])
        times.extend(data.timestamp.iloc[cutoff : cutoff + HORIZON])
    return (
        pd.concat(blocks, ignore_index=True),
        np.array(targets),
        np.array(baselines),
        pd.DatetimeIndex(times),
    )


def split_points(rows: int) -> tuple[int, int]:
    blocks = rows // HORIZON
    if blocks < 30 or rows % HORIZON:
        raise ValueError("At least 30 complete daily target blocks are required")
    return int(blocks * 0.7) * HORIZON, int(blocks * 0.85) * HORIZON
