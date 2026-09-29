import logging
import math
import sqlite3
import time
import uuid
from datetime import UTC, datetime
from typing import Literal

import paho.mqtt.client as mqtt
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from gridpulse.config import Settings
from gridpulse.data.storage import Store, telemetry

logger = logging.getLogger("gridpulse.ingestion")


class Telemetry(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    event_id: uuid.UUID
    timestamp: AwareDatetime
    device_id: str = Field(pattern=r"^[a-z0-9-]{1,48}$")
    kind: Literal["smart-meter", "plant", "edge"]
    power_kw: float = Field(ge=0, le=100000)


def ingest(payload: bytes, store: Store) -> None:
    event = Telemetry.model_validate_json(payload)
    age = (datetime.now(UTC) - event.timestamp).total_seconds()
    if age < -60 or age > 86400:
        raise ValueError("Telemetry timestamp is future or more than 24h old")
    row = event.model_dump(mode="json")
    row["timestamp"] = event.timestamp.astimezone(UTC).isoformat()
    row["received_at"] = datetime.now(UTC).isoformat()
    store.insert(telemetry, [row], immutable=True)


def mqtt_client(settings: Settings, name: str, *, subscriber: bool = False):
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=name,
        clean_session=False,
        manual_ack=subscriber,
    )
    if settings.mqtt_ca:
        client.tls_set(ca_certs=settings.mqtt_ca)
    if settings.mqtt_username:
        client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    return client


def run(settings: Settings, mode: str, count: int = 0) -> dict:
    store = Store(settings)
    if mode == "subscribe":
        client = mqtt_client(settings, settings.mqtt_client_id, subscriber=True)

        def on_connect(connection, _userdata, _flags, reason_code, _properties):
            if reason_code == 0:
                connection.subscribe(settings.mqtt_topic, qos=1)
                logger.info("mqtt_connected")

        def on_message(connection, _userdata, message):
            try:
                ingest(message.payload, store)
            except ValueError:
                # Poison messages are rejected and acknowledged, never silently persisted.
                logger.exception("mqtt_schema_rejected", extra={"error_category": "validation"})
                connection.ack(message.mid, message.qos)
            except Exception:
                logger.exception("mqtt_storage_failed", extra={"error_category": "storage"})
                connection.disconnect()  # Unacked QoS1 is redelivered on reconnect.
            else:
                connection.ack(message.mid, message.qos)
                logger.info("mqtt_stored")

        client.on_connect, client.on_message = on_connect, on_message
        while True:
            try:
                client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=30)
                client.loop_forever(retry_first_connection=True)
            except OSError:
                logger.warning("mqtt_unavailable_retrying", extra={"error_category": "broker"})
            time.sleep(2)
    spool = sqlite3.connect(settings.runtime / "mqtt-outbox.db")
    spool.execute(
        "CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, topic TEXT, payload TEXT)"
    )
    client = mqtt_client(settings, "gridpulse-simulator")
    emitted = 0
    while count == 0 or emitted < count:
        now = datetime.now(UTC)
        for kind, scale in (("smart-meter", 4), ("plant", 1200), ("edge", 25)):
            event = Telemetry(
                event_id=uuid.uuid4(),
                timestamp=now,
                device_id=f"{kind}-01",
                kind=kind,
                power_kw=scale * (1 + 0.3 * math.sin(2 * math.pi * now.hour / 24)),
            )
            spool.execute(
                "INSERT INTO outbox VALUES (?, ?, ?)",
                (
                    str(event.event_id),
                    f"gridpulse/telemetry/{kind}/{event.device_id}",
                    event.model_dump_json(),
                ),
            )
        spool.commit()  # Persist before attempting broker delivery.
        try:
            if not client.is_connected():
                client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=30)
                client.loop_start()
            for event_id, topic, payload in spool.execute(
                "SELECT id, topic, payload FROM outbox"
            ).fetchall():
                receipt = client.publish(topic, payload, qos=1)
                receipt.wait_for_publish(timeout=10)
                if not receipt.is_published():
                    raise OSError("MQTT publish not acknowledged")
                spool.execute("DELETE FROM outbox WHERE id = ?", (event_id,))
                spool.commit()
        except (OSError, RuntimeError, ValueError):
            logger.warning("mqtt_buffered_retry_pending", extra={"error_category": "broker"})
        emitted += 1
        if count == 0 or emitted < count:
            time.sleep(2)
    pending = spool.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
    client.disconnect()
    client.loop_stop()
    spool.close()
    return {"emitted_batches": emitted, "buffered_events": pending}
