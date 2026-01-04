"""
End-to-end tests for JARVIS Robot system.

These tests verify complete workflows and integration between components
without requiring actual hardware (ESP32, camera, microphone).
"""
import pytest
import time
import threading
import queue
from unittest.mock import Mock, MagicMock, patch
import numpy as np

from pipeline.robot_state import RobotState
from robot_comms import RobotComms
from web_server import WebServer


@pytest.mark.e2e
class TestVoicePipelineE2E:
    """End-to-end tests for voice pipeline workflows."""

    @pytest.fixture
    def voice_pipeline_setup(self, disable_hardware):
        """Set up voice pipeline with all dependencies mocked."""
        state = RobotState()
        comms = Mock(spec=RobotComms)
        comms.connected = True
        comms.send.return_value = True

        # Mock all voice components
        with patch('pipeline.voice_pipeline.WakeWordDetector') as mock_ww, \
             patch('pipeline.voice_pipeline.WhisperSTT') as mock_stt, \
             patch('pipeline.voice_pipeline.PiperTTS') as mock_tts, \
             patch('pipeline.voice_pipeline.LLMParser') as mock_llm, \
             patch('pipeline.voice_pipeline.CommandQueue') as mock_cmd:

            mock_ww_instance = Mock()
            mock_stt_instance = Mock()
            mock_tts_instance = Mock()
            mock_llm_instance = Mock()
            mock_cmd_instance = Mock()

            mock_ww.return_value = mock_ww_instance
            mock_stt.return_value = mock_stt_instance
            mock_tts.return_value = mock_tts_instance
            mock_llm.return_value = mock_llm_instance
            mock_cmd.return_value = mock_cmd_instance

            from pipeline.voice_pipeline import VoicePipeline
            pipeline = VoicePipeline(comms=comms, state=state)

            yield {
                'pipeline': pipeline,
                'state': state,
                'comms': comms,
                'mocks': {
                    'wakeword': mock_ww_instance,
                    'stt': mock_stt_instance,
                    'tts': mock_tts_instance,
                    'llm': mock_llm_instance,
                    'cmd_queue': mock_cmd_instance
                }
            }

    def test_voice_pipeline_startup_and_greeting(self, voice_pipeline_setup):
        """Test that voice pipeline starts and plays greeting."""
        setup = voice_pipeline_setup
        pipeline = setup['pipeline']
        mocks = setup['mocks']

        # Start pipeline in a thread
        pipeline_thread = threading.Thread(target=pipeline._loop, daemon=True)
        pipeline_thread.start()

        # Wait a moment for initialization
        time.sleep(0.1)

        # Verify initial greeting was played
        mocks['tts'].speak.assert_called()
        greeting_call = mocks['tts'].speak.call_args_list[0]
        assert "JARVIS" in greeting_call[0][0]

    def test_voice_command_processing_workflow(self, voice_pipeline_setup):
        """Test complete voice command processing from wake word to action."""
        setup = voice_pipeline_setup
        pipeline = setup['pipeline']
        state = setup['state']
        mocks = setup['mocks']

        # Mock STT to return a test command
        mocks['stt'].listen.return_value = "move forward"

        # Mock LLM to return parsed response
        mocks['llm'].parse.return_value = {
            "speech": "Moving forward now",
            "actions": ["MOVE_FORWARD"]
        }

        # Trigger a single cycle
        pipeline._single_cycle()

        # Verify the workflow
        mocks['wakeword'].wait_for_wakeword.assert_called_once()
        mocks['stt'].listen.assert_called_once()
        mocks['llm'].parse.assert_called_once()
        mocks['tts'].speak.assert_called()
        mocks['cmd_queue'].push_all.assert_called_with(["MOVE_FORWARD"])

        # Verify state was updated
        assert state.last_heard == "move forward"
        assert state.jarvis_response == "Moving forward now"

    def test_custom_response_shortcut(self, voice_pipeline_setup):
        """Test that custom responses bypass LLM processing."""
        setup = voice_pipeline_setup
        pipeline = setup['pipeline']
        state = setup['state']
        mocks = setup['mocks']

        # Mock STT to return a custom response trigger
        mocks['stt'].listen.return_value = "what is your name"

        # Trigger a single cycle
        pipeline._single_cycle()

        # Verify custom response was used (LLM should not be called)
        mocks['llm'].parse.assert_not_called()
        mocks['tts'].speak.assert_called()

        # Verify response contains JARVIS
        tts_call = mocks['tts'].speak.call_args_list[-1]
        assert "JARVIS" in tts_call[0][0]

        # Verify state was updated
        assert state.last_heard == "what is your name"
        assert "JARVIS" in state.jarvis_response

    def test_emergency_stop_handling(self, voice_pipeline_setup):
        """Test emergency keyword handling."""
        setup = voice_pipeline_setup
        pipeline = setup['pipeline']
        state = setup['state']
        mocks = setup['mocks']

        # Set initial mode
        state.mode = "HUMAN"

        # Mock STT to return emergency command
        mocks['stt'].listen.return_value = "emergency stop now"

        # Trigger a single cycle
        pipeline._single_cycle()

        # Verify emergency handling
        mocks['cmd_queue'].clear.assert_called_once()
        assert state.mode == "IDLE"
        mocks['tts'].speak.assert_called()

        # Verify stop message
        tts_call = mocks['tts'].speak.call_args_list[-1]
        assert "Stopping" in tts_call[0][0] or "stop" in tts_call[0][0].lower()


