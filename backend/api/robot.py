from flask import Blueprint, request, jsonify
from typing import Any, Dict
from pydantic import BaseModel, ValidationError
import json

robot_api = Blueprint("api", __name__)

# CommandQueue and RobotState will be injected via set_pipeline_refs()
_command_queue = None
_robot_state = None

def set_pipeline_refs(command_queue, robot_state):
    global _command_queue, _robot_state
    _command_queue = command_queue
    _robot_state = robot_state

# Pydantic model for POST /api/robot/command
class RobotCommand(BaseModel):
    type: str

@robot_api.route("/api/robot/command", methods=["POST"])
def robot_command():
    if _command_queue is None:
        return jsonify({"error": "Command queue unavailable"}), 500
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Malformed JSON"}), 400
    try:
        validated = RobotCommand(**data)
    except ValidationError as e:
        return jsonify({"error": "Validation error", "details": json.loads(e.json())}), 400
    try:
        _command_queue.put(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"status": "queued"})

@robot_api.route("/api/robot/state", methods=["GET"])
def robot_state_():
    if _robot_state is None:
        return jsonify({"error": "Robot state unavailable"}), 500
    try:
        state_snapshot = _robot_state.snapshot() if hasattr(_robot_state, "snapshot") else dict(_robot_state)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"state": state_snapshot})

@robot_api.route("/api/llm/query", methods=["POST"])
def llm_query():
    return jsonify({"error": "Not implemented"}), 501
