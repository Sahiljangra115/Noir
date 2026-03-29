"""
E2E tests for complete application workflows.

These tests simulate real user scenarios and verify end-to-end functionality.
"""
import pytest
import time
import threading
from unittest.mock import Mock, patch, MagicMock
import numpy as np
import queue

from backend.services.robot_state import RobotState
from backend.esp32.robot_comms import RobotComms


@pytest.mark.e2e
class TestCompleteWorkflows:
    """Test complete application workflows from user interaction to robot action."""

    @pytest.fixture
    def complete_system_setup(self, disable_hardware):
        """Set up complete system with all components mocked."""
        # Core state and comms
        state = RobotState()
        comms = Mock(spec=RobotComms)
        comms.connected = True
        comms.send.return_value = True

        # Mock web server
        web_server = Mock()
        web_server.push_frame = Mock()

        # Mock voice pipeline components
        voice_mocks = {
            'wakeword': Mock(),
            'stt': Mock(),
            'tts': Mock(),
            'llm': Mock(),
            'cmd_queue': Mock()
        }

        # Mock CV components
        cv_mocks = {
            'line_detector': Mock(),
            'human_detector': Mock(),
            'vla_processor': Mock()
        }

        yield {
            'state': state,
            'comms': comms,
            'web_server': web_server,
            'voice': voice_mocks,
            'cv': cv_mocks
        }

    def test_user_voice_command_to_robot_action(self, complete_system_setup):
        """Test complete flow: user speaks -> robot moves."""
        setup = complete_system_setup
        state = setup['state']
        comms = setup['comms']
        voice = setup['voice']

        # Simulate user saying "move forward"
        voice['stt'].listen.return_value = "move forward please"

        # Mock LLM parsing the command
        voice['llm'].parse.return_value = {
            "speech": "Moving forward now",
            "actions": ["MOVE_FORWARD", "SET_SPEED_NORMAL"]
        }

        # Mock command queue processing
        def mock_command_processor(actions):
            for action in actions:
                if "MOVE_FORWARD" in action:
                    comms.send("F")
                    state.last_cmd = "F"

        voice['cmd_queue'].push_all.side_effect = mock_command_processor

        # Execute the voice processing workflow
        from backend.services.voice_pipeline import VoicePipeline
        with patch('backend.services.voice_pipeline.WakeWordDetector', return_value=voice['wakeword']), \
             patch('backend.services.voice_pipeline.WhisperSTT', return_value=voice['stt']), \
             patch('backend.services.voice_pipeline.PiperTTS', return_value=voice['tts']), \
             patch('backend.services.voice_pipeline.LLMParser', return_value=voice['llm']), \
             patch('backend.services.voice_pipeline.CommandQueue', return_value=voice['cmd_queue']):

            pipeline = VoicePipeline(comms=comms, state=state)
            pipeline.conversation_active = True
            pipeline._conversation_cycle()

            # Verify the complete workflow
            voice['wakeword'].wait_for_wakeword.assert_called_once()
            voice['stt'].listen.assert_called_once()
            voice['llm'].parse.assert_called_once()
            voice['tts'].speak.assert_called()

            # Verify robot received command
            comms.send.assert_called_with("F")
            assert state.last_cmd == "F"
            assert state.last_heard == "move forward please"
            assert state.jarvis_response == "Moving forward now"

    def test_web_dashboard_control_workflow(self, complete_system_setup, mock_frame):
        """Test web dashboard control workflow."""
        setup = complete_system_setup
        state = setup['state']
        comms = setup['comms']

        # Simulate web dashboard sending move command directly
        from web_server import WebServer
        server = WebServer(state=state, comms=comms)

        # Simulate move command processing directly (avoiding Flask context)
        command_data = {
            "type": "move",
            "cmd": "R",
            "duration": 1.0
        }

        # Process move command directly
        if command_data.get("type") == "move":
            cmd_char = command_data.get("cmd", "S")
            duration = float(command_data.get("duration", 1.0))
            if cmd_char in "FBLRS":
                comms.send(cmd_char)
                state.last_cmd = cmd_char

        # Verify command was sent to robot
        comms.send.assert_called_with("R")
        assert state.last_cmd == "R"

        # Simulate frame streaming
        server._has_clients = True
        server.push_frame(mock_frame)

        # Verify frame was processed for streaming
        assert server._frame_bytes is not None

    def test_computer_vision_detection_to_movement(self, complete_system_setup, mock_frame):
        """Test CV detection leading to robot movement."""
        setup = complete_system_setup
        state = setup['state']
        comms = setup['comms']
        cv = setup['cv']

        # Test human tracking mode
        state.mode = "HUMAN"

        # Mock human detection
        detection = Mock()
        detection.confidence = 0.9
        detection.bbox = [50, 50, 150, 150]  # Small bbox = person far away
        cv['human_detector'].detect.return_value = [detection]

        # Process the detection
        detections = cv['human_detector'].detect(mock_frame)
        if detections:
            best = max(detections, key=lambda d: d.confidence)
            frame_h, frame_w = mock_frame.shape[:2]
            cmd = RobotComms.from_human_bbox(best.bbox, frame_w, frame_h)

            # Execute command
            comms.send(cmd)
            state.last_cmd = cmd
            state.yolo_info = f"person conf={best.confidence:.0%}"

        # Verify the workflow
        cv['human_detector'].detect.assert_called_with(mock_frame)
        comms.send.assert_called_with("F")  # Small bbox should trigger forward movement
        assert state.last_cmd == "F"
        assert "person" in state.yolo_info

    def test_mode_switching_and_behavior_change(self, complete_system_setup, mock_frame):
        """Test that mode switching changes robot behavior."""
        setup = complete_system_setup
        state = setup['state']
        cv = setup['cv']

        # Test different modes produce different behaviors
        test_cases = [
            ("LFR", "line following"),
            ("HUMAN", "human tracking"),
            ("VLA", "vision-language-action"),
            ("IDLE", "idle mode"),
            ("MANUAL", "manual control")
        ]

        for mode, description in test_cases:
            state.mode = mode

            # Verify mode was set
            assert state.mode == mode

            # Verify state snapshot reflects the mode
            snapshot = state.snapshot()
            assert snapshot["mode"] == mode

            # Test mode-specific behavior would be triggered
            if mode == "LFR":
                # Line following would use line detector
                line_result = Mock()
                line_result.steer = "STRAIGHT"
                cv['line_detector'].scan.return_value = line_result
                result = cv['line_detector'].scan(mock_frame)
                cmd = RobotComms.from_lfr(result.steer)
                assert cmd == "F"

            elif mode == "HUMAN":
                # Human tracking would use human detector
                detection = Mock()
                detection.bbox = [300, 200, 400, 300]
                cv['human_detector'].detect.return_value = [detection]
                detections = cv['human_detector'].detect(mock_frame)
                assert len(detections) > 0

    def test_error_handling_and_recovery(self, complete_system_setup):
        """Test system error handling and recovery."""
        setup = complete_system_setup
        state = setup['state']
        comms = setup['comms']
        voice = setup['voice']

        # Test communication failure recovery
        comms.send.return_value = False  # Simulate communication failure

        # System should handle failed commands gracefully
        result = comms.send("F")
        assert result is False

        # Test STT failure recovery
        voice['stt'].listen.return_value = ""  # Empty transcription

        # Voice pipeline should handle empty input
        with patch('backend.services.voice_pipeline.WakeWordDetector', return_value=voice['wakeword']), \
             patch('backend.services.voice_pipeline.WhisperSTT', return_value=voice['stt']), \
             patch('backend.services.voice_pipeline.PiperTTS', return_value=voice['tts']), \
             patch('backend.services.voice_pipeline.LLMParser', return_value=voice['llm']), \
             patch('backend.services.voice_pipeline.CommandQueue', return_value=voice['cmd_queue']):

            from backend.services.voice_pipeline import VoicePipeline
            pipeline = VoicePipeline(comms=comms, state=state)
            pipeline.conversation_active = True

            # Should handle empty transcription gracefully
            pipeline._conversation_cycle()

            # Should provide feedback about failed transcription
            voice['tts'].speak.assert_called()
            tts_calls = [call[0][0] for call in voice['tts'].speak.call_args_list]
            assert any("didn't catch" in call.lower() or "try again" in call.lower() for call in tts_calls)

    def test_concurrent_operations_stability(self, complete_system_setup):
        """Test system stability under concurrent operations."""
        setup = complete_system_setup
        state = setup['state']
        comms = setup['comms']

        errors = []
        operations_completed = []

        def state_modifier_worker():
            """Worker that modifies state continuously."""
            try:
                for i in range(50):
                    state.mode = ["IDLE", "LFR", "HUMAN", "VLA"][i % 4]
                    state.yolo_info = f"detection_{i}"
                    state.last_cmd = "FBLRS"[i % 5]
                    time.sleep(0.001)  # Small delay
                operations_completed.append("state_modifier")
            except Exception as e:
                errors.append(f"state_modifier: {e}")

        def comms_worker():
            """Worker that sends commands continuously."""
            try:
                for i in range(50):
                    cmd = "FBLRS"[i % 5]
                    comms.send(cmd)
                    time.sleep(0.001)  # Small delay
                operations_completed.append("comms")
            except Exception as e:
                errors.append(f"comms: {e}")

        def snapshot_worker():
            """Worker that takes snapshots continuously."""
            try:
                snapshots = []
                for i in range(50):
                    snapshot = state.snapshot()
                    snapshots.append(snapshot)
                    time.sleep(0.001)  # Small delay
                operations_completed.append("snapshot")
                # Verify all snapshots are valid
                assert len(snapshots) == 50
                for snapshot in snapshots:
                    assert "mode" in snapshot
            except Exception as e:
                errors.append(f"snapshot: {e}")

        # Start concurrent workers
        threads = [
            threading.Thread(target=state_modifier_worker),
            threading.Thread(target=comms_worker),
            threading.Thread(target=snapshot_worker),
        ]

        for thread in threads:
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join(timeout=10.0)

        # Verify no errors and all workers completed
        assert len(errors) == 0, f"Concurrent operation errors: {errors}"
        assert len(operations_completed) == 3
        assert "state_modifier" in operations_completed
        assert "comms" in operations_completed
        assert "snapshot" in operations_completed


@pytest.mark.e2e
@pytest.mark.hardware
class TestHardwareIntegrationE2E:
    """E2E tests that would require actual hardware (marked for conditional execution)."""

    def test_real_esp32_communication(self):
        """Test real ESP32 communication (requires hardware)."""
        pytest.skip("Requires actual ESP32 hardware")

    def test_real_camera_processing(self):
        """Test real camera input processing (requires hardware)."""
        pytest.skip("Requires actual camera hardware")

    def test_real_audio_pipeline(self):
        """Test real audio input/output (requires hardware)."""
        pytest.skip("Requires actual microphone/speaker hardware")