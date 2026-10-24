"""
similar_songs.py

Finds songs "like" a YouTube video using only the Spotify endpoints still open to
new apps (search and artist top tracks). Spotify's real recommendations endpoint
is closed to us, so similarity here is approximate: the artist's other popular
tracks first, then tracks from the same year.
"""

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import yt_dlp
import spotify_config

API = "https://api.spotify.com/v1/"
# Tags YouTube uploaders add to titles, which would confuse the Spotify search
_NOISE = re.compile(
    r"[\(\[][^\)\]]*(official|video|audio|lyric|remaster|4k|hd|hq|visualizer|live)[^\)\]]*[\)\]]",
    re.IGNORECASE,
)


class SimilarSongsError(Exception):
    """An error whose message is safe to show to the user."""


def _get_token() -> str:
    env = spotify_config.read_env()
    cid, secret = env.get(spotify_config.ID_KEY), env.get(spotify_config.SECRET_KEY)
    if not (cid and secret):
        raise SimilarSongsError("Spotify isn't set up yet.")
    auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    req = urllib.request.Request(
        spotify_config.TOKEN_URL,
        data=b"grant_type=client_credentials",
        headers={"Authorization": f"Basic {auth}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp)["access_token"]
    except urllib.error.URLError:
        raise SimilarSongsError("Couldn't log in to Spotify. Check your keys and internet connection.")


def _api(token: str, path: str, **params) -> dict:
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raise SimilarSongsError(f"Spotify returned an error ({e.code}). Please try again.")
    except urllib.error.URLError:
        raise SimilarSongsError("Couldn't reach Spotify. Check your internet connection.")


def video_song_query(video_url: str) -> tuple[str, str]:
    """Returns (search text, artist hint) for a YouTube video."""
    opts = {"quiet": True, "noplaylist": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
    except Exception:
        raise SimilarSongsError("Couldn't read that YouTube link.")
    # YouTube Music uploads carry clean track/artist fields; otherwise clean up the title
    if info.get("track") and info.get("artist"):
        return info["track"], info["artist"].split(",")[0]
    title = _NOISE.sub("", info.get("title", "")).strip()
    return title, (info.get("channel") or info.get("uploader") or "").replace(" Official", "").replace("VEVO", "")


def _base_name(name: str) -> str:
    """'Song - 2022 Remaster' / 'Song (Live)' -> 'song', so versions of one song count as the same."""
    return re.split(r"\s+-\s+|\s*[\(\[]", name, maxsplit=1)[0].strip().lower()


def _label(track: dict) -> str:
    return f"{track['name']} — {track['artists'][0]['name']}"


def find_similar(video_url: str, limit: int = 10) -> dict:
    query, artist_hint = video_song_query(video_url)
    token = _get_token()

    # Match the video to a Spotify track: try "title + channel", then the title alone
    seed = None
    for q in (f"{query} {artist_hint}".strip(), query):
        items = _api(token, "search", q=q, type="track", limit=1)["tracks"]["items"]
        if items:
            seed = items[0]
            break
    if not seed:
        raise SimilarSongsError(f"Couldn't find \"{query}\" on Spotify.")

    results, seen = [], {_base_name(seed["name"])}

    def add(tracks):
        for t in tracks:
            # skip the song itself and other versions of any song already listed
            base = _base_name(t["name"])
            if base in seen:
                continue
            seen.add(base)
            results.append(t)

    artist_id = seed["artists"][0]["id"]
    add(_api(token, "artists/" + artist_id + "/top-tracks", market="US")["tracks"])

    if len(results) < limit:  # fill up with other artists' tracks from the same year
        year = seed["album"]["release_date"][:4]
        others = _api(token, "search", q=f"year:{year}", type="track", limit=50)["tracks"]["items"]
        add(t for t in sorted(others, key=lambda t: -t["popularity"]) if t["artists"][0]["id"] != artist_id)

    return {"song": _label(seed), "similar": [_label(t) for t in results[:limit]]}