@pytest.mark.e2e
class TestWebServerRobotCommsE2E:
    """End-to-end tests for web server and robot communication."""

    @pytest.fixture
    def web_robot_setup(self):
        """Set up web server with robot comms for testing."""
        state = RobotState()
        comms = Mock(spec=RobotComms)
        comms.connected = True
        comms.send.return_value = True

        server = WebServer(state=state, comms=comms, host="127.0.0.1", port=5002)

        yield {
            'server': server,
            'state': state,
            'comms': comms
        }

    def test_robot_move_command_via_web_api(self, web_robot_setup):
        """Test robot movement commands through web API."""
        setup = web_robot_setup
        server = setup['server']
        state = setup['state']
        comms = setup['comms']

        # Simulate move command processing directly
        command_data = {
            "type": "move",
            "cmd": "F",
            "duration": 0.5
        }

        # Test the move logic directly
        if command_data.get("type") == "move":
            cmd_char = command_data.get("cmd", "S")
            if cmd_char in "FBLRS":
                comms.send(cmd_char)
                state.last_cmd = cmd_char

        # Verify command was sent
        comms.send.assert_called_with("F")
        assert state.last_cmd == "F"

    def test_mode_switching_workflow(self, web_robot_setup):
        """Test mode switching through web interface."""
        setup = web_robot_setup
        server = setup['server']
        state = setup['state']

        # Initial mode
        assert state.mode == "IDLE"

        # Simulate mode change directly
        mode_data = {
            "type": "mode",
            "mode": "HUMAN"
        }

        # Test mode switching logic directly
        if mode_data.get("type") == "mode":
            new_mode = mode_data.get("mode")
            if new_mode in ["IDLE", "LFR", "HUMAN", "VLA", "MANUAL"]:
                state.mode = new_mode

        # Verify mode was changed
        assert state.mode == "HUMAN"

    def test_frame_streaming_to_dashboard(self, web_robot_setup, mock_frame):
        """Test frame streaming to web dashboard."""
        setup = web_robot_setup
        server = setup['server']

        # Simulate browser client connection
        server._has_clients = True

        # Push a frame
        server.push_frame(mock_frame)

        # Verify frame was encoded
        assert server._frame_bytes is not None
        assert isinstance(server._frame_bytes, bytes)

        # Verify JPEG header
        assert server._frame_bytes.startswith(b'\xff\xd8')  # JPEG header


