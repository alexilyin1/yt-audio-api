"""
similar_songs.py

Finds songs "like" a YouTube video using only the Spotify endpoints still open to
new apps (search and artist top tracks). Spotify's real recommendations endpoint
is closed to us, so similarity here is approximate: the artist's other popular
tracks first, then tracks from the same year.
Songs that share playlists with the seed song are ranked first.
"""

import base64
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import yt_dlp
from concurrent.futures import ThreadPoolExecutor
import spotify_config
import youtube_match

MIN_SUPPORT = 2               # a related song must share at least this many playlists with the seed
ARTIST_PLAYLIST_SHARE = 0.4   # a playlist where one artist has this share of tracks is skipped
ERA_YEARS = 8                 # songs this many years from the seed count half as much
_NOT_ORIGINAL = re.compile(
    r"karaoke|tribute|originally performed|made famous|\bcover\b|soundtrack|motion picture|"
    r"\bcast\b|lullaby|8-bit|sped up|slowed|nightcore|from \"|original tv",
    re.IGNORECASE,
)
# playlists named like this are covers, remixes or loops rather than a real mix of songs
_JUNK_PLAYLIST = re.compile(
    r"\bcovers?\b|phonk|lofi|lo-fi|instrumental|karaoke|slowed|sped up|nightcore|8d|reverb|"
    r"\d+\s*(hours?|hrs?|h)\b|\bloop\b|tribute|\bmix\b.*\ball songs|all songs",
    re.IGNORECASE,
)
# playlists that a person made to list songs like the seed
_CURATED_PLAYLIST = re.compile(r"similar|songs? like|sounds? like|if you like|more like|fans of", re.IGNORECASE)
CURATED_WEIGHT = 3
MAX_PER_ARTIST = 2  # keep the list from being dominated by one artist
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
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 3:  # rate limited (big lists): wait as Spotify asks, then retry
                time.sleep(min(int(e.headers.get("Retry-After", 2)), 10) + 1)
                continue
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
    name = name.replace("\u2019", "'").replace("\u2018", "'")  # Spotify mixes curly and straight apostrophes
    return re.split(r"\s+-\s+|\s*[\(\[]", name, maxsplit=1)[0].strip().lower()


def _label(track: dict) -> str:
    return f"{track['name']} — {track['artists'][0]['name']}"


def _year(track: dict) -> int | None:
    date = (track.get("album") or {}).get("release_date") or ""
    return int(date[:4]) if date[:4].isdigit() else None


def _playlist_neighbours(token: str, seed: dict, seed_base: str) -> list:
    """Tracks that keep turning up in the same playlists as the seed song, best first.

    Tightened so that unrelated songs don't slip in: a song needs MIN_SUPPORT playlists,
    one-artist playlists are ignored, and songs from the seed's era rank higher."""
    found = {}
    title = _base_name(seed["name"])
    queries = (f"{seed['name']} {seed['artists'][0]['name']}", seed["name"], f"songs like {title}", f"{title} similar songs")
    for q in queries:
        for p in _api(token, "search", q=q, type="playlist", limit=15)["playlists"]["items"]:
            if p and p["id"] not in found and 5 <= p["tracks"]["total"] <= 200:
                found[p["id"]] = p

    def fetch(playlist_id):
        try:
            return _api(token, f"playlists/{playlist_id}/tracks", limit=100, market="US")["items"]
        except SimilarSongsError:
            return []

    with ThreadPoolExecutor(max_workers=8) as pool:
        playlists = list(pool.map(fetch, found))

    scores, support, by_id = {}, {}, {}
    for playlist, items in zip(found.values(), playlists):
        name = playlist["name"] or ""
        if _JUNK_PLAYLIST.search(name):
            continue
        tracks = [i["track"] for i in items if i.get("track") and i["track"].get("id")]
        curated = bool(_CURATED_PLAYLIST.search(name)) and title.lower() in name.lower()
        # a hand-made "songs like X" list is strong evidence even when X itself isn't in it
        if not curated and not any(_base_name(t["name"]) == seed_base for t in tracks):
            continue  # playlist only matched the title, not the song
        artists = [t["artists"][0]["id"] for t in tracks if t.get("artists")]
        if artists and max(artists.count(a) for a in set(artists)) >= ARTIST_PLAYLIST_SHARE * len(artists):
            continue  # an "all songs by one artist" playlist says nothing about similar songs
        for t in tracks:
            by_id[t["id"]] = t
            support[t["id"]] = support.get(t["id"], 0) + (MIN_SUPPORT if curated else 1)
            scores[t["id"]] = scores.get(t["id"], 0) + len(tracks) ** -0.5 * (CURATED_WEIGHT if curated else 1)

    seed_year = _year(seed)

    def final_score(track_id):
        year = _year(by_id[track_id])
        era = 1 / (1 + abs(year - seed_year) / ERA_YEARS) if year and seed_year else 0.5
        return scores[track_id] * era

    keep = [i for i in scores if support[i] >= MIN_SUPPORT and _is_original(by_id[i], seed)]
    return [by_id[i] for i in sorted(keep, key=lambda i: -final_score(i))]


