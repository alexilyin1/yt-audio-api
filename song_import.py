"""
song_import.py

Turns pasted text or an uploaded .txt/.csv into a list of songs, and finds a
clean YouTube link for each one.

Spaces are never treated as separators, because they are part of song names.
"""

import csv
import io
import re
from concurrent.futures import ThreadPoolExecutor
import similar_songs
import spotify_config
import youtube_match

MAX_SONGS = 50
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
    """Returns search queries, one per song, from free-form text or CSV contents."""
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
    return songs[:MAX_SONGS]


def _looks_related(query: str, track: dict) -> bool:
    """Spotify always returns something; only trust a result sharing a word with what was asked for."""
    words = {w for w in re.findall(r"\w+", query.lower()) if len(w) > 2}
    found = set(re.findall(r"\w+", (track["name"] + " " + track["artists"][0]["name"]).lower()))
    return not words or bool(words & found)


def _resolve(query: str, token: str | None) -> dict:
    """Finds the song on Spotify (when set up) for a clean name and length, then a YouTube link."""
    if token:
        try:
            items = similar_songs._api(token, "search", q=query, type="track", limit=1)["tracks"]["items"]
        except similar_songs.SimilarSongsError:
            items = []
        if items and _looks_related(query, items[0]):
            t = items[0]
            return {
                "query": query,
                "name": similar_songs._label(t),
                "url": youtube_match.find_link(t["name"], t["artists"][0]["name"], t["duration_ms"]),
            }
    return {"query": query, "name": query, "url": youtube_match.find_link(query, "", None)}


def resolve_songs(queries: list[str]) -> list[dict]:
    token = None
    if spotify_config.is_configured():
        try:
            token = similar_songs._get_token()
        except similar_songs.SimilarSongsError:
            pass  # fall back to YouTube-only matching
    with ThreadPoolExecutor(max_workers=5) as pool:
        return list(pool.map(lambda q: _resolve(q, token), queries))
