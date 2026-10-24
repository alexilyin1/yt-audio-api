"""
spotify_config.py

Reads and writes the Spotify API credentials stored in the local .env file,
and checks that a client ID/secret pair is accepted by Spotify.
"""

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from constants import DATA_DIRECTORY

ENV_PATH = Path(DATA_DIRECTORY) / ".env"
ID_KEY = "SPOTIFY_CLIENT_ID"
SECRET_KEY = "SPOTIFY_CLIENT_SECRET"
TOKEN_URL = "https://accounts.spotify.com/api/token"


def read_env() -> dict:
    """Parses KEY=VALUE lines of the .env file (ignores blanks and # comments)."""
    values = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def is_configured() -> bool:
    env = read_env()
    return bool(env.get(ID_KEY) and env.get(SECRET_KEY))


def save_credentials(client_id: str, client_secret: str) -> None:
    """Sets the two Spotify keys in .env, keeping every other line as it was."""
    updates = {ID_KEY: client_id, SECRET_KEY: client_secret}
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    out = []
    for line in lines:
        key = line.partition("=")[0].strip()
        if key in updates:
            out.append(f"{key}={updates.pop(key)}")
        else:
            out.append(line)
    out.extend(f"{k}={v}" for k, v in updates.items())
    ENV_PATH.write_text("\n".join(out) + "\n")
    ENV_PATH.chmod(0o600)  # the secret should only be readable by this user


def check_credentials(client_id: str, client_secret: str) -> str | None:
    """Asks Spotify for a token. Returns None if the keys work, else a plain-English problem."""
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
        headers={"Authorization": f"Basic {auth}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            json.load(resp)
        return None
    except urllib.error.HTTPError as e:
        if e.code in (400, 401):
            return "Spotify didn't accept these keys. Check that you copied the Client ID and Client secret exactly, with no extra spaces."
        return f"Spotify returned an unexpected error ({e.code}). Please try again."
    except (urllib.error.URLError, TimeoutError):
        return "Couldn't reach Spotify. Check your internet connection and try again."
