"""Log terstruktur (NFR-9): setiap baris membawa `scan_id` dan `trace_id` bila ada."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

FIELDS = ("scan_id", "trace_id", "status", "code")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update({k: getattr(record, k) for k in FIELDS if hasattr(record, k)})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: int = logging.INFO) -> None:
    """Pasang formatter JSON sekali untuk logger `ceteris_server`."""
    logger = logging.getLogger("ceteris_server")
    if any(isinstance(h.formatter, JsonFormatter) for h in logger.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
