"""Replay held-out synthetic origins through the real API to populate delayed-label metrics."""

import argparse
import json

import httpx
import pandas as pd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--data", default="runtime/synthetic.csv")
    parser.add_argument("--days", type=int, default=14)
    args = parser.parse_args()
    data = pd.read_csv(args.data)
    data.timestamp = pd.to_datetime(data.timestamp, utc=True)
    with httpx.Client(timeout=60) as client:
        for cutoff in range(len(data) - args.days * 24, len(data), 24):
            history = data.iloc[cutoff - 168 : cutoff]
            response = client.post(
                args.url + "/v1/forecast",
                json={
                    "history": json.loads(history.to_json(orient="records", date_format="iso")),
                },
            )
            response.raise_for_status()
        info = client.get(args.url + "/v1/model").json()
    print(json.dumps({"origins_served": args.days, "model": info}, indent=2))


if __name__ == "__main__":
    main()
