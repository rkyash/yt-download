"""
utils.py
--------
Utility functions for the YouTube Downloader application.
Provides URL validation, filename sanitization, formatting helpers,
and other shared utilities used across modules.
"""

import re
import os
import sys
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FFmpeg Helpers
# ---------------------------------------------------------------------------

def get_ffmpeg_path() -> str:
    """Finds the bundled ffmpeg binary when running as a PyInstaller executable."""
    ffmpeg_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    if getattr(sys, 'frozen', False):
        # The app is running as a bundled PyInstaller executable
        return os.path.join(sys._MEIPASS, ffmpeg_name)
    else:
        # The app is running as a normal Python script
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), ffmpeg_name)


# ---------------------------------------------------------------------------
# URL Helpers
# ---------------------------------------------------------------------------

YOUTUBE_URL_PATTERN = re.compile(
    r"(https?://)?(www\.)?"
    r"("
    r"youtube\.com/(watch\?v=|embed/|shorts/|live/|v/|e/|playlist\?list=)"
    r"|youtu\.be/"
    r")"
    r"[\w\-_]+"  # video / playlist ID
)

PLAYLIST_URL_PATTERN = re.compile(
    r"(https?://)?(www\.)?youtube\.com/playlist\?list=[\w\-_]+"
)


def is_valid_youtube_url(url: str) -> bool:
    """Return True if *url* looks like a valid YouTube URL."""
    return bool(YOUTUBE_URL_PATTERN.match(url.strip()))


def is_playlist_url(url: str) -> bool:
    """Return True if *url* is a YouTube playlist URL."""
    return bool(PLAYLIST_URL_PATTERN.match(url.strip())) or (
        "list=" in url and "youtube.com" in url
    )


def normalize_url(url: str) -> str:
    """Strip whitespace and ensure the URL starts with https://."""
    url = url.strip()
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


# ---------------------------------------------------------------------------
# Filename Helpers
# ---------------------------------------------------------------------------

_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1F]')
_SPACES = re.compile(r"\s+")
_LEADING_DOTS = re.compile(r"^\.+")


def sanitize_filename(name: str, max_length: int = 200) -> str:
    """
    Remove or replace characters that are illegal in file names on Windows,
    macOS, and Linux, then truncate to *max_length*.
    """
    name = _ILLEGAL_CHARS.sub("_", name)
    name = _SPACES.sub(" ", name).strip()
    name = _LEADING_DOTS.sub("", name)
    if not name:
        name = "download"
    return name[:max_length]


def apply_output_template(template: str, info: dict) -> str:
    """
    Replace known placeholders in *template* with values from *info*.

    Supported placeholders:
        %(title)s, %(uploader)s, %(id)s, %(ext)s, %(resolution)s
    """
    mapping = {
        "%(title)s": sanitize_filename(info.get("title", "video")),
        "%(uploader)s": sanitize_filename(info.get("uploader", "unknown")),
        "%(id)s": info.get("id", ""),
        "%(ext)s": info.get("ext", "mp4"),
        "%(resolution)s": info.get("resolution", ""),
    }
    for placeholder, value in mapping.items():
        template = template.replace(placeholder, value)
    return template


# ---------------------------------------------------------------------------
# Size / Duration Formatting
# ---------------------------------------------------------------------------

def format_filesize(size_bytes: Optional[int]) -> str:
    """Convert bytes to a human-readable string (e.g. '1.23 GB')."""
    if size_bytes is None:
        return "Unknown"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size_bytes) < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0  # type: ignore[assignment]
    return f"{size_bytes:.2f} PB"


def format_duration(seconds: Optional[int]) -> str:
    """Convert seconds to HH:MM:SS or MM:SS string."""
    if seconds is None:
        return "Unknown"
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_speed(speed_bps: Optional[float]) -> str:
    """Convert bytes-per-second to a human-readable speed string."""
    if speed_bps is None:
        return "---"
    return format_filesize(int(speed_bps)) + "/s"


def format_eta(eta_seconds: Optional[int]) -> str:
    """Convert ETA in seconds to a human-readable string."""
    if eta_seconds is None:
        return "---"
    eta_seconds = int(eta_seconds)
    if eta_seconds < 60:
        return f"{eta_seconds}s"
    m = eta_seconds // 60
    s = eta_seconds % 60
    return f"{m}m {s}s"


# ---------------------------------------------------------------------------
# Path Helpers
# ---------------------------------------------------------------------------

def ensure_dir(path: str) -> Path:
    """Create *path* (including parents) if it does not exist and return a Path."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def open_in_file_manager(path: str) -> None:
    """Open *path* in the system's default file manager."""
    import subprocess
    import sys

    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:  # Linux / BSD
            subprocess.Popen(["xdg-open", path])
    except Exception as exc:
        logger.error("Failed to open file manager: %s", exc)


def open_file(path: str) -> None:
    """Open *path* using the system's default application."""
    import subprocess
    import sys

    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as exc:
        logger.error("Failed to open file: %s", exc)


# ---------------------------------------------------------------------------
# Duplicate Detection
# ---------------------------------------------------------------------------

def build_expected_path(download_folder: str, title: str, ext: str) -> str:
    """Build the expected final file path for a download."""
    filename = sanitize_filename(title) + "." + ext
    return os.path.join(download_folder, filename)


def file_already_exists(download_folder: str, title: str, ext: str) -> bool:
    """Return True if the expected output file already exists on disk."""
    path = build_expected_path(download_folder, title, ext)
    return os.path.isfile(path)
