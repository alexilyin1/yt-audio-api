"""
main.py
Developed by Alperen Sümeroğlu - YouTube Audio Converter API
Clean, modular Flask-based backend for downloading and serving YouTube audio tracks.
Utilizes yt-dlp and FFmpeg for conversion and token-based access management.
"""

import os
import re
import secrets
import shutil
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from flask import Flask, request, jsonify, send_from_directory, render_template
from uuid import uuid4
from pathlib import Path
import yt_dlp
import imageio_ffmpeg
import access_manager
import spotify_config
import similar_songs
import song_import
from constants import *

# Initialize the Flask application
app = Flask(__name__)


# Background conversion jobs for the GUI's progress bar: job_id -> status dict
jobs = {}


def _convert(video_url: str, filename: str, progress_hook=None) -> None:
    """Download the audio of video_url and convert it to ABS_DOWNLOADS_PATH/filename (mp3)."""
    output_path = Path(ABS_DOWNLOADS_PATH) / filename

    # yt-dlp configuration for downloading best audio and converting to mp3
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': str(output_path.with_suffix('')),  # yt-dlp adds .mp3 itself
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192'
        }],
        'ffmpeg_location': imageio_ffmpeg.get_ffmpeg_exe(),  # bundled, no system install needed
        'noplaylist': True,  # a link with &list=... should convert only that video
        'quiet': True,
        'noprogress': True,
        'progress_hooks': [progress_hook] if progress_hook else [],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])


def _run_job(job_id: str, video_url: str) -> None:
    """Thread target: runs a conversion and records its progress in jobs[job_id]."""
    job = jobs[job_id]
    filename = f"{uuid4()}.mp3"

    def hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                job["percent"] = round(d["downloaded_bytes"] / total * 100)
        elif d["status"] == "finished":
            job.update(state="converting", percent=100)

    try:
        _convert(video_url, filename, hook)
        token = secrets.token_urlsafe(TOKEN_LENGTH)
        access_manager.add_token(token, filename)
        job.update(state="done", token=token)
    except Exception as e:
        job.update(state="error", error=str(e))


MAX_ZIP_SONGS = 1000  # 100 imported songs x 10 similar songs each
ZIP_PARALLEL = 3  # songs converted at the same time
BULK_SIMILAR_PARALLEL = 3  # imported songs looked up at the same time
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}


def _is_youtube_url(url) -> bool:
    return isinstance(url, str) and urlparse(url).hostname in _YOUTUBE_HOSTS


def _safe_filename(name: str) -> str:
    """A song name usable as a file name on Mac and Windows."""
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", name).strip(" .")[:120] or "song"


def _run_zip_job(job_id: str, songs: list) -> None:
    """Thread target: converts every song straight into one zip, so only the zip uses disk space."""
    job = jobs[job_id]
    zip_name = f"YT-Audio-songs-{uuid4().hex[:8]}.zip"
    zip_path = Path(ABS_DOWNLOADS_PATH) / zip_name
    lock = threading.Lock()  # zipfile isn't safe for several threads writing at once
    used = set()
    added = 0

    def add_to_zip(zf, filename: str, name: str) -> None:
        nonlocal added
        base, n = _safe_filename(name), 1
        with lock:
            arcname = base + ".mp3"
            while arcname.lower() in used:  # two songs with the same name
                n += 1
                arcname = f"{base} ({n}).mp3"
            used.add(arcname.lower())
            zf.write(Path(ABS_DOWNLOADS_PATH) / filename, arcname)
            added += 1

    def convert_one(song, zf):
        filename = f"{uuid4()}.mp3"
        try:
            _convert(song["url"], filename)
            add_to_zip(zf, filename, str(song.get("name") or "song"))
        except Exception:
            job["failed"].append(str(song.get("name") or song["url"]))
        finally:
            (Path(ABS_DOWNLOADS_PATH) / filename).unlink(missing_ok=True)
        job["done"] += 1

    try:
        os.makedirs(ABS_DOWNLOADS_PATH, exist_ok=True)
        # ZIP_STORED: MP3s are already compressed
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
            with ThreadPoolExecutor(max_workers=ZIP_PARALLEL) as pool:
                list(pool.map(lambda s: convert_one(s, zf), songs))
        if not added:
            raise RuntimeError("None of the songs could be downloaded.")
        token = secrets.token_urlsafe(TOKEN_LENGTH)
        access_manager.add_token(token, zip_name)
        job.update(state="done", token=token)
    except Exception as e:
        zip_path.unlink(missing_ok=True)
        job.update(state="error", error=str(e))


@app.route("/bulk-similar", methods=["GET"])
def bulk_similar_page():
    """Page listing similar songs for every song of an imported list."""
    return render_template("bulk_similar.html")


