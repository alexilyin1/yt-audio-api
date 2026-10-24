"""
youtube_match.py

Finds the best YouTube link for a song. Music videos often have long intros,
skits or talking, so we prefer audio-only uploads and require the video length
to be close to the song's length on Spotify.
"""

import math
import re
import yt_dlp

MAX_UNKNOWN_LENGTH = 600  # seconds; cap when the song isn't known to Spotify
MAX_LENGTH_DIFF = 20  # seconds a video may differ from the Spotify track length
# Words in a title that signal non-music parts, other versions, or someone else's recording
_BAD = re.compile(
    r"music video|official video|\bmv\b|live|concert|cover|remix|reaction|karaoke|"
    r"instrumental|slowed|sped up|nightcore|8d|tutorial|lesson|behind the scenes|"
    r"interview|trailer|full album|compilation|mashup|extended|intro|"
    r"symphonic|acoustic|unplugged|orchestra\w*|piano|demo|session|stripped|re-?recorded",
    re.IGNORECASE,
)
_GOOD = re.compile(r"official audio|\baudio\b|lyric|visuali[sz]er", re.IGNORECASE)


def _source_quality(entry: dict, artist: str) -> float:
    """Bonus for uploads from the real source. YouTube re-encodes every upload to nearly the same
    bitrate (about 130 kbps Opus), so who uploaded it matters far more than the format."""
    channel = (entry.get("channel") or entry.get("uploader") or "").lower()
    artist_words = [w for w in re.findall(r"\w+", artist.lower()) if len(w) > 2]
    bonus = 0.0
    if entry.get("channel_is_verified"):
        bonus += 6
    # the artist's own channel, a label's VEVO, or YouTube's auto-generated "Topic" channel
    if channel.endswith("- topic") or "vevo" in channel or (artist_words and all(w in channel for w in artist_words)):
        bonus += 8
    return bonus + math.log10(max(entry.get("view_count") or 1, 1)) * 0.75  # popular uploads are rarely rips


def _score(entry: dict, song: str, artist: str, seconds: float | None) -> float | None:
    """Higher is better; None means reject. seconds is None when the song's length is unknown."""
    duration = entry.get("duration")
    title = entry.get("title") or ""
    channel = entry.get("channel") or entry.get("uploader") or ""
    if not duration:
        return None
    if seconds is None:
        if duration > MAX_UNKNOWN_LENGTH:  # no reference length: just skip very long videos
            return None
        seconds = duration
    else:
        if abs(duration - seconds) > MAX_LENGTH_DIFF:
            return None
        # The song's title from Spotify must show up, or it's a different song
        if song.lower().split(" - ")[0].split(" (")[0] not in title.lower():
            return None
    # A wanted word in the song's own name (e.g. a "Live" song) is not a reason to penalize
    bad_words = {m.lower() for m in _BAD.findall(title)} - {m.lower() for m in _BAD.findall(song)}
    score = -abs(duration - seconds) / 5  # closer length is better
    score -= 10 * len(bad_words)
    if _GOOD.search(title):
        score += 4
    return score + _source_quality(entry, artist)


def find_link(song: str, artist: str, duration_ms: int | None) -> str | None:
    """Returns the best YouTube URL for the song, or None if nothing looks right."""
    opts = {"quiet": True, "extract_flat": True, "skip_download": True}
    seconds = duration_ms / 1000 if duration_ms else None
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            found = ydl.extract_info(f"ytsearch12:{artist} {song} audio".replace("  ", " "), download=False)["entries"]
    except Exception:
        return None
    scored = [(s, e) for e in found if (s := _score(e, song, artist, seconds)) is not None]
    if not scored:
        return None
    return max(scored, key=lambda p: p[0])[1].get("url")
