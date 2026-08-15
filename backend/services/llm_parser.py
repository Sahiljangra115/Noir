"""
pipeline/llm_parser.py
───────────────────────
Sends the transcribed voice command to Gemma 4 (via Ollama) and
parses the reply into a structured JSON object containing:

    {
        "speech":  "short spoken confirmation",
        "actions": [ ...action tokens... ]
    }

Action token catalogue
──────────────────────
Mode changes:
    {"type": "mode",  "value": "LFR"}           ← follow a line
    {"type": "mode",  "value": "HUMAN_TRACK"}   ← follow a person
    {"type": "mode",  "value": "VLA"}           ← autonomous AI vision
    {"type": "mode",  "value": "MANUAL"}        ← hold last command
    {"type": "mode",  "value": "IDLE"}          ← stop

Timed movement:
    {"type": "move",  "cmd": "F", "duration": 5.0}   ← forward 5 s
    {"type": "move",  "cmd": "B", "duration": 2.0}   ← backward 2 s
    {"type": "move",  "cmd": "L", "duration": 1.5}   ← turn left 1.5 s
    {"type": "move",  "cmd": "R", "duration": 1.5}   ← turn right 1.5 s

This catalogue is the whole vocabulary. ``goto`` and ``arm`` tokens used to be
accepted here, but no CV mode navigates to a target and the ESP32 firmware has
no arm: both ended up parking the robot in a mode the CV loop does not
recognise. They were removed rather than left as schema that lies about the
hardware. Re-add them alongside the code that executes them, not before.
"""

import json
import logging
import random
import re
import time
from typing import List, Literal, Union, Annotated

import requests
from pydantic import BaseModel, Field

from backend.config import config

log = logging.getLogger(__name__)


def _post_with_retry(url: str, *, json: dict, timeout: float, retries: int, base: float):
    """POST with exponential backoff + jitter on Timeout/ConnectionError/5xx.

    Raises the last network exception if all retries fail.
    """
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, json=json, timeout=timeout)
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exc = exc
            if attempt == retries:
                break
            delay = base * (2 ** attempt) + random.uniform(0, base)
            log.warning("[LLM] retry %d/%d after %.2fs: %s", attempt + 1, retries, delay, exc)
            time.sleep(delay)
            continue

        # requests.post itself never raises on a 5xx, so the status has to be
        # inspected here for the documented server-error retry to happen at all.
        if 500 <= resp.status_code < 600 and attempt < retries:
            delay = base * (2 ** attempt) + random.uniform(0, base)
            log.warning("[LLM] retry on HTTP %d after %.2fs", resp.status_code, delay)
            time.sleep(delay)
            continue
        return resp

    assert last_exc is not None
    raise last_exc

# ── Action Models ─────────────────────────────────────────────────────────────

# Only modes the CV loop in backend/main.py actually dispatches on.
VALID_MODES = ("LFR", "HUMAN_TRACK", "VLA", "MANUAL", "IDLE")

class ModeAction(BaseModel):
    type: Literal["mode"]
    value: Literal["LFR", "HUMAN_TRACK", "VLA", "MANUAL", "IDLE"]

class MoveAction(BaseModel):
    type: Literal["move"]
    cmd: Literal["F", "B", "L", "R", "S"]
    # Upper bound mirrors config.MOVE_MAX_DURATION_S, which the executor also
    # clamps to. Keeping them aligned stops the schema advertising a range the
    # command queue will silently cut down.
    duration: float = Field(default=1.0, ge=0.1, le=config.MOVE_MAX_DURATION_S)

# Discriminated union for automatic sub-model selection
RobotAction = Annotated[
    Union[ModeAction, MoveAction],
    Field(discriminator="type")
]

class LLMResponse(BaseModel):
    speech: str = "Done."
    actions: List[RobotAction] = Field(default_factory=list)

# ── Ollama endpoint ───────────────────────────────────────────────────────────
# Single source of truth: backend.config (env-driven). Falls back to the
# documented Gemma 4 model / local Ollama if env is unset.
_OLLAMA_URL    = config.OLLAMA_URL.rstrip("/") + "/api/generate"
_DEFAULT_MODEL = config.OLLAMA_MODEL          # gemma4-e2b-nothink:latest


