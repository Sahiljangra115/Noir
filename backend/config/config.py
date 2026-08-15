"""
backend/config/config.py
─────────────────────────
Single source of truth for runtime configuration.

All tunables and external integration parameters are read from environment
variables via typed helpers. ``validate_config()`` is invoked from
``backend/main.py`` startup; it raises ``ConfigError`` on missing/invalid
values so the process exits early rather than failing deep inside a service.
"""

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


# ── Exception ────────────────────────────────────────────────────────────────

class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


# ── Typed env helpers (private) ──────────────────────────────────────────────

def _env_str(name: str, default: str | None = None, *, required: bool = False) -> str:
    val = os.environ.get(name)
    if val is None or val == "":
        if required:
            raise ConfigError(f"Required environment variable {name!r} is not set")
        return default if default is not None else ""
    return val


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"Environment variable {name!r} must be int, got {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"Environment variable {name!r} must be float, got {raw!r}") from exc


def _env_path_required(name: str, default: Path | None = None, *, kind: str = "file") -> Path:
    """Resolve a path from env. ``kind`` is ``"file"`` (existence checked later)
    or ``"dir"`` (created if missing). If ``default`` is provided and the env
    var is unset, the default is used; otherwise raises ``ConfigError``.
    """
    raw = os.environ.get(name)
    if raw is None or raw == "":
        if default is None:
            raise ConfigError(f"Required path environment variable {name!r} is not set")
        path = default
    else:
        path = Path(raw).expanduser()

    if kind == "dir":
        path.mkdir(parents=True, exist_ok=True)
        return path
    return path


# ── Camera ───────────────────────────────────────────────────────────────────

CAMERA_ALIAS_RESOLVE = {
    "laptop": 0,
    "mobile": "/dev/video2",
    "phone": "/dev/video2",
}

DEFAULT_CAMERA_DEVICE = "laptop"


# ── Web / CORS ───────────────────────────────────────────────────────────────

_origins_raw = _env_str(
    "JARVIS_ALLOWED_ORIGINS",
    default="http://localhost,http://localhost:5173,http://127.0.0.1,http://127.0.0.1:5000,http://192.168.31.95:5000",
)
ALLOWED_ORIGINS = [o.strip() for o in _origins_raw.split(",") if o.strip()]


# ── Auth ─────────────────────────────────────────────────────────────────────

# Read at import time but enforce required-ness in validate_config() so test
# tooling that imports the module without the env set doesn't crash.
JARVIS_SECRET_KEY = _env_str("JARVIS_SECRET_KEY", default="")


# ── Ollama ───────────────────────────────────────────────────────────────────

OLLAMA_URL = _env_str("JARVIS_OLLAMA_URL", default="http://localhost:11434")
OLLAMA_MODEL = _env_str("JARVIS_OLLAMA_MODEL", default="gemma4-e2b-nothink:latest")
# A cold Ollama load costs 20-40 s on first call and structured generation adds
# more. The old 5 s default timed out nearly every first voice command and the
# user heard "Sorry, I timed out" instead of an answer.
OLLAMA_TIMEOUT_S = _env_float("JARVIS_OLLAMA_TIMEOUT_S", 30.0)
OLLAMA_MAX_RETRIES = _env_int("JARVIS_OLLAMA_MAX_RETRIES", 1)
OLLAMA_BACKOFF_BASE = _env_float("JARVIS_OLLAMA_BACKOFF_BASE", 1.5)


# ── Voice (Piper TTS / Whisper STT) ──────────────────────────────────────────

VOICE_ENABLED = _env_str("JARVIS_VOICE", default="1") == "1"

# These are validated to exist + be executable when VOICE_ENABLED.
PIPER_BIN = _env_str("JARVIS_PIPER_BIN", default="")
PIPER_MODEL = _env_str("JARVIS_PIPER_MODEL", default="")
PIPER_CONFIG = _env_str("JARVIS_PIPER_CONFIG", default="")

WHISPER_MODEL = _env_str("JARVIS_WHISPER_MODEL", "small.en")
WHISPER_DEVICE = _env_str("JARVIS_WHISPER_DEVICE", "auto")

# Wake word. Must be a key of wake_word._KEYWORD_TO_MODEL_FILE — openWakeWord
# ships a fixed set of stock models and "noir"/"jarvis" is not trainable here.
WAKE_KEYWORD = _env_str("JARVIS_WAKE_KEYWORD", "hey_jarvis")
WAKE_SENSITIVITY = _env_float("JARVIS_WAKE_SENSITIVITY", 0.5)


# ── ESP32 ────────────────────────────────────────────────────────────────────

ESP32_HOST = _env_str("JARVIS_ESP32_HOST", default="0.0.0.0")
ESP32_PORT = _env_int("JARVIS_ESP32_PORT", 9999)
ESP32_RECONNECT_BASE_S = _env_float("JARVIS_ESP32_RECONNECT_BASE_S", 1.0)
ESP32_RECONNECT_MAX_S = _env_float("JARVIS_ESP32_RECONNECT_MAX_S", 30.0)


# ── Queues ───────────────────────────────────────────────────────────────────

CMD_QUEUE_MAX = _env_int("JARVIS_CMD_QUEUE_MAX", 128)
MOVE_MAX_DURATION_S = _env_float("JARVIS_MOVE_MAX_DURATION_S", 5.0)


