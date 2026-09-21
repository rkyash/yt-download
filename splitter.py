"""
splitter.py
-----------
Video splitting engine for the YouTube Downloader application.

Responsibilities:
  - Probe local video files for metadata (duration, codec, resolution, size)
  - Split a video into sequential parts using FFmpeg stream-copy (-c copy)
  - Report progress via a callback (same pattern as downloader.py)
"""

import logging
import math
import os
import re
import subprocess
import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Optional

from utils import get_ffmpeg_path, format_duration

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class SplitStatus(Enum):
    IDLE = auto()
    VALIDATING = auto()
    SPLITTING = auto()
    COMPLETED = auto()
    ERROR = auto()


@dataclass
class VideoFileInfo:
    """Metadata about a local video file (obtained via ffprobe)."""
    path: str
    filename: str = ""
    duration: float = 0.0          # seconds
    video_codec: str = ""
    audio_codec: str = ""
    resolution: str = ""           # e.g. "1920x1080"
    filesize: int = 0              # bytes
    format_name: str = ""          # e.g. "mp4" / "matroska"
    extension: str = ""            # e.g. ".mp4"


@dataclass
class SplitTask:
    """Represents a single video-split operation."""
    source_path: str
    segment_duration: float        # seconds
    destination_folder: str
    status: SplitStatus = SplitStatus.IDLE
    total_parts: int = 0
    parts_done: int = 0
    current_part: int = 0          # 1-based, the part currently being written
    error_message: str = ""
    output_files: list[str] = field(default_factory=list)
    video_info: Optional[VideoFileInfo] = None


# ---------------------------------------------------------------------------
# Progress callback type alias
# ---------------------------------------------------------------------------
SplitProgressCallback = Callable[[SplitTask], None]


# ---------------------------------------------------------------------------
# Supported video extensions (common containers FFmpeg can handle)
# ---------------------------------------------------------------------------

SUPPORTED_VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm",
    ".m4v", ".mpg", ".mpeg", ".3gp", ".ts", ".mts", ".vob",
}


# ---------------------------------------------------------------------------
# Video probe helper  (uses ffmpeg -i, no ffprobe required)
# ---------------------------------------------------------------------------

# Regex patterns for parsing ffmpeg -i stderr output
_RE_DURATION = re.compile(
    r"Duration:\s*(\d{2}):(\d{2}):(\d{2})\.(\d+)"
)
_RE_VIDEO_STREAM = re.compile(
    r"Stream\s+#\d+:\d+.*:\s*Video:\s*(\w+)"       # codec name
    r".*?,\s*(\d{2,5})x(\d{2,5})",                  # WxH resolution
    re.IGNORECASE,
)
_RE_AUDIO_STREAM = re.compile(
    r"Stream\s+#\d+:\d+.*:\s*Audio:\s*(\w+)",       # codec name
    re.IGNORECASE,
)


def probe_video(path: str) -> VideoFileInfo:
    """
    Run ``ffmpeg -i`` on *path* and parse the stderr output to extract
    video metadata (duration, codecs, resolution, file size).

    This avoids the need for a separate ``ffprobe`` binary — only the
    bundled ``ffmpeg.exe`` is required.

    Raises ``ValueError`` if the file is not a supported video or
    ffmpeg cannot read it.
    """
    if not os.path.isfile(path):
        raise ValueError(f"File not found: {path}")

    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED_VIDEO_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{ext}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_VIDEO_EXTENSIONS))}"
        )

    ffmpeg = get_ffmpeg_path()
    cmd = [ffmpeg, "-i", path]

    try:
        # ffmpeg -i always exits with code 1 (no output file specified),
        # but it prints all stream info to stderr — which is exactly what
        # we need.
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except FileNotFoundError:
        raise ValueError(
            "FFmpeg was not found. Ensure ffmpeg.exe is in the project folder."
        )
    except subprocess.TimeoutExpired:
        raise ValueError("FFmpeg timed out while reading the file.")

    stderr = result.stderr

    # --- Duration ---
    duration = 0.0
    m = _RE_DURATION.search(stderr)
    if m:
        h, mins, secs, frac = m.groups()
        duration = int(h) * 3600 + int(mins) * 60 + int(secs) + float(f"0.{frac}")

    if duration <= 0:
        # Check if ffmpeg actually recognized the file at all
        if "Invalid data" in stderr or "No such file" in stderr:
            raise ValueError("FFmpeg could not read the file. It may be corrupt.")
        raise ValueError("Could not determine video duration. The file may be corrupt.")

    # --- Video stream ---
    video_codec = ""
    resolution = ""
    vm = _RE_VIDEO_STREAM.search(stderr)
    if vm:
        video_codec = vm.group(1)
        resolution = f"{vm.group(2)}x{vm.group(3)}"

    # --- Audio stream ---
    audio_codec = ""
    am = _RE_AUDIO_STREAM.search(stderr)
    if am:
        audio_codec = am.group(1)

    # --- File size (from OS, not ffmpeg) ---
    filesize = os.path.getsize(path)

    # --- Format name from extension ---
    format_map = {
        ".mp4": "mp4", ".mkv": "matroska", ".avi": "avi", ".mov": "mov",
        ".wmv": "wmv", ".flv": "flv", ".webm": "webm", ".m4v": "mp4",
        ".mpg": "mpeg", ".mpeg": "mpeg", ".3gp": "3gp", ".ts": "mpegts",
        ".mts": "mpegts", ".vob": "vob",
    }
    format_name = format_map.get(ext, "")

    return VideoFileInfo(
        path=path,
        filename=os.path.basename(path),
        duration=duration,
        video_codec=video_codec,
        audio_codec=audio_codec,
        resolution=resolution,
        filesize=filesize,
        format_name=format_name,
        extension=ext,
    )