def _is_original(track: dict, seed: dict) -> bool:
    """False for karaoke, tribute, soundtrack and cover versions, unless the seed is one itself."""
    def flagged(t):
        artists = " ".join(a["name"] for a in t.get("artists", []))
        return bool(_NOT_ORIGINAL.search(f'{t["name"]} | {(t.get("album") or {}).get("name", "")} | {artists}'))
    return not flagged(track) or flagged(seed)


def seed_from_queries(token: str, queries: list) -> dict:
    """The first Spotify track found for any of the search texts, tried in order."""
    for q in queries:
        items = _api(token, "search", q=q, type="track", limit=1)["tracks"]["items"]
        if items:
            return items[0]
    raise SimilarSongsError(f"Couldn't find \"{queries[-1]}\" on Spotify.")


def similar_for_seed(token: str, seed: dict, limit: int = 10) -> dict:
    """Related songs (with YouTube links) for a Spotify track."""
    results = related_tracks(token, seed, limit)
    with ThreadPoolExecutor(max_workers=5) as pool:
        links = list(pool.map(
            lambda t: youtube_match.find_link(t["name"], t["artists"][0]["name"], t["duration_ms"]),
            results,
        ))
    return {
        "song": _label(seed),
        "similar": [{"name": _label(t), "url": link} for t, link in zip(results, links)],
    }


def related_tracks(token: str, seed: dict, limit: int = 10) -> list:
    """Spotify tracks related to the seed track, best first."""
    seed_base = _base_name(seed["name"])
    seed_artist = seed["artists"][0]
    results, seen = [], {seed_base}
    per_artist = {}

    def add(tracks):
        for t in tracks:
            if len(results) >= limit:
                return
            # skip the song itself and other versions of any song already listed
            base = _base_name(t["name"])
            if base in seen or seed_base in base:  # also covers covers/remixes of the seed song
                continue
            artist_id = t["artists"][0]["id"]
            if per_artist.get(artist_id, 0) >= MAX_PER_ARTIST:
                continue
            per_artist[artist_id] = per_artist.get(artist_id, 0) + 1
            seen.add(base)
            results.append(t)

    # 1) Songs that share playlists with the seed song (best signal available)
    add(_playlist_neighbours(token, seed, seed_base))

    # 2) Top up with the artist's own top tracks (capped per artist). Unrelated filler is not added:
    #    a shorter list of real matches is better than ten loose ones.
    if len(results) < limit:
        add(_api(token, "artists/" + seed_artist["id"] + "/top-tracks", market="US")["tracks"])

    return results


def find_similar(video_url: str, limit: int = 10) -> dict:
    query, artist_hint = video_song_query(video_url)
    token = _get_token()
    # Match the video to a Spotify track: try "title + channel", then the title alone
    seed = seed_from_queries(token, [f"{query} {artist_hint}".strip(), query])
    return similar_for_seed(token, seed, limit)