# ── Web payload limits ───────────────────────────────────────────────────────

MAX_AUDIO_PAYLOAD_BYTES = _env_int("JARVIS_MAX_AUDIO_PAYLOAD_BYTES", 512_000)
MAX_SENSOR_PAYLOAD_BYTES = _env_int("JARVIS_MAX_SENSOR_PAYLOAD_BYTES", 8_192)


# ── Logging ──────────────────────────────────────────────────────────────────

LOG_DIR: Path = _env_path_required(
    "JARVIS_LOG_DIR",
    default=Path.home() / ".jarvis" / "logs",
    kind="dir",
)
LOG_LEVEL = _env_str("JARVIS_LOG_LEVEL", "INFO")
LOG_MAX_BYTES = _env_int("JARVIS_LOG_MAX_BYTES", 10 * 1024 * 1024)
LOG_BACKUPS = _env_int("JARVIS_LOG_BACKUPS", 5)


# ── Validation + summary ─────────────────────────────────────────────────────

def _mask(secret: str) -> str:
    if not secret:
        return "<unset>"
    if len(secret) <= 6:
        return "***"
    return f"{secret[:3]}***{secret[-2:]}"


def summary() -> dict:
    """Return a redacted snapshot of resolved configuration for diagnostics."""
    return {
        "camera_default": DEFAULT_CAMERA_DEVICE,
        "allowed_origins": ALLOWED_ORIGINS,
        "secret_key": _mask(JARVIS_SECRET_KEY),
        "ollama_url": OLLAMA_URL,
        "ollama_model": OLLAMA_MODEL,
        "ollama_timeout_s": OLLAMA_TIMEOUT_S,
        "ollama_max_retries": OLLAMA_MAX_RETRIES,
        "voice_enabled": VOICE_ENABLED,
        "piper_bin": PIPER_BIN or "<unset>",
        "piper_model": PIPER_MODEL or "<unset>",
        "piper_config": PIPER_CONFIG or "<unset>",
        "whisper_model": WHISPER_MODEL,
        "whisper_device": WHISPER_DEVICE,
        "wake_keyword": WAKE_KEYWORD,
        "wake_sensitivity": WAKE_SENSITIVITY,
        "esp32_host": ESP32_HOST,
        "esp32_port": ESP32_PORT,
        "cmd_queue_max": CMD_QUEUE_MAX,
        "move_max_duration_s": MOVE_MAX_DURATION_S,
        "max_audio_payload_bytes": MAX_AUDIO_PAYLOAD_BYTES,
        "max_sensor_payload_bytes": MAX_SENSOR_PAYLOAD_BYTES,
        "log_dir": str(LOG_DIR),
        "log_level": LOG_LEVEL,
    }


def validate_config() -> None:
    """Validate that all required configuration is present and consistent.

    Raises ``ConfigError`` on any failure. Logs a single redacted summary line
    on success.
    """
    if not JARVIS_SECRET_KEY:
        raise ConfigError(
            "JARVIS_SECRET_KEY is required but not set (export it in .env or shell)"
        )

    if VOICE_ENABLED:
        if not PIPER_BIN:
            raise ConfigError("VOICE_ENABLED=1 but JARVIS_PIPER_BIN is unset")
        piper_path = Path(PIPER_BIN).expanduser()
        if not piper_path.exists():
            raise ConfigError(f"JARVIS_PIPER_BIN does not exist: {piper_path}")
        if not os.access(piper_path, os.X_OK):
            raise ConfigError(f"JARVIS_PIPER_BIN is not executable: {piper_path}")
        for label, raw in (("JARVIS_PIPER_MODEL", PIPER_MODEL),
                           ("JARVIS_PIPER_CONFIG", PIPER_CONFIG)):
            if not raw:
                raise ConfigError(f"VOICE_ENABLED=1 but {label} is unset")
            if not Path(raw).expanduser().exists():
                raise ConfigError(f"{label} does not exist: {raw}")

    if WAKE_KEYWORD:
        from backend.services.wake_word import _KEYWORD_TO_MODEL_FILE
        if WAKE_KEYWORD not in _KEYWORD_TO_MODEL_FILE:
            raise ConfigError(
                f"JARVIS_WAKE_KEYWORD={WAKE_KEYWORD!r} has no openWakeWord model. "
                f"Choose one of: {sorted(_KEYWORD_TO_MODEL_FILE)}"
            )
    if not 0.0 < WAKE_SENSITIVITY <= 1.0:
        raise ConfigError(f"JARVIS_WAKE_SENSITIVITY must be in (0, 1] ({WAKE_SENSITIVITY})")

    if OLLAMA_MAX_RETRIES < 0:
        raise ConfigError(f"JARVIS_OLLAMA_MAX_RETRIES must be >= 0 ({OLLAMA_MAX_RETRIES})")
    if MOVE_MAX_DURATION_S <= 0:
        raise ConfigError(f"JARVIS_MOVE_MAX_DURATION_S must be > 0 ({MOVE_MAX_DURATION_S})")
    if CMD_QUEUE_MAX <= 0:
        raise ConfigError(f"JARVIS_CMD_QUEUE_MAX must be > 0 ({CMD_QUEUE_MAX})")

    log.info("[CONFIG] resolved %s", summary())