# ---------------------------------------------------------------------------
# Core splitter
# ---------------------------------------------------------------------------

def split_video(
    task: SplitTask,
    progress_callback: Optional[SplitProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
) -> None:
    """
    Split a video file into sequential parts using FFmpeg stream-copy.

    This function is designed to be called from a **background thread**.
    It updates *task* in-place and invokes *progress_callback* after each
    part is written.

    Parameters
    ----------
    task : SplitTask
        Must have ``source_path``, ``segment_duration``, and
        ``destination_folder`` populated.
    progress_callback : callable, optional
        ``callback(task)`` — called after each part completes.
    cancel_event : threading.Event, optional
        If set, the split is cancelled between parts.
    """

    def _notify() -> None:
        if progress_callback:
            try:
                progress_callback(task)
            except Exception:
                pass

    # ── Validation ────────────────────────────────────────────────────────
    task.status = SplitStatus.VALIDATING
    _notify()

    if not os.path.isfile(task.source_path):
        task.status = SplitStatus.ERROR
        task.error_message = f"Source file not found: {task.source_path}"
        _notify()
        return

    if task.segment_duration <= 0:
        task.status = SplitStatus.ERROR
        task.error_message = "Segment duration must be greater than zero."
        _notify()
        return

    dest = Path(task.destination_folder)
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        task.status = SplitStatus.ERROR
        task.error_message = f"Cannot create destination folder: {exc}"
        _notify()
        return

    # ── Probe the video for duration and extension ────────────────────────
    try:
        info = probe_video(task.source_path)
    except ValueError as exc:
        task.status = SplitStatus.ERROR
        task.error_message = str(exc)
        _notify()
        return

    task.video_info = info
    total_duration = info.duration
    segment_sec = task.segment_duration
    num_parts = math.ceil(total_duration / segment_sec)
    task.total_parts = num_parts

    # ── Split loop ────────────────────────────────────────────────────────
    task.status = SplitStatus.SPLITTING
    task.parts_done = 0
    task.output_files = []
    _notify()

    ffmpeg = get_ffmpeg_path()
    ext = info.extension  # preserve original extension

    for i in range(num_parts):
        # Check for cancellation
        if cancel_event and cancel_event.is_set():
            task.status = SplitStatus.ERROR
            task.error_message = "Cancelled by user."
            _notify()
            return

        start = i * segment_sec
        # For the last part, let FFmpeg run to the end of file
        is_last = (i == num_parts - 1)

        # Use the first 6 characters of the source filename as prefix
        # (or the full name if shorter than 6 chars)
        src_stem = os.path.splitext(os.path.basename(task.source_path))[0].strip()
        prefix = src_stem[:6] if src_stem else "video"
        part_name = f"{prefix}_part_{i + 1:03d}{ext}"
        part_path = str(dest / part_name)

        task.current_part = i + 1
        _notify()

        cmd = [
            ffmpeg,
            "-y",                          # overwrite without asking
            "-i", task.source_path,
            "-ss", str(start),
        ]
        if not is_last:
            cmd += ["-t", str(segment_sec)]

        cmd += [
            "-c", "copy",                  # stream-copy (no re-encoding)
            "-map", "0",                   # copy all streams
            "-avoid_negative_ts", "make_zero",
            part_path,
        ]

        logger.info("Splitting part %d/%d: %s", i + 1, num_parts, part_name)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except FileNotFoundError:
            task.status = SplitStatus.ERROR
            task.error_message = (
                "FFmpeg was not found. Ensure ffmpeg.exe is in the project folder."
            )
            _notify()
            return
        except Exception as exc:
            task.status = SplitStatus.ERROR
            task.error_message = f"FFmpeg error: {exc}"
            _notify()
            return

        if result.returncode != 0:
            stderr = result.stderr.strip()
            # Extract the last meaningful line from stderr
            lines = [ln for ln in stderr.splitlines() if ln.strip()]
            short = lines[-1] if lines else "unknown error"
            task.status = SplitStatus.ERROR
            task.error_message = f"FFmpeg failed on part {i + 1}: {short}"
            _notify()
            return

        task.output_files.append(part_path)
        task.parts_done = i + 1
        _notify()

    # ── Done ──────────────────────────────────────────────────────────────
    task.status = SplitStatus.COMPLETED
    _notify()
    logger.info(
        "Split complete: %d parts saved to %s",
        num_parts, task.destination_folder,
    )