def _run_bulk_similar(job_id: str, queries: list) -> None:
    """Thread target: finds similar songs for each query, recording each result as it finishes."""
    job = jobs[job_id]
    try:
        token = similar_songs._get_token()
    except similar_songs.SimilarSongsError as e:
        job.update(state="error", error=str(e))
        return

    def one(index_query):
        index, query = index_query
        try:
            seed = similar_songs.seed_from_queries(token, [query])
            if not song_import._looks_related(query, seed):  # Spotify returns something even for nonsense
                raise similar_songs.SimilarSongsError(f"Couldn't find \"{query}\" on Spotify.")
            result = similar_songs.similar_for_seed(token, seed)
            entry = {"index": index, "query": query, **result}
        except similar_songs.SimilarSongsError as e:
            entry = {"index": index, "query": query, "error": str(e)}
        except Exception:
            entry = {"index": index, "query": query, "error": "Something went wrong with this song."}
        job["finished"].append(entry)
        job["done"] += 1

    with ThreadPoolExecutor(max_workers=BULK_SIMILAR_PARALLEL) as pool:
        list(pool.map(one, enumerate(queries)))
    job["state"] = "done"


@app.route("/bulk/start", methods=["POST"])
def bulk_start():
    """Body {"queries": ["song", ...]} (max 100). Poll /bulk/progress for results as they finish."""
    data = request.get_json(silent=True) or {}
    queries = [q.strip() for q in data.get("queries", []) if isinstance(q, str) and q.strip()]
    queries = queries[:song_import.MAX_SONGS]
    if not queries:
        return jsonify(error="No songs to look up."), BAD_REQUEST
    if not spotify_config.is_configured():
        return jsonify(error="Spotify isn't set up yet."), BAD_REQUEST
    job_id = secrets.token_urlsafe(8)
    jobs[job_id] = {"state": "working", "done": 0, "total": len(queries), "finished": []}
    threading.Thread(target=_run_bulk_similar, args=(job_id, queries), daemon=True).start()
    return jsonify(job=job_id, total=len(queries))


@app.route("/bulk/progress", methods=["GET"])
def bulk_progress():
    """Returns the results finished since the client last asked (`have` = how many it already has)."""
    job = jobs.get(request.args.get("job", ""))
    if job is None:
        return jsonify(error="Unknown job."), NOT_FOUND
    have = request.args.get("have", 0, type=int)
    finished = job["finished"]
    return jsonify(state=job["state"], error=job.get("error"), done=job["done"],
                   total=job["total"], results=finished[have:])


@app.route("/zip/start", methods=["POST"])
def start_zip():
    """Body {"songs": [{"name", "url"}, ...]}. Converts them all into one zip; poll /progress."""
    data = request.get_json(silent=True) or {}
    songs = [s for s in data.get("songs", []) if isinstance(s, dict) and _is_youtube_url(s.get("url"))]
    if not songs:
        return jsonify(error="No songs with a YouTube link to download."), BAD_REQUEST
    songs = list({s["url"]: s for s in reversed(songs)}.values())[::-1]  # one copy per link
    songs = songs[:MAX_ZIP_SONGS]
    job_id = secrets.token_urlsafe(8)
    jobs[job_id] = {"state": "working", "done": 0, "total": len(songs), "failed": []}
    threading.Thread(target=_run_zip_job, args=(job_id, songs), daemon=True).start()
    return jsonify(job=job_id)


@app.route("/start", methods=["GET"])
def start_job():
    """Start a conversion in the background. Returns {"job": <id>}; poll /progress."""
    video_url = request.args.get("url")
    if not video_url:
        return jsonify(error="Missing 'url' parameter in request."), BAD_REQUEST
    job_id = secrets.token_urlsafe(8)
    jobs[job_id] = {"state": "downloading", "percent": 0}
    threading.Thread(target=_run_job, args=(job_id, video_url), daemon=True).start()
    return jsonify(job=job_id)


@app.route("/progress", methods=["GET"])
def job_progress():
    """Returns {"state": downloading|converting|done|error, "percent": 0-100, "token"/"error"}."""
    job = jobs.get(request.args.get("job", ""))
    if job is None:
        return jsonify(error="Unknown job."), NOT_FOUND
    return jsonify(job)


@app.route("/", methods=["GET"])
def index():
    """Simple GUI: a page with a box to paste a YouTube link."""
    return render_template("index.html")


@app.route("/convert", methods=["GET"])
def handle_audio_request():
    """
    Main endpoint to receive a YouTube video URL, download the audio in MP3 format,
    and return a unique token for accessing the file later.

    Query Parameters:
        - url (str): Full YouTube video URL.

    Returns:
        - JSON: {"token": <download_token>}
    """
    video_url = request.args.get("url")
    if not video_url:
        return jsonify(error="Missing 'url' parameter in request."), BAD_REQUEST

    filename = f"{uuid4()}.mp3"
    try:
        _convert(video_url, filename)
    except Exception as e:
        return jsonify(error="Failed to download or convert audio.", detail=str(e)), INTERNAL_SERVER_ERROR

    return _generate_token_response(filename)


