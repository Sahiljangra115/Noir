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
    {"type": "mode",  "value": "LFR"}          ← follow a line
    {"type": "mode",  "value": "HUMAN"}         ← follow a person
    {"type": "mode",  "value": "VLA"}           ← autonomous AI vision
    {"type": "mode",  "value": "IDLE"}          ← stop

Timed movement:
    {"type": "move",  "cmd": "F", "duration": 5.0}   ← forward 5 s
    {"type": "move",  "cmd": "B", "duration": 2.0}   ← backward 2 s
    {"type": "move",  "cmd": "L", "duration": 1.5}   ← turn left 1.5 s
    {"type": "move",  "cmd": "R", "duration": 1.5}   ← turn right 1.5 s

Goal navigation:
    {"type": "goto",  "target": "red box"}            ← navigate to object

Arm control (requires physical arm on ESP32):
    {"type": "arm",   "cmd": "GRAB"}
    {"type": "arm",   "cmd": "RELEASE"}
    {"type": "arm",   "cmd": "UP"}
    {"type": "arm",   "cmd": "DOWN"}
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
            return requests.post(url, json=json, timeout=timeout)
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exc = exc
            if attempt == retries:
                break
            delay = base * (2 ** attempt) + random.uniform(0, base)
            log.warning("[LLM] retry %d/%d after %.2fs: %s", attempt + 1, retries, delay, exc)
            time.sleep(delay)
        except requests.HTTPError as exc:
            if 500 <= exc.response.status_code < 600 and attempt < retries:
                delay = base * (2 ** attempt) + random.uniform(0, base)
                log.warning("[LLM] retry on 5xx after %.2fs", delay)
                time.sleep(delay)
                continue
            raise
    assert last_exc is not None
    raise last_exc

# ── Action Models ─────────────────────────────────────────────────────────────

class ModeAction(BaseModel):
    type: Literal["mode"]
    value: Literal["LFR", "HUMAN_TRACK", "VLA", "GOTO", "MANUAL", "IDLE"]

class MoveAction(BaseModel):
    type: Literal["move"]
    cmd: Literal["F", "B", "L", "R", "S"]
    duration: float = Field(default=1.0, ge=0.1, le=30.0)

class GotoAction(BaseModel):
    type: Literal["goto"]
    target: str

class ArmAction(BaseModel):
    type: Literal["arm"]
    cmd: Literal["GRAB", "RELEASE", "UP", "DOWN"]

# Discriminated union for automatic sub-model selection
RobotAction = Annotated[
    Union[ModeAction, MoveAction, GotoAction, ArmAction],
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
_TIMEOUT_S     = 20          # s – give it more time for structured output


# ── System prompt ─────────────────────────────────────────────────────────────
# Injected once per request.  {state} is replaced at call time.
_SYSTEM_PROMPT = """\
You are jarvis — an AI assistant for a wheeled robot.
Current Mode: {mode}
Last Command: {last_cmd}
Vision Context: {yolo_info}

IMPORTANT: DO NOT include any thinking process or reasoning out loud.

Respond with ONLY a raw JSON object — no markdown, no preamble.

Respond with ONLY a JSON object in this format:
{"speech": "put your response text here", "actions": []}"""


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
        ) + f'\n\nUser said: "{text}"'

        payload = {
            "model":  self.model,
            "prompt": prompt,
            "format": "json",        # Ollama forces JSON output
            "stream": False,
            "include_thinking": False,  # Disable reasoning
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
            log.warning("[LLM] Timeout after %ds", _TIMEOUT_S)
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
