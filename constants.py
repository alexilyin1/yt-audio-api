"""
constants.py

Central configuration module for YouTube Audio Converter API.
Defines paths, token settings, and HTTP response codes.

Crafted with precision by Alperen Sümeroğlu — powering clean and configurable logic.
"""

import os
import sys
from pathlib import Path

# --- Directory Configurations ---
ROOT_DIRECTORY = Path(__file__).resolve().parent
IS_DESKTOP_APP = getattr(sys, "frozen", False)  # True inside the packaged (PyInstaller) app


def _data_directory() -> Path:
    """Where .env and downloads live. The packaged app's own folder is read-only, so use the user's."""
    if os.environ.get("YT_AUDIO_DATA_DIR"):
        return Path(os.environ["YT_AUDIO_DATA_DIR"])
    if not IS_DESKTOP_APP:
        return ROOT_DIRECTORY
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "YT Audio"
    return Path.home() / ".yt-audio"


DATA_DIRECTORY = _data_directory()
DOWNLOADS_DIRECTORY = 'downloads'
ABS_DOWNLOADS_PATH = str(DATA_DIRECTORY / DOWNLOADS_DIRECTORY)

# --- HTTP Response Codes ---
REQUEST_TIMEOUT = 408       # Used when token is expired
UNAUTHORIZED = 401          # Used when token is invalid
NOT_FOUND = 404             # File not found on server
BAD_REQUEST = 400           # Missing parameters in request
INTERNAL_SERVER_ERROR = 500 # Fallback for unexpected server errors

# --- Token Settings ---
EXPIRY_TIME_MINUTES = 5     # Token expiration duration in minutes
TOKEN_LENGTH = 20           # Length of generated token (in characters)