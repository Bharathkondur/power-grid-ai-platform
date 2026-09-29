import json
import logging
import time
from datetime import UTC, datetime, timedelta

from gridpulse.config import Settings
from gridpulse.monitoring.quality import monitor, retrain
from gridpulse.utils.logging import configure


def main():
    settings = Settings()
    configure(settings.log_level)
    state_path = settings.runtime / "scheduler.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    while True:
        try:
            now = datetime.now(UTC)
            report = monitor(settings)
            last = datetime.fromisoformat(state.get("last_training", now.isoformat()))
            # Persistent weekly cadence, and at most one quality-triggered attempt per day.
            trigger = "scheduled" if now - last >= timedelta(days=7) else "quality"
            should_train = trigger == "scheduled" or (
                report["retrain_requested"] and now - last >= timedelta(days=1)
            )
            if should_train:
                logging.info(json.dumps(retrain(settings, trigger)))
                state["last_training"] = now.isoformat()
            state.setdefault("last_training", now.isoformat())
            temporary = state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(state))
            temporary.replace(state_path)
        except Exception:
            logging.exception("monitor_cycle_failed")
        time.sleep(60)


if __name__ == "__main__":
    main()