# ── System prompt ─────────────────────────────────────────────────────────────
# Injected once per request. The placeholders are replaced at call time.
#
# The action catalogue has to be spelled out here. Without it the model has no
# way to know the token shape and answers every "drive forward" with speech and
# an empty actions list, which looks like the robot ignoring voice commands.
_SYSTEM_PROMPT = """\
You are jarvis — an AI assistant controlling a wheeled robot.
Current Mode: {mode}
Last Command: {last_cmd}
Vision Context: {yolo_info}

Reply with ONLY a raw JSON object — no markdown, no preamble, no reasoning:
{"speech": "one short spoken sentence", "actions": [ ... ]}

"actions" is a list. Leave it empty for conversation. When the user asks the
robot to do something physical, put one or more of these tokens in it:

  {"type": "move", "cmd": "F", "duration": 2.0}
      Drive for a fixed time. cmd is F (forward), B (backward),
      L (turn left), R (turn right) or S (stop).
      duration is seconds, between 0.1 and MAX_DURATION.

  {"type": "mode", "value": "LFR"}
      Switch behaviour. value is one of:
        LFR          follow a line on the floor
        HUMAN_TRACK  follow the nearest person
        VLA          drive autonomously from camera vision
        MANUAL       hold the last command
        IDLE         stop and stand by

Examples:
  "go forward for three seconds" ->
    {"speech": "Moving forward.", "actions": [{"type": "move", "cmd": "F", "duration": 3.0}]}
  "follow me" ->
    {"speech": "Following you.", "actions": [{"type": "mode", "value": "HUMAN_TRACK"}]}
  "what can you see" ->
    {"speech": "A person straight ahead.", "actions": []}

Use no other action types and no other field names."""


# Keywords that should NEVER reach the LLM (handled by fast path in pipeline)
EMERGENCY_KEYWORDS: frozenset[str] = frozenset({
    "stop", "halt", "freeze", "abort", "emergency", "cancel",
})


class LLMParser:
    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        url:   str = _OLLAMA_URL,
    ) -> None:
        self.model = model
        self.url   = url
        log.info("[LLM] Parser ready – model=%s", model)

    # ── Public API ────────────────────────────────────────────────────────────

    def parse(self, text: str, state_snapshot: dict, *, corr_id: str = "") -> dict:
        """
        Send `text` + current robot state to Gemma 4, return parsed dict.
        Falls back to a safe idle response on any error.
        """
        log.info("[LLM] parse request  corr_id=%s  text=%r", corr_id, text[:80])
        prompt = (
            _SYSTEM_PROMPT
            .replace("{mode}",      state_snapshot.get("mode",      "IDLE"))
            .replace("{last_cmd}",  state_snapshot.get("last_cmd",  "S"))
            .replace("{yolo_info}", state_snapshot.get("yolo_info", "no detections"))
            .replace("MAX_DURATION", f"{config.MOVE_MAX_DURATION_S:g}")
        ) + f'\n\nUser said: "{text}"'

        payload = {
            "model":  self.model,
            "prompt": prompt,
            "format": "json",        # Ollama forces JSON output
            "stream": False,
            "think": False,          # Ollama's flag for suppressing reasoning output
            "options": {
                "temperature": 0.1,  # low temp → deterministic structured output
                "num_predict": 300,
            },
        }

        t0 = time.monotonic()
        try:
            resp = _post_with_retry(
                self.url,
                json=payload,
                timeout=config.OLLAMA_TIMEOUT_S,
                retries=config.OLLAMA_MAX_RETRIES,
                base=config.OLLAMA_BACKOFF_BASE,
            )
            resp.raise_for_status()
            full_data = resp.json()
            
            # Reasoning Support: check 'response' first, then 'thinking'
            raw = full_data.get("response", "").strip()
            if not raw and "thinking" in full_data:
                log.debug("[LLM] Model output found in 'thinking' field")
                raw = full_data.get("thinking", "").strip()
            
        except requests.exceptions.Timeout:
            log.warning("[LLM] Timeout after %.1fs", config.OLLAMA_TIMEOUT_S)
            return self._fallback("Sorry, I timed out processing that.")
        except Exception as exc:
            log.error("[LLM] Request error: %s", exc)
            return self._fallback("I had a connection error.")

        elapsed = time.monotonic() - t0
        log.info("[LLM] response received  corr_id=%s  elapsed=%.2fs", corr_id, elapsed)
        log.debug("[LLM] raw=%r  (%.2fs)", raw[:120], elapsed)

        return self._parse_json(raw)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _parse_json(self, raw: str) -> dict:
        """
        Robust JSON extractor using Pydantic for validation.
        """
        # Strip markdown code fences if present
        raw = re.sub(r"```(?:json)?", "", raw).strip()

        # Try to find a JSON block if it's not a pure JSON string
        if not (raw.startswith("{") and raw.endswith("}")):
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                raw = match.group()

        try:
            # Validate and sanitize using Pydantic
            response_model = LLMResponse.model_validate_json(raw)
            result = response_model.model_dump()
        except Exception as exc:
            log.warning("[LLM] Validation failed: %s", exc)
            # Try to at least get the speech if the whole thing failed
            try:
                partial = json.loads(raw)
                speech = partial.get("speech", "I had trouble understanding that.")
                return self._fallback(speech)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                log.warning("LLM parse failed: %s", exc)
                return self._fallback("I produced an invalid response.")

        log.debug(
            "[LLM] speech=%r  actions=%s",
            result["speech"],
            result["actions"],
        )
        return result

    @staticmethod
    def _fallback(speech: str) -> dict:
        return {"speech": speech, "actions": []}
