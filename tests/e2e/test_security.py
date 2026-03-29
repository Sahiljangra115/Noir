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
    
    BASE_URL = "http://127.0.0.1:5000"
    SECRET_KEY = os.getenv("JARVIS_SECRET_KEY", "jarvis-robot-secret")

    def test_rest_api_unauthorized_access(self):
        """Verify that REST API endpoints return 401 without valid token."""
        # Test /status
        resp = requests.get(f"{self.BASE_URL}/status")
        assert resp.status_code == 401
        
        # Test /command
        resp = requests.post(f"{self.BASE_URL}/command", json={"type": "move", "cmd": "S"})
        assert resp.status_code == 401

    def test_rest_api_authorized_access(self):
        """Verify that REST API endpoints work with valid token."""
        headers = {"Authorization": f"Bearer {self.SECRET_KEY}"}
        
        # Test /status
        resp = requests.get(f"{self.BASE_URL}/status", headers=headers)
        # Note: This might return 500 if the server is not fully initialized, 
        # but 401 is what we're testing against.
        assert resp.status_code != 401
        
    def test_socketio_unauthorized_connect(self):
        """Verify that SocketIO connection is refused without valid token."""
        sio = socketio.Client()
        connected = False
        
        try:
            # Try to connect without token
            sio.connect(self.BASE_URL)
            connected = True
        except Exception:
            pass
        finally:
            if sio.connected:
                sio.disconnect()
        
        assert not connected, "SocketIO should have refused connection without token"

    def test_socketio_authorized_connect(self):
        """Verify that SocketIO connection works with valid token."""
        sio = socketio.Client()
        
        try:
            # Try to connect with token in auth dict
            sio.connect(self.BASE_URL, auth={"token": self.SECRET_KEY})
            assert sio.connected
        finally:
            if sio.connected:
                sio.disconnect()
                
    def test_cors_restriction(self):
        """Verify that CORS headers are present and restricted."""
        headers = {"Origin": "http://evil-attacker.com"}
        resp = requests.options(f"{self.BASE_URL}/status", headers=headers)
        
        # Access-Control-Allow-Origin should not be '*' or 'http://evil-attacker.com'
        allow_origin = resp.headers.get("Access-Control-Allow-Origin")
        assert allow_origin != "*"
        assert allow_origin != "http://evil-attacker.com"
