"""
backend/services/logging_setup.py
──────────────────────────────────
Structured JSON logging with correlation ID propagation.

Provides:
  - JSON file handler (RotatingFileHandler → LOG_DIR/jarvis.log)
  - Human-readable console handler
  - Thread-safe correlation ID via contextvars
"""

import contextvars
import json
import logging
import logging.handlers
from datetime import datetime, timezone

from backend.config import config

# ── Correlation ID ────────────────────────────────────────────────────────────

corr_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "corr_id", default=""
)


def set_corr_id(corr_id: str) -> contextvars.Token:
    """Set the correlation ID for the current context. Returns a reset token."""
    return corr_id_var.set(corr_id)


# ── Filter that injects corr_id into every LogRecord ─────────────────────────

class _CorrIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.corr_id = corr_id_var.get("")  # type: ignore[attr-defined]
        return True


# ── JSON Formatter ────────────────────────────────────────────────────────────

class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc)
                        .isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "corr_id": getattr(record, "corr_id", ""),
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1] is not None:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


# ── Setup ─────────────────────────────────────────────────────────────────────

def setup_logging() -> None:
    """Configure root logger with console (human) + file (JSON) handlers."""
    root = logging.getLogger()
    level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    root.setLevel(level)

    corr_filter = _CorrIdFilter()

    # ── Console handler (human-readable) ──────────────────────────────────
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s [%(name)s] %(message)s")
    )
    console.addFilter(corr_filter)
    root.addHandler(console)

    # ── File handler (JSON, rotating) ─────────────────────────────────────
    log_path = config.LOG_DIR / "jarvis.log"
    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUPS,
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(_JSONFormatter())
    file_handler.addFilter(corr_filter)
    root.addHandler(file_handler)
