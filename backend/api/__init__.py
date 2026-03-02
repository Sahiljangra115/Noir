"""
Wires up the API blueprint and exposes a function to set pipeline refs (CommandQueue, RobotState).
"""
from .robot import robot_api, set_pipeline_refs

def create_api_blueprint(command_queue, robot_state):
    """
    Factory to return blueprint with pipeline references injected.
    """
    set_pipeline_refs(command_queue, robot_state)
    return robot_api

__all__ = ["create_api_blueprint"]
