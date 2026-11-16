import json
import logging
from datetime import UTC, datetime

from app.core.context import current_request_id


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Structured fields go in `extra={"fields": {...}}`."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        request_id = current_request_id()
        if request_id and "request_id" not in payload:
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    logger = logging.getLogger("assetdesk")
    logger.setLevel(level)
    if not any(getattr(h, "_assetdesk", False) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        handler._assetdesk = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
