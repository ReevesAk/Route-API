import json
import logging
from datetime import UTC, datetime

# Attributes every LogRecord has; anything else was passed via `extra=`.
_RESERVED = set(vars(logging.makeLogRecord({}))) | {'message', 'asctime'}


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with any `extra=` fields merged in."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            'ts'    : datetime.fromtimestamp(record.created, UTC).isoformat(),
            'level' : record.levelname,
            'logger': record.name,
            'msg'   : record.getMessage(),
        }
        payload.update({k: v for k, v in vars(record).items() if k not in _RESERVED})
        if record.exc_info:
            payload['exc'] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)
