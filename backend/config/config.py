# config.py for modular robot assistant backend
# Camera device aliases for human-friendly input from CLI

CAMERA_ALIAS_RESOLVE = {
    "laptop": 0,  # OpenCV default device for built-in webcam
    "mobile": "/dev/video2",  # update if your phone via scrcpy outputs differently
    "phone": "/dev/video2",   # alias for convenience
}

DEFAULT_CAMERA_DEVICE = "laptop"

# --- REST API and CORS Configuration ---

#: List of allowed origins for CORS (used in REST API setup).
#: Extend this list to enable more frontend hosts accessing the backend API.
ALLOWED_ORIGINS = [
    "http://localhost",
    "http://localhost:5173",
    # Add production domains as needed
]

#: Default REST API parameters (model selection, etc.).
DEFAULT_API_PARAMS = {
    "model": "gpt-3.5-turbo",   # Example: update to production model as needed
    # Add other API defaults here
}

