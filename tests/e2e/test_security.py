import pytest
import requests
import socketio
import time
import os
from dotenv import load_dotenv

load_dotenv()

@pytest.mark.e2e
class TestBackendSecurity:
    """Security tests for the backend API and WebSocket."""

    SECRET_KEY = "test-secret"

    @pytest.fixture(autouse=True)
    def configure_test_secret(self):
        os.environ["JARVIS_SECRET_KEY"] = self.SECRET_KEY

    def test_rest_api_unauthorized_access(self, web_server_instance):
        """Verify that REST API endpoints return 401 without valid token."""
        base_url = f"http://127.0.0.1:{web_server_instance._port}"
        # Test /status
        resp = requests.get(f"{base_url}/status")
        assert resp.status_code == 401
        
        # Test /command
        resp = requests.post(f"{base_url}/command", json={"type": "move", "cmd": "S"})
        assert resp.status_code == 401

    def test_rest_api_authorized_access(self, web_server_instance):
        """Verify that REST API endpoints work with valid token."""
        base_url = f"http://127.0.0.1:{web_server_instance._port}"
        headers = {"Authorization": f"Bearer {self.SECRET_KEY}"}
        
        # Test /status
        resp = requests.get(f"{base_url}/status", headers=headers)
        assert resp.status_code == 200

    def test_rest_api_authorized_command_works(self, web_server_instance):
        """Verify /command accepts authorized move payload."""
        base_url = f"http://127.0.0.1:{web_server_instance._port}"
        headers = {"Authorization": f"Bearer {self.SECRET_KEY}"}
        resp = requests.post(
            f"{base_url}/command",
            headers=headers,
            json={"type": "move", "cmd": "S", "duration": 0.1},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "ok"
        
    def test_socketio_unauthorized_connect(self, web_server_instance):
        """Verify that SocketIO connection is refused without valid token."""
        base_url = f"http://127.0.0.1:{web_server_instance._port}"
        sio = socketio.Client()
        connected = False
        
        try:
            # Try to connect without token
            sio.connect(base_url)
            connected = True
        except Exception:
            pass
        finally:
            if sio.connected:
                sio.disconnect()
        
        assert not connected, "SocketIO should have refused connection without token"

    def test_socketio_authorized_connect(self, web_server_instance):
        """Verify that SocketIO connection works with valid token."""
        base_url = f"http://127.0.0.1:{web_server_instance._port}"
        sio = socketio.Client()
        
        try:
            # Try to connect with token in auth dict
            sio.connect(base_url, auth={"token": self.SECRET_KEY})
            assert sio.connected
        finally:
            if sio.connected:
                sio.disconnect()
                
    def test_cors_restriction(self, web_server_instance):
        """Verify that CORS headers are present and restricted."""
        base_url = f"http://127.0.0.1:{web_server_instance._port}"
        headers = {"Origin": "http://evil-attacker.com"}
        resp = requests.options(
            f"{base_url}/status",
            headers={**headers, "Authorization": f"Bearer {self.SECRET_KEY}"},
        )
        
        # Access-Control-Allow-Origin should not be '*' or 'http://evil-attacker.com'
        allow_origin = resp.headers.get("Access-Control-Allow-Origin")
        assert allow_origin != "*"
        assert allow_origin != "http://evil-attacker.com"
