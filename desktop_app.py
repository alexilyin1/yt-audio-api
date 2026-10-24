"""
desktop_app.py

Entry point of the packaged desktop app: starts the server on this computer
and opens the page in the user's browser. No terminal or Python needed.
"""

import os
import socket
import threading
import time
import webbrowser
import certifi

# Packaged Python has no system certificates; without these, Spotify/YouTube calls fail on macOS
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from constants import DATA_DIRECTORY, ABS_DOWNLOADS_PATH  # noqa: E402  (after the cert setting)
from main import app, start_token_cleaner  # noqa: E402

PREFERRED_PORT = 5000


def _free_port() -> int:
    """5000 if available (another program may be using it), otherwise any free port."""
    for port in (PREFERRED_PORT, 0):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("No free network port available.")


def main():
    os.makedirs(ABS_DOWNLOADS_PATH, exist_ok=True)
    start_token_cleaner()
    port = _free_port()
    url = f"http://127.0.0.1:{port}/"
    threading.Thread(target=lambda: (time.sleep(1.0), webbrowser.open(url)), daemon=True).start()
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
