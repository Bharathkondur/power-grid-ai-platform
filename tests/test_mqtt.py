import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from gridpulse.config import Settings
from gridpulse.data.mqtt import ingest, run
from gridpulse.data.storage import Store, telemetry


def test_telemetry_validation_and_deduplication(tmp_path):
    store = Store(Settings(runtime=tmp_path, database_url=f"sqlite:///{tmp_path}/db"))
    event = dict(
        event_id=str(uuid.uuid4()),
        timestamp=datetime.now(UTC).isoformat(),
        device_id="meter-1",
        kind="smart-meter",
        power_kw=4.0,
    )
    payload = json.dumps(event).encode()
    ingest(payload, store)
    ingest(payload, store)
    with store.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(telemetry)).scalar() == 1
    event["power_kw"] = -1
    with pytest.raises(ValueError):
        ingest(json.dumps(event).encode(), store)


def test_broker_unavailable_persists_outbox(tmp_path):
    settings = Settings(runtime=tmp_path, database_url=f"sqlite:///{tmp_path}/db", mqtt_port=1)
    result = run(settings, "publish", count=1)
    assert result["buffered_events"] == 3