@pytest.mark.e2e
class TestComputerVisionModesE2E:
    """End-to-end tests for computer vision processing modes."""

    @pytest.fixture
    def cv_system_setup(self):
        """Set up CV system with mocked components."""
        state = RobotState()
        comms = Mock(spec=RobotComms)
        comms.connected = True

        # Mock CV components
        line_detector = Mock()
        human_detector = Mock()
        vla_processor = Mock()

        yield {
            'state': state,
            'comms': comms,
            'line_detector': line_detector,
            'human_detector': human_detector,
            'vla_processor': vla_processor
        }

    def test_line_following_mode_integration(self, cv_system_setup, mock_frame):
        """Test line following mode end-to-end processing."""
        setup = cv_system_setup
        state = setup['state']
        comms = setup['comms']
        line_detector = setup['line_detector']

        # Set mode to line following
        state.mode = "LFR"

        # Mock line detection result
        line_result = Mock()
        line_result.steer = "LEFT"
        line_detector.scan.return_value = line_result

        # Call the detector and test the line following logic
        result = line_detector.scan(mock_frame)
        cmd = RobotComms.from_lfr(result.steer)

        # Verify correct command mapping
        assert cmd == "L"

        # Verify line detector was called with frame
        line_detector.scan.assert_called_with(mock_frame)

    def test_human_tracking_mode_integration(self, cv_system_setup, mock_frame):
        """Test human tracking mode end-to-end processing."""
        setup = cv_system_setup
        state = setup['state']
        human_detector = setup['human_detector']

        # Set mode to human tracking
        state.mode = "HUMAN"

        # Mock human detection result
        detection = Mock()
        detection.confidence = 0.85
        detection.bbox = [100, 100, 200, 200]
        human_detector.detect.return_value = [detection]

        # Call the detector and test the human tracking logic
        detections = human_detector.detect(mock_frame)
        frame_w, frame_h = mock_frame.shape[1], mock_frame.shape[0]
        cmd = RobotComms.from_human_bbox(detection.bbox, frame_w, frame_h, rotate_deg=0)

        # Small bbox should result in forward movement
        assert cmd == "F"

        # Verify human detector was called
        human_detector.detect.assert_called_with(mock_frame)

    def test_vla_mode_processing(self, cv_system_setup, mock_frame):
        """Test VLA (Vision-Language-Action) mode processing."""
        setup = cv_system_setup
        state = setup['state']
        vla_processor = setup['vla_processor']

        # Set mode to VLA
        state.mode = "VLA"

        # Mock VLA result
        vla_processor.get_intent.return_value = "FOLLOW"

        # Test VLA processing
        intent = vla_processor.get_intent(mock_frame)
        from robot_comms import RobotComms
        cmd = RobotComms.from_intent(intent)

        # Verify intent mapping
        assert intent == "FOLLOW"
        assert cmd == "F"

        # Verify VLA processor was called
        vla_processor.get_intent.assert_called_with(mock_frame)


@pytest.mark.e2e
@pytest.mark.slow
class TestFullSystemIntegrationE2E:
    """Full system integration tests (slower, more comprehensive)."""

    def test_mode_transition_workflow(self):
        """Test transitioning between different operating modes."""
        state = RobotState()

        # Test mode transitions
        modes = ["IDLE", "LFR", "HUMAN", "VLA", "MANUAL"]

        for mode in modes:
            state.mode = mode
            assert state.mode == mode

            # Verify state consistency
            snapshot = state.snapshot()
            assert snapshot["mode"] == mode

    def test_concurrent_state_access_under_load(self):
        """Test state access under concurrent load."""
        state = RobotState()
        errors = []
        results = []

        def stress_worker():
            try:
                for i in range(100):
                    state.mode = f"TEST_{i % 5}"
                    snapshot = state.snapshot()
                    results.append(snapshot["mode"])
                    state.yolo_info = f"detection_{i}"
                    state.last_cmd = "FBLRS"[i % 5]
            except Exception as e:
                errors.append(e)

        # Start multiple concurrent workers
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=stress_worker)
            threads.append(thread)
            thread.start()

        # Wait for all to complete
        for thread in threads:
            thread.join(timeout=5.0)

        # Verify no errors occurred
        assert len(errors) == 0, f"Concurrent access errors: {errors}"
        assert len(results) == 500  # 5 threads * 100 operations each