@app.route("/spotify", methods=["GET"])
def spotify_setup_page():
    """Guided setup page for the Spotify API keys."""
    return render_template("spotify.html")


@app.route("/spotify/status", methods=["GET"])
def spotify_status():
    """Tells the GUI whether keys are already saved (never returns the keys)."""
    return jsonify(configured=spotify_config.is_configured())


@app.route("/spotify/save", methods=["POST"])
def spotify_save():
    """Validates a Client ID/secret with Spotify and, if they work, saves them to .env."""
    data = request.get_json(silent=True) or {}
    client_id = str(data.get("client_id", "")).strip()
    client_secret = str(data.get("client_secret", "")).strip()
    if not client_id or not client_secret:
        return jsonify(error="Please fill in both the Client ID and the Client secret."), BAD_REQUEST
    problem = spotify_config.check_credentials(client_id, client_secret)
    if problem:
        return jsonify(error=problem), BAD_REQUEST
    spotify_config.save_credentials(client_id, client_secret)
    return jsonify(ok=True)


@app.route("/similar", methods=["GET"])
def similar():
    """Finds the song in a YouTube link on Spotify and returns 10 related songs."""
    video_url = request.args.get("url")
    if not video_url:
        return jsonify(error="Missing 'url' parameter in request."), BAD_REQUEST
    try:
        return jsonify(similar_songs.find_similar(video_url))
    except similar_songs.SimilarSongsError as e:
        return jsonify(error=str(e)), INTERNAL_SERVER_ERROR


@app.route("/import", methods=["POST"])
def import_songs():
    """Parses pasted/uploaded song text and returns each song with a YouTube link (when found)."""
    data = request.get_json(silent=True) or {}
    queries = song_import.parse_songs(str(data.get("text", "")))
    if not queries:
        return jsonify(error="I couldn't find any song names in that."), BAD_REQUEST
    found = len(queries)
    songs = song_import.resolve_songs(queries[:song_import.MAX_SONGS])
    return jsonify(songs=songs, found=found, limit=song_import.MAX_SONGS)


@app.route("/download", methods=["GET"])
def download_audio():
    """
    Endpoint to serve an audio file associated with a given token.
    If token is valid and not expired, returns the associated MP3 file.

    Query Parameters:
        - token (str): Unique access token

    Returns:
        - MP3 audio file as attachment or error JSON
    """
    token = request.args.get("token")
    if not token:
        return jsonify(error="Missing 'token' parameter in request."), BAD_REQUEST

    if not access_manager.has_access(token):
        return jsonify(error="Token is invalid or unknown."), UNAUTHORIZED

    if not access_manager.is_valid(token):
        return jsonify(error="Token has expired."), REQUEST_TIMEOUT

    try:
        filename = access_manager.get_audio_file(token)
        return send_from_directory(ABS_DOWNLOADS_PATH, filename, as_attachment=True)
    except FileNotFoundError:
        return jsonify(error="Requested file could not be found on the server."), NOT_FOUND


def _generate_token_response(filename: str):
    """
    Generates a secure download token for a given filename,
    registers it in the access manager, and returns the token as JSON.

    Args:
        filename (str): The name of the downloaded MP3 file

    Returns:
        JSON: {"token": <generated_token>}
    """
    token = secrets.token_urlsafe(TOKEN_LENGTH)
    access_manager.add_token(token, filename)
    return jsonify(token=token)


@app.route("/app-info", methods=["GET"])
def app_info():
    """Lets the page know whether it is running as the desktop app (which has a Quit link)."""
    return jsonify(desktop=IS_DESKTOP_APP)


@app.route("/quit", methods=["POST"])
def quit_app():
    """Desktop app only: stops the program, since closing the browser tab doesn't."""
    if not IS_DESKTOP_APP:
        return jsonify(error="Not available."), NOT_FOUND
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return jsonify(ok=True)


def start_token_cleaner():
    """Starts the background thread that deletes expired tokens and their files."""
    # Expiry timers live in memory, so files left by a previous run would never be deleted
    shutil.rmtree(ABS_DOWNLOADS_PATH, ignore_errors=True)
    os.makedirs(ABS_DOWNLOADS_PATH, exist_ok=True)
    threading.Thread(target=access_manager.manage_tokens, daemon=True).start()


def main():
    """Developer mode: token cleanup plus the Flask development server with auto-reload."""
    start_token_cleaner()
    app.run(debug=True)


if __name__ == "__main__":
    main()
