"""
song_import.py

Turns pasted text or an uploaded .txt/.csv into a list of songs, and finds a
clean YouTube link for each one.

Spaces are never treated as separators, because they are part of song names.
"""

import csv
import io
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
import similar_songs
import spotify_config
import youtube_match

MAX_SONGS = 100  # most songs used from one pasted list or file
_DELIMITERS = ["\t", ";", "|", ","]  # tried in this order
_TITLE_HEADERS = ("track name", "track", "title", "song name", "song", "name")
_ARTIST_HEADERS = ("artist name(s)", "artist names", "artist name", "artists", "artist")
_LIST_MARKER = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+")  # "1. ", "2) ", "- "


def _find_column(header: list[str], wanted: tuple) -> int | None:
    lowered = [h.strip().lower() for h in header]
    for name in wanted:
        if name in lowered:
            return lowered.index(name)
    return None


def _table_delimiter(lines: list[str]) -> str | None:
    """A delimiter that splits (nearly) every line into the same number (2+) of columns."""
    for d in _DELIMITERS:
        counts = [len(row) for row in csv.reader(lines, delimiter=d)]
        common = max(set(counts), key=counts.count)
        if common > 1 and counts.count(common) >= 0.7 * len(counts):
            return d
    return None


def parse_songs(text: str) -> list[str]:
    """Returns search queries, one per song, from free-form text or CSV contents (all of them; the caller applies MAX_SONGS)."""
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    lines = [l for l in text.split("\n") if l.strip()]
    queries: list[str] = []

    if len(lines) > 1:
        delimiter = _table_delimiter(lines)
        if delimiter:  # rows with columns, e.g. a CSV export or "song, artist" lines
            rows = list(csv.reader(lines, delimiter=delimiter))
            title_col = _find_column(rows[0], _TITLE_HEADERS)
            if title_col is not None:  # first row is a header: use the title (+ artist) columns
                artist_col = _find_column(rows[0], _ARTIST_HEADERS)
                for row in rows[1:]:
                    if title_col >= len(row):
                        continue
                    parts = [row[title_col]]
                    if artist_col is not None and artist_col < len(row):
                        parts.append(row[artist_col].split(",")[0])
                    queries.append(" ".join(parts))
            else:
                queries = [" ".join(row) for row in rows]
        else:  # one song per line
            if lines[0].strip().strip('"').lower() in _TITLE_HEADERS:
                lines = lines[1:]  # a one-column file with a header row
            queries = [_LIST_MARKER.sub("", l) for l in lines]
    elif lines:  # a single line: songs separated by tab, ; | or ,
        line = _LIST_MARKER.sub("", lines[0])
        delimiter = next((d for d in _DELIMITERS if d in line), None)
        queries = next(csv.reader([line], delimiter=delimiter)) if delimiter else [line]

    seen, songs = set(), []
    for q in queries:
        q = re.sub(r"\s+", " ", q).strip().strip('"')
        if q and q.lower() not in seen:
            seen.add(q.lower())
            songs.append(q)
    return songs


# Words too common to prove a match
_STOPWORDS = {"the", "and", "feat", "ft", "with", "live", "remix", "official", "video", "audio", "version", "remaster", "remastered"}
OK_CONFIDENCE = 0.75      # most of what the user typed appears in the Spotify match
UNSURE_CONFIDENCE = 0.4   # below this the match is probably a different song
MAX_ENTRY_LENGTH = 100    # longer lines are probably sentences or lyrics, not song names
TIP = "For best results, enter one song per line as \"Artist - Song\" (for example: Daft Punk - One More Time)."


def _words(text: str) -> set:
    """Lower-case words of a text, accents removed, without filler words."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return {w for w in re.findall(r"\w+", text) if len(w) > 1 and w not in _STOPWORDS}


def match_confidence(query: str, track: dict) -> float:
    """0..1: how much of what the user typed shows up in a Spotify track's title and artists."""
    wanted = _words(query)
    if not wanted:
        return 0.5
    found = _words(track["name"] + " " + " ".join(a["name"] for a in track["artists"]))
    return len(wanted & found) / len(wanted)


def best_match(token: str, query: str) -> tuple:
    """Returns (track or None, status, hint). Status is "ok", "unsure" (a guess) or "notfound"."""
    try:
        items = similar_songs._api(token, "search", q=query, type="track", limit=5)["tracks"]["items"]
    except similar_songs.SimilarSongsError:
        items = []
    scored = [(match_confidence(query, t), t) for t in items]
    if not scored:
        return None, "notfound", "Couldn't find this song. Check the spelling or add the artist."
    confidence, track = max(scored, key=lambda p: p[0])  # Spotify's own order breaks ties
    if confidence < UNSURE_CONFIDENCE:
        return None, "notfound", "Couldn't find a close match. Check the spelling or add the artist."
    if confidence < OK_CONFIDENCE or len(_words(query)) < 2:
        # a single word ("Levels") fits many songs even when it matches perfectly
        return track, "unsure", f"Not sure this is the right song; we guessed \"{similar_songs._label(track)}\". Adding the artist helps, e.g. \"Artist - Song\"."
    return track, "ok", ""


def check_entries(queries: list) -> tuple:
    """Splits entries into usable ones and (entry, reason) pairs that are clearly not song names."""
    usable, skipped = [], []
    for q in queries:
        if re.match(r"(?i)^(https?://|www\.)", q) or " http" in q.lower():
            skipped.append((q, "This is a web link, not a song name. Paste YouTube links in the box at the top of the page instead."))
        elif len(q) > MAX_ENTRY_LENGTH:
            skipped.append((q[:60] + "…", "This line is very long, like a sentence or lyrics. Put one song name on each line."))
        elif not re.search(r"[^\W\d_]", q):
            skipped.append((q, "This has no letters, so it can't be a song name."))
        else:
            usable.append(q)
    return usable, skipped


def _resolve(query: str, token: str | None) -> dict:
    """Finds the song on Spotify (when set up) for a clean name and length, then a YouTube link."""
    if token:
        track, status, hint = best_match(token, query)
        if track:
            return {
                "query": query,
                "name": similar_songs._label(track),
                "url": youtube_match.find_link(track["name"], track["artists"][0]["name"], track["duration_ms"]),
                "status": status,
                "hint": hint,
            }
        return {"query": query, "name": query, "url": None, "status": status, "hint": hint}
    # without Spotify there is nothing to check the match against
    return {"query": query, "name": query, "url": youtube_match.find_link(query, "", None), "status": "ok", "hint": ""}


def resolve_songs(queries: list[str]) -> list[dict]:
    token = None
    if spotify_config.is_configured():
        try:
            token = similar_songs._get_token()
        except similar_songs.SimilarSongsError:
            pass  # fall back to YouTube-only matching
    with ThreadPoolExecutor(max_workers=5) as pool:
        return list(pool.map(lambda q: _resolve(q, token), queries))
