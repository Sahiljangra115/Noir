"""
pipeline/llm_parser.py
───────────────────────
Sends the transcribed voice command to Gemma 3 4B (via Ollama) and
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
import re
import time

import requests

log = logging.getLogger(__name__)

# ── Ollama endpoint ───────────────────────────────────────────────────────────
_OLLAMA_URL    = "http://localhost:11434/api/generate"
_DEFAULT_MODEL = "gemma3:4b-it-q4_K_M"
_TIMEOUT_S     = 15          # s – gemma3 4b is fast with int4

# ── System prompt ─────────────────────────────────────────────────────────────
# Injected once per request.  {state} is replaced at call time.
_SYSTEM_PROMPT = """\
You are JARVIS — an AI assistant crammed into a wheeled robot by a student \
who probably had better things to do during their final year.

Your personality:
- Sharp, witty, and a bit of a smartass — but genuinely helpful
- Keep answers SHORT and punchy. One or two sentences max for simple questions.
- Add dry humour or a light joke when it fits naturally, not forced
- If the question is genuinely interesting, you can go a little longer — but never waffle
- Never say "Certainly!" or "Of course!" — just answer

For GENERAL questions (greetings, curiosity, knowledge, conversation):
- Give a crisp, clever answer in the "speech" field
- Set "actions" to []

For ROBOT COMMANDS embed action tokens in "actions" and confirm in one short sentence in "speech".
Available action tokens:
  {"type":"mode",  "value":"LFR"}            → follow a line
  {"type":"mode",  "value":"HUMAN"}          → follow a person
  {"type":"mode",  "value":"VLA"}            → full autonomous vision mode
  {"type":"mode",  "value":"IDLE"}           → stop everything
  {"type":"move",  "cmd":"F","duration":N}   → forward N seconds
  {"type":"move",  "cmd":"B","duration":N}   → backward N seconds
  {"type":"move",  "cmd":"L","duration":N}   → turn left N seconds
  {"type":"move",  "cmd":"R","duration":N}   → turn right N seconds
  {"type":"goto",  "target":"<label>"}       → navigate to named object
  {"type":"arm",   "cmd":"GRAB"}             → close gripper
  {"type":"arm",   "cmd":"RELEASE"}          → open gripper
  {"type":"arm",   "cmd":"UP"}               → raise arm
  {"type":"arm",   "cmd":"DOWN"}             → lower arm

Rules:
1. For compound commands produce multiple tokens in order.
2. If unclear, ask for clarification in "speech", actions:[].
3. Never invent action types outside the list.
4. For stop/halt/freeze: {"type":"mode","value":"IDLE"}.
5. Reply with ONLY a raw JSON object — no markdown, no preamble.

Current robot state:
  mode      = {mode}
  last_cmd  = {last_cmd}
  camera    = {yolo_info}

Respond with ONLY this JSON:
{"speech": "...", "actions": [...]}"""

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

    def parse(self, text: str, state_snapshot: dict) -> dict:
        """
        Send `text` + current robot state to Gemma 3, return parsed dict.
        Falls back to a safe idle response on any error.
        """
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
            "options": {
                "temperature": 0.1,  # low temp → deterministic structured output
                "num_predict": 300,
            },
        }

        t0 = time.monotonic()
        try:
            resp = requests.post(self.url, json=payload, timeout=_TIMEOUT_S)
            resp.raise_for_status()
            raw = resp.json().get("response", "{}").strip()
        except requests.exceptions.Timeout:
            log.warning("[LLM] Timeout after %ds", _TIMEOUT_S)
            return self._fallback("Sorry, I timed out processing that.")
        except Exception as exc:
            log.error("[LLM] Request error: %s", exc)
            return self._fallback("I had a connection error.")

        elapsed = time.monotonic() - t0
        log.debug("[LLM] raw=%r  (%.2fs)", raw[:120], elapsed)

        return self._parse_json(raw)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _parse_json(self, raw: str) -> dict:
        """
        Robust JSON extractor.  Gemma 3 with format=json rarely adds noise,
        but this handles edge cases where it wraps the JSON in markdown fences.
        """
        # Strip markdown code fences if present
        raw = re.sub(r"```(?:json)?", "", raw).strip()

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            # Try to extract just the first {...} block
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                try:
                    result = json.loads(match.group())
                except json.JSONDecodeError:
                    return self._fallback("I couldn't parse my own response.")
            else:
                return self._fallback("I produced an invalid response.")

        # Validate structure
        if not isinstance(result.get("speech"), str):
            result["speech"] = "Done."
        if not isinstance(result.get("actions"), list):
            result["actions"] = []

        # Sanitise actions — drop anything with unknown type
        _valid_types = {"mode", "move", "goto", "arm"}
        result["actions"] = [
            a for a in result["actions"]
            if isinstance(a, dict) and a.get("type") in _valid_types
        ]

        log.debug(
            "[LLM] speech=%r  actions=%s",
            result["speech"],
            result["actions"],
        )
        return result

    @staticmethod
    def _fallback(speech: str) -> dict:
        return {"speech": speech, "actions": []}
