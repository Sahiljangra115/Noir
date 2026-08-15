from flask import Blueprint, request, jsonify
from pydantic import TypeAdapter, ValidationError
import json
import os
import hmac
from functools import wraps
from dotenv import load_dotenv

from backend.services.llm_parser import RobotAction

# Load environment variables
load_dotenv()

robot_api = Blueprint("api", __name__)

# CommandQueue and RobotState will be injected via set_pipeline_refs()
_command_queue = None
_robot_state = None

def set_pipeline_refs(command_queue, robot_state):
    global _command_queue, _robot_state
    _command_queue = command_queue
    _robot_state = robot_state

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        expected = os.getenv('JARVIS_SECRET_KEY')
        if not expected:
            return jsonify({"status": "error", "msg": "Server auth misconfigured"}), 503
        if not token:
            return jsonify({"status": "error", "msg": "Unauthorized"}), 401
        # Bytes compare: hmac.compare_digest raises TypeError on non-ASCII str,
        # which would turn a bad token into a 500 instead of a 401.
        if not hmac.compare_digest(token.encode("utf-8"), f"Bearer {expected}".encode("utf-8")):
            return jsonify({"status": "error", "msg": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# The same discriminated union the LLM output is validated against. The old
# model here only required a `type` string, so this endpoint was a hole straight
# past the schema: any authenticated caller could enqueue an arbitrary dict.
_ACTION_ADAPTER = TypeAdapter(RobotAction)


@robot_api.route("/api/robot/command", methods=["POST"])
@require_auth
def robot_command():
    if _command_queue is None:
        return jsonify({"error": "Command queue unavailable"}), 500
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Malformed JSON"}), 400
    try:
        action = _ACTION_ADAPTER.validate_python(data)
    except ValidationError as e:
        return jsonify({"error": "Validation error", "details": json.loads(e.json())}), 400
    try:
        # Enqueue the validated+normalised action, not the raw request body.
        _command_queue.push(action.model_dump())
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"status": "queued"})

@robot_api.route("/api/robot/state", methods=["GET"])
@require_auth
def robot_state_():
    if _robot_state is None:
        return jsonify({"error": "Robot state unavailable"}), 500
    try:
        state_snapshot = _robot_state.snapshot()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"state": state_snapshot})


# Built on first use: constructing an LLMParser is cheap but pointless until
# somebody actually calls the endpoint.
_llm_parser = None


@robot_api.route("/api/llm/query", methods=["POST"])
@require_auth
def llm_query():
    """Text-in / {speech, actions}-out. The voice pipeline without the microphone.

    Body: {"text": "...", "execute": true}
    ``execute`` defaults to false so a caller can inspect the plan before the
    robot acts on it.
    """
    global _llm_parser

    if _robot_state is None:
        return jsonify({"error": "Robot state unavailable"}), 500

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Malformed JSON"}), 400

    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        return jsonify({"error": "'text' is required"}), 400
    if len(text) > 2000:
        return jsonify({"error": "'text' too long"}), 413

    execute = bool(data.get("execute", False))

    if _llm_parser is None:
        from backend.services.llm_parser import LLMParser
        _llm_parser = LLMParser()

    result = _llm_parser.parse(text, _robot_state.snapshot())

    executed = False
    actions = result.get("actions") or []
    if execute and actions and _command_queue is not None:
        _command_queue.push_all(actions)
        executed = True

    return jsonify({**result, "executed": executed})
