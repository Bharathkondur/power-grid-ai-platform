import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        output = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": record.name,
            "operation": record.getMessage(),
        }
        for key in ("request_id", "model_version", "error_category"):
            if hasattr(record, key):
                output[key] = getattr(record, key)
        if record.exc_info:
            output["exception"] = self.formatException(record.exc_info)
        return json.dumps(output)


def configure(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
