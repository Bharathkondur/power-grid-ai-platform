import argparse
import json
import logging
import sys

from gridpulse.config import Settings
from gridpulse.data.schema import fingerprint
from gridpulse.data.sources import historical, synthetic
from gridpulse.data.storage import Store
from gridpulse.utils.logging import configure


def acquire(args: argparse.Namespace, settings: Settings) -> dict:
    store = Store(settings)
    source = args.source or settings.data_source
    frame = (
        synthetic(args.days, start=args.start)
        if source == "synthetic"
        else historical(source, args.start, args.end, settings.runtime / "raw")
    )
    store.save_data(frame, source)
    path = settings.runtime / f"{source}.csv"
    frame.to_csv(path, index=False)
    raw_hash = store.archive(path)
    return {
        "source": source,
        "rows": len(frame),
        "data_hash": fingerprint(frame),
        "raw_hash": raw_hash,
    }


def smoke(settings: Settings, url: str, expected: str | None = None) -> dict:
    import httpx

    data = Store(settings).read_data(settings.data_source)
    payload = {"history": json.loads(data.iloc[-168:].to_json(orient="records", date_format="iso"))}
    with httpx.Client(timeout=60) as client:
        ready = client.get(url + "/ready")
        ready.raise_for_status()
        response = client.post(url + "/v1/forecast", json=payload)
        response.raise_for_status()
        result = response.json()
    if len(result["forecasts"]) != 24:
        raise ValueError("Wrong forecast horizon")
    if expected and result["model_version"] != expected:
        raise ValueError("Served model version differs from approved version")
    return result


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="gridpulse")
    sub = root.add_subparsers(dest="command", required=True)
    data = sub.add_parser("data")
    data.add_argument("--source", choices=["synthetic", "opsd", "entsoe"])
    data.add_argument("--days", type=int, default=365)
    data.add_argument("--start", default="2023-01-01")
    data.add_argument("--end", default="2019-12-31")
    sub.add_parser("features")
    train = sub.add_parser("train")
    train.add_argument("--promote", action="store_true")
    sub.add_parser("evaluate")
    promote = sub.add_parser("promote")
    promote.add_argument("version")
    sub.add_parser("rollback")
    sub.add_parser("monitor")
    retrain = sub.add_parser("retrain")
    retrain.add_argument("--trigger", choices=["scheduled", "quality"], default="scheduled")
    smoke_parser = sub.add_parser("smoke")
    smoke_parser.add_argument("--url", default="http://localhost:8000")
    smoke_parser.add_argument("--expected-version")
    sub.add_parser("demo")
    mqtt = sub.add_parser("mqtt")
    mqtt.add_argument("mode", choices=["publish", "subscribe"])
    mqtt.add_argument("--count", type=int, default=0)
    return root


def main() -> None:
    args = parser().parse_args()
    settings = Settings()
    settings.prepare()
    configure(settings.log_level)
    try:
        result = dispatch(args, settings)
        print(json.dumps(result, indent=2, default=str))
    except Exception as exc:
        logging.getLogger("gridpulse.cli").exception(
            "command_failed", extra={"error_category": type(exc).__name__}
        )
        sys.exit(1)


def dispatch(args: argparse.Namespace, settings: Settings) -> dict:
    from gridpulse.models.registry import load, promote, rollback
    from gridpulse.models.training import train

    if args.command == "data":
        return acquire(args, settings)
    if args.command == "rollback":
        return rollback(settings)
    if args.command == "promote":
        return promote(settings, args.version)
    if args.command == "smoke":
        return smoke(settings, args.url, args.expected_version)
    if args.command == "mqtt":
        from gridpulse.data.mqtt import run

        return run(settings, args.mode, args.count)
    if args.command == "demo":
        args.source, args.days, args.start = "synthetic", 365, "2023-01-01"
        acquire(args, settings)
        result = train(Store(settings).read_data("synthetic"), settings, "synthetic")
        outcome = promote(settings, result["model_version"])
        if not outcome["accepted"]:
            raise ValueError(f"Demo candidate rejected: {outcome}")
        return {"training": brief(result), "promotion": outcome}
    if args.command in ("monitor", "retrain"):
        from gridpulse.monitoring.quality import monitor, retrain

        return monitor(settings) if args.command == "monitor" else retrain(settings, args.trigger)
    frame = Store(settings).read_data(settings.data_source)
    if args.command == "features":
        from gridpulse.features import supervised

        features, targets, _, times = supervised(frame)
        output = features.assign(target=targets, target_timestamp=times)
        path = settings.runtime / "features.parquet"
        output.to_parquet(path, index=False)
        return {"rows": len(output), "path": str(path)}
    if args.command == "train":
        result = train(frame, settings, settings.data_source)
        outcome = promote(settings, result["model_version"]) if args.promote else None
        if outcome and not outcome["accepted"]:
            raise ValueError(f"Candidate rejected: {outcome}")
        return {"training": brief(result), "promotion": outcome}
    if args.command == "evaluate":
        bundle = load(settings)
        return {"version": bundle.version, **brief(bundle.manifest)}
    raise ValueError(args.command)


def brief(manifest: dict) -> dict:
    return {
        key: value
        for key, value in manifest.items()
        if key not in ("baseline_features", "smoke_history", "importance", "features")
    }


if __name__ == "__main__":
    main()
