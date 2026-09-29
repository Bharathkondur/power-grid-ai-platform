import os
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from gridpulse.data.schema import DataQualityError, validate

OPSD_URL = (
    "https://data.open-power-system-data.org/time_series/2020-10-06/"
    "time_series_60min_singleindex.csv"
)
WEATHER_NAMES = {
    "temperature_2m": "temperature",
    "apparent_temperature": "apparent_temperature",
    "wind_speed_10m": "wind",
    "cloud_cover": "cloud_cover",
    "shortwave_radiation": "solar_radiation",
}


def synthetic(days: int = 365, seed: int = 42, start: str = "2023-01-01") -> pd.DataFrame:
    """Explicit synthetic national MW fixture; never passed off as measured data."""
    rng = np.random.default_rng(seed)
    t = pd.date_range(start, periods=days * 24, freq="h", tz="UTC")
    local = t.tz_convert("Europe/Berlin")
    hour = local.hour.to_numpy()
    temp = 10 + 12 * np.sin(2 * np.pi * (t.dayofyear.to_numpy() - 100) / 365)
    temp = temp + 3 * np.sin(2 * np.pi * (hour - 9) / 24) + rng.normal(0, 1, len(t))
    cloud = np.clip(50 + 25 * np.sin(np.arange(len(t)) / 40) + rng.normal(0, 10, len(t)), 0, 100)
    solar = np.maximum(0, np.sin(np.pi * (hour - 6) / 12)) * 600 * (1 - cloud / 150)
    demand = (
        48000
        + 7000 * np.sin(2 * np.pi * (hour - 7) / 24)
        - 6000 * (local.dayofweek.to_numpy() >= 5)
        + 700 * np.maximum(15 - temp, 0)
        + rng.normal(0, 500, len(t))
    )
    return validate(
        pd.DataFrame(
            {
                "timestamp": t,
                "demand": demand,
                "temperature": temp,
                "apparent_temperature": temp - 1.5,
                "wind": np.maximum(0, 15 + rng.normal(0, 4, len(t))),
                "cloud_cover": cloud,
                "solar_radiation": solar,
            }
        )
    )


def weather(start: str, end: str, raw_dir: Path) -> pd.DataFrame:
    """Berlin proxy only; historical observed weather, never future forecast inputs."""
    params = {
        "latitude": 52.52,
        "longitude": 13.41,
        "start_date": start,
        "end_date": end,
        "hourly": ",".join(WEATHER_NAMES),
        "timezone": "UTC",
        "wind_speed_unit": "kmh",
    }
    response = httpx.get(
        "https://archive-api.open-meteo.com/v1/archive", params=params, timeout=120
    )
    response.raise_for_status()
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"weather-{start}-{end}.json").write_bytes(response.content)
    result = pd.DataFrame(response.json()["hourly"]).rename(columns=WEATHER_NAMES)
    result["timestamp"] = pd.to_datetime(result.pop("time"), utc=True)
    return result


def historical(source: str, start: str, end: str, raw_dir: Path) -> pd.DataFrame:
    begin = pd.Timestamp(start, tz="UTC")
    stop = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    raw_dir.mkdir(parents=True, exist_ok=True)
    if source == "opsd":
        path = raw_dir / "opsd-2020-10-06.csv"
        if not path.exists():
            temporary = path.with_suffix(".part")
            with httpx.stream("GET", OPSD_URL, timeout=120, follow_redirects=True) as response:
                response.raise_for_status()
                with temporary.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
            temporary.replace(path)
        demand = pd.read_csv(path, usecols=["utc_timestamp", "DE_load_actual_entsoe_transparency"])
        demand.columns = ["timestamp", "demand"]
        demand.timestamp = pd.to_datetime(demand.timestamp, utc=True)
    elif source == "entsoe":
        from entsoe import EntsoePandasClient

        token = os.environ.get("ENTSOE_API_KEY")
        if not token:
            raise DataQualityError("ENTSOE_API_KEY is required; use --source synthetic for demo")
        series = EntsoePandasClient(api_key=token).query_load("DE_LU", start=begin, end=stop)
        # Quarter-hour inputs require all four samples; incomplete hours remain NaN and fail.
        if isinstance(series, pd.DataFrame):
            series = series["Actual Load"]
        series.index = series.index.tz_convert("UTC")
        interval = series.index.to_series().diff().dropna().mode().iloc[0]
        if interval not in [pd.Timedelta(minutes=15), pd.Timedelta(hours=1)]:
            raise DataQualityError(f"Unsupported ENTSO-E interval: {interval}")
        expected = int(pd.Timedelta(hours=1) / interval)
        hourly = series.resample("h").mean().where(series.resample("h").count() == expected)
        demand = hourly.rename("demand").rename_axis("timestamp").reset_index()
        demand.to_csv(raw_dir / f"entsoe-{start}-{end}.csv", index=False)
    else:
        raise ValueError(f"Unknown historical source {source}")
    demand = demand[(demand.timestamp >= begin) & (demand.timestamp < stop)]
    expected_times = pd.date_range(begin, stop, freq="h", inclusive="left")
    if len(demand) != len(expected_times) or not demand.timestamp.reset_index(drop=True).equals(
        pd.Series(expected_times)
    ):
        raise DataQualityError("Upstream did not provide the entire requested demand window")
    meteo = weather(start, end, raw_dir)
    return validate(demand.merge(meteo, on="timestamp", how="left", validate="one_to_one"))
