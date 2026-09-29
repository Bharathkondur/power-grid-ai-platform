import hashlib
from datetime import datetime

import numpy as np
import pandas as pd

WEATHER = ["temperature", "apparent_temperature", "wind", "cloud_cover", "solar_radiation"]
REQUIRED = ["timestamp", "demand", *WEATHER]
OPTIONAL = ["generation", "price"]


class DataQualityError(ValueError):
    """An entire batch was rejected; no partial training is permitted."""


def validate(
    data: pd.DataFrame,
    *,
    min_rows: int = 1,
    now: datetime | pd.Timestamp | None = None,
    max_stale_hours: float = 3,
) -> pd.DataFrame:
    missing = set(REQUIRED) - set(data.columns)
    extra = set(data.columns) - set(REQUIRED + OPTIONAL)
    if missing or extra:
        raise DataQualityError(f"Schema mismatch: missing={sorted(missing)}, extra={sorted(extra)}")
    if len(data) < min_rows:
        raise DataQualityError(f"Need at least {min_rows} complete hours, got {len(data)}")
    frame = data.copy()
    try:
        times = pd.DatetimeIndex(pd.to_datetime(frame.timestamp))
    except (ValueError, TypeError) as exc:
        raise DataQualityError(
            "Invalid or mixed-zone timestamps; normalize explicitly to UTC"
        ) from exc
    if times.tz is None or times.hasnans:
        raise DataQualityError("Timestamps must be timezone-aware and non-null")
    times = times.tz_convert("UTC")
    if times.has_duplicates or not times.is_monotonic_increasing:
        raise DataQualityError("Duplicate or unordered timestamps")
    if not (times == times.floor("h")).all():
        raise DataQualityError("Timestamps must be aligned to the hour")
    if len(times) > 1 and not (np.diff(times.asi8) == pd.Timedelta(hours=1).value).all():
        raise DataQualityError("Missing hours: batch must be a continuous hourly series")
    frame["timestamp"] = times
    for col in REQUIRED[1:] + [c for c in OPTIONAL if c in frame]:
        try:
            frame[col] = pd.to_numeric(frame[col], errors="raise").astype(float)
        except (ValueError, TypeError) as exc:
            raise DataQualityError(f"Non-numeric {col}") from exc
        vals = frame[col].dropna() if col in OPTIONAL else frame[col]
        if not np.isfinite(vals).all():
            raise DataQualityError(f"Missing or non-finite {col}")
    if (frame.demand <= 0).any():
        raise DataQualityError("Demand must be positive MW")
    if (frame.wind < 0).any() or (frame.solar_radiation < 0).any():
        raise DataQualityError("Wind and solar radiation cannot be negative")
    if not frame.cloud_cover.between(0, 100).all():
        raise DataQualityError("Cloud cover must be a percentage")
    if not frame.temperature.between(-90, 65).all():
        raise DataQualityError("Temperature outside physical bounds (Celsius)")
    if now is not None:
        clock = pd.Timestamp(now)
        if clock.tzinfo is None:
            raise DataQualityError("Freshness reference must be timezone-aware")
        age = (clock.tz_convert("UTC") - times[-1]).total_seconds() / 3600
        if age < 0 or age > max_stale_hours:
            raise DataQualityError(f"Future or stale data: age_hours={age:.2f}")
    return frame.reset_index(drop=True)


def fingerprint(frame: pd.DataFrame) -> str:
    normalized = validate(frame).reindex(columns=REQUIRED + OPTIONAL)
    return hashlib.sha256(normalized.to_csv(index=False, float_format="%.8f").encode()).hexdigest()
