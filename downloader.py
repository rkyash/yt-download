"""
downloader.py
-------------
Download engine for the YouTube Downloader application.

Responsibilities:
  - Fetch video metadata (title, thumbnail, duration, formats …)
  - Execute downloads via yt-dlp in a background thread
  - Report real-time progress via a callback
  - Support pause / cancel tokens
  - Manage a sequential download queue
"""

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Optional

import yt_dlp

from settings import settings, append_history
from utils import (
    sanitize_filename,
    apply_output_template,
    format_filesize,
    format_duration,
    file_already_exists,
    ensure_dir,
    get_ffmpeg_path,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class DownloadStatus(Enum):
    QUEUED = auto()
    FETCHING_INFO = auto()
    DOWNLOADING = auto()
    PROCESSING = auto()   # FFmpeg post-processing
    COMPLETED = auto()
    CANCELLED = auto()
    ERROR = auto()
    PAUSED = auto()


@dataclass
class VideoInfo:
    """Metadata about a video/audio item."""
    url: str
    title: str = "Unknown"
    uploader: str = "Unknown"
    duration: Optional[int] = None       # seconds
    thumbnail_url: Optional[str] = None
    filesize: Optional[int] = None       # bytes
    formats: list[dict] = field(default_factory=list)
    video_id: str = ""
    is_playlist: bool = False
    playlist_entries: list[dict] = field(default_factory=list)


@dataclass
class DownloadTask:
    """Represents a single item in the download queue."""
    task_id: str
    url: str
    title: str
    download_type: str           # "Video+Audio" | "Video Only" | "Audio Only"
    quality: str                 # "best" | "1080p" | "720p" …
    output_folder: str
    output_template: str = "%(title)s.%(ext)s"
    cookies_file: str = ""
    status: DownloadStatus = DownloadStatus.QUEUED
    progress: float = 0.0        # 0-100
    speed: Optional[float] = None
    eta: Optional[int] = None
    filesize: Optional[int] = None
    downloaded_bytes: int = 0
    error_message: str = ""
    output_file: str = ""
    thumbnail_url: str = ""
    uploader: str = ""
    duration: Optional[int] = None
    retries: int = 0
    max_retries: int = 3
    # Split-download fields (0 / None = no splitting)
    start_time: Optional[int] = None   # seconds from start
    end_time: Optional[int] = None     # seconds from start
    part_number: int = 0               # 1-based (0 = not a split task)
    total_parts: int = 0               # total number of parts


# ---------------------------------------------------------------------------
# Progress callback type alias
# ---------------------------------------------------------------------------
ProgressCallback = Callable[[DownloadTask], None]


# ---------------------------------------------------------------------------
# Info fetcher
# ---------------------------------------------------------------------------

def fetch_video_info(url: str, cookies_file: str = "") -> VideoInfo:
    """
    Fetch metadata for *url* using yt-dlp without starting a download.
    Raises yt_dlp.utils.DownloadError or other exceptions on failure.
    """
    ydl_opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": False,   # allow playlist detection
    }
    if cookies_file:
        if os.path.isfile(cookies_file):
            ydl_opts["cookiefile"] = cookies_file
        else:
            # Assume it's a browser name like "edge", "chrome", "firefox", etc.
            ydl_opts["cookiesfrombrowser"] = (cookies_file, )

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        raw = ydl.extract_info(url, download=False)

    if raw is None:
        raise ValueError("yt-dlp returned no information for the URL.")

    # --- Playlist ----------------------------------------------------------
    if raw.get("_type") == "playlist":
        entries = raw.get("entries") or []
        first = entries[0] if entries else {}
        info = VideoInfo(
            url=url,
            title=raw.get("title", "Playlist"),
            uploader=raw.get("uploader", raw.get("channel", "Unknown")),
            is_playlist=True,
            playlist_entries=[
                {
                    "url": e.get("webpage_url", e.get("url", "")),
                    "title": e.get("title", ""),
                    "duration": e.get("duration"),
                    "thumbnail": e.get("thumbnail"),
                }
                for e in entries
                if e
            ],
            thumbnail_url=first.get("thumbnail") or raw.get("thumbnail"),
        )
        return info

    # --- Single video ------------------------------------------------------
    formats = raw.get("formats") or []
    # Build a simplified format list for the resolution chooser
    seen: set = set()
    simple_formats: list[dict] = []
    for f in formats:
        height = f.get("height")
        vcodec = f.get("vcodec", "")
        acodec = f.get("acodec", "")
        if height and vcodec and vcodec != "none":
            label = f"{height}p"
            if label not in seen:
                seen.add(label)
                simple_formats.append({
                    "label": label,
                    "height": height,
                    "format_id": f.get("format_id", ""),
                    "filesize": f.get("filesize") or f.get("filesize_approx"),
                })
    # Sort descending
    simple_formats.sort(key=lambda x: x["height"], reverse=True)

    return VideoInfo(
        url=url,
        title=raw.get("title", "Unknown"),
        uploader=raw.get("uploader", raw.get("channel", "Unknown")),
        duration=raw.get("duration"),
        thumbnail_url=raw.get("thumbnail"),
        filesize=raw.get("filesize") or raw.get("filesize_approx"),
        formats=simple_formats,
        video_id=raw.get("id", ""),
    )


# ---------------------------------------------------------------------------
# yt-dlp format selector
# ---------------------------------------------------------------------------

def _build_format_string(download_type: str, quality: str) -> str:
    """
    Return a yt-dlp format selector string based on download type and quality.

    Strategy for Video+Audio:
      1. H.264 (avc1) video  +  AAC/M4A audio  → universally compatible MP4
      2. H.264 video  +  any audio             → still good compatibility
      3. Any video  +  any audio               → last resort (may need recoding)

    This ensures the output plays on VLC, Windows Media Player, QuickTime,
    mobile devices, etc. without needing extra codecs.
    """
    quality_map = {
        "best": "",
        "1080p": "[height<=1080]",
        "720p":  "[height<=720]",
        "480p":  "[height<=480]",
        "360p":  "[height<=360]",
        "240p":  "[height<=240]",
    }
    hf = quality_map.get(quality, "")   # height filter, e.g. "[height<=720]"

    if download_type == "Audio Only":
        # Prefer M4A (AAC) — plays everywhere; fall back to best audio
        return "bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]/bestaudio/best"

    if download_type == "Video Only":
        # H.264 preferred, then anything
        if hf:
            return (
                f"bestvideo[vcodec^=avc1]{hf}/"
                f"bestvideo[vcodec^=h264]{hf}/"
                f"bestvideo{hf}/bestvideo"
            )
        return "bestvideo[vcodec^=avc1]/bestvideo[vcodec^=h264]/bestvideo/best"

    # ── Video + Audio ────────────────────────────────────────────────────────
    # Priority:
    #   1. H.264 video + AAC audio  (best compatibility)
    #   2. H.264 video + any audio  (recoder will fix audio if needed)
    #   3. any video   + any audio  (recoder will fix everything if needed)
    if hf:
        return (
            f"bestvideo[vcodec^=avc1]{hf}+bestaudio[acodec^=mp4a]/"
            f"bestvideo[vcodec^=avc1]{hf}+bestaudio/"
            f"bestvideo[vcodec^=h264]{hf}+bestaudio/"
            f"bestvideo{hf}+bestaudio/"
            f"best{hf}/best"
        )
    return (
        "bestvideo[vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
        "bestvideo[vcodec^=avc1]+bestaudio/"
        "bestvideo[vcodec^=h264]+bestaudio/"
        "bestvideo+bestaudio/best"
    )


# ---------------------------------------------------------------------------
# Core downloader
# ---------------------------------------------------------------------------

class Downloader:
    """
    Wraps yt-dlp to download a single DownloadTask.

    Pass a *progress_callback* that will be invoked (from the download thread)
    whenever the task state changes.
    """

    def __init__(
        self,
        task: DownloadTask,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> None:
        self.task = task
        self._progress_callback = progress_callback
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()   # not paused initially

    # ------------------------------------------------------------------

    def cancel(self) -> None:
        """Signal the download to stop."""
        self._cancel_event.set()
        self._pause_event.set()   # unblock if paused

    def pause(self) -> None:
        """Pause the download (best-effort – yt-dlp may not honour mid-chunk)."""
        self._pause_event.clear()
        self.task.status = DownloadStatus.PAUSED
        self._notify()

    def resume(self) -> None:
        """Resume a paused download."""
        self._pause_event.set()
        self.task.status = DownloadStatus.DOWNLOADING
        self._notify()

    # ------------------------------------------------------------------

    def _notify(self) -> None:
        if self._progress_callback:
            try:
                self._progress_callback(self.task)
            except Exception:
                pass   # never crash the download thread due to UI errors

    def _ydl_progress_hook(self, d: dict) -> None:
        """Called by yt-dlp on every progress update."""
        # Honour pause / cancel
        if self._cancel_event.is_set():
            raise yt_dlp.utils.DownloadError("Cancelled by user")
        self._pause_event.wait()   # blocks if paused

        status = d.get("status", "")

        if status == "downloading":
            self.task.status = DownloadStatus.DOWNLOADING
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes", 0)
            if total:
                self.task.progress = downloaded / total * 100
                self.task.filesize = total
            self.task.downloaded_bytes = downloaded
            self.task.speed = d.get("speed")
            self.task.eta = d.get("eta")

        elif status == "finished":
            # File has been fully downloaded; FFmpeg post-processing may follow
            self.task.status = DownloadStatus.PROCESSING
            self.task.progress = 100.0
            filename = d.get("filename", "")
            if filename:
                self.task.output_file = filename

        self._notify()

    def _build_ydl_opts(self) -> dict:
        """Construct the yt-dlp options dictionary for this task."""
        ensure_dir(self.task.output_folder)

        fmt = _build_format_string(self.task.download_type, self.task.quality)

        safe_title = sanitize_filename(self.task.title)

        # For split tasks append "_part_N_of_M" so each part saves separately
        if self.task.part_number and self.task.total_parts:
            part_suffix = f"_part_{self.task.part_number}_of_{self.task.total_parts}"
        else:
            part_suffix = ""

        outtmpl = os.path.join(
            self.task.output_folder,
            safe_title + part_suffix + ".%(ext)s",
        )

        opts: dict = {
            "format": fmt,
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [self._ydl_progress_hook],
            "noplaylist": True,
            # Always merge/container into MP4 for maximum compatibility
            "merge_output_format": "mp4",
            "writethumbnail": False,
            "retries": self.task.max_retries,
            "ffmpeg_location": get_ffmpeg_path(),
        }

        if self.task.download_type == "Audio Only":
            # ── Audio only ────────────────────────────────────────────────
            audio_fmt = settings.get("audio_format", "mp3")
            opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": audio_fmt,
                    "preferredquality": "192",
                }
            ]
            opts["merge_output_format"] = audio_fmt

        elif self.task.download_type in ("Video+Audio", "Video Only"):
            # ── Video: ensure H.264 + AAC in MP4 ─────────────────────────
            # If yt-dlp could not find a native H.264 stream (e.g. the video
            # is only available in VP9/AV1), FFmpegVideoConvertor re-encodes
            # it to H.264 so it plays on every device without extra codecs.
            opts["postprocessors"] = [
                {
                    # Re-encode to H.264/AAC only when the merged output is
                    # NOT already in an MP4-friendly codec pair.
                    # 'mp4' here means "ensure output is playable MP4".
                    "key": "FFmpegVideoConvertor",
                    "preferedformat": "mp4",   # yt-dlp spelling (one 'r')
                }
            ]

        # ── Split / trim section ──────────────────────────────────────────────
        # Use yt-dlp's download_ranges to fetch only the requested slice.
        # force_keyframes_at_cuts ensures FFmpeg cuts on a clean frame boundary
        # so the trimmed clip starts/ends without glitches.
        if self.task.start_time is not None and self.task.end_time is not None:
            try:
                from yt_dlp.utils import download_range_func
                opts["download_ranges"] = download_range_func(
                    None,
                    [(self.task.start_time, self.task.end_time)]
                )
                opts["force_keyframes_at_cuts"] = True
            except Exception as exc:
                logger.warning("download_range_func not available: %s", exc)

        # Cookies
        if self.task.cookies_file:
            if os.path.isfile(self.task.cookies_file):
                opts["cookiefile"] = self.task.cookies_file
            else:
                opts["cookiesfrombrowser"] = (self.task.cookies_file, )

        return opts

    def download(self) -> None:
        """Execute the download synchronously (call from a thread)."""
        task = self.task
        task.status = DownloadStatus.DOWNLOADING
        self._notify()

        try:
            opts = self._build_ydl_opts()
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([task.url])

            if self._cancel_event.is_set():
                task.status = DownloadStatus.CANCELLED
            else:
                task.status = DownloadStatus.COMPLETED
                task.progress = 100.0
                # Record history
                append_history(
                    {
                        "title": task.title,
                        "url": task.url,
                        "output_file": task.output_file,
                        "output_folder": task.output_folder,
                        "download_type": task.download_type,
                        "quality": task.quality,
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "thumbnail_url": task.thumbnail_url,
                        "uploader": task.uploader,
                        "duration": task.duration,
                    }
                )

        except yt_dlp.utils.DownloadError as exc:
            if self._cancel_event.is_set():
                task.status = DownloadStatus.CANCELLED
            else:
                task.status = DownloadStatus.ERROR
                task.error_message = str(exc)
                logger.error("Download failed: %s", exc)
        except Exception as exc:
            task.status = DownloadStatus.ERROR
            task.error_message = str(exc)
            logger.exception("Unexpected download error: %s", exc)

        self._notify()


# ---------------------------------------------------------------------------
# Download Queue Manager
# ---------------------------------------------------------------------------

class DownloadQueue:
    """
    Manages a FIFO queue of DownloadTask objects, running up to
    *max_workers* downloads concurrently.

    Thread-safe – all public methods can be called from any thread.
    """

    def __init__(
        self,
        max_workers: int = 2,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> None:
        self._max_workers = max_workers
        self._progress_callback = progress_callback
        self._tasks: list[DownloadTask] = []
        self._active_downloaders: dict[str, Downloader] = {}
        self._lock = threading.Lock()
        self._scheduler_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._task_counter = 0

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    def add_task(self, task: DownloadTask) -> None:
        """Enqueue a new download task and start the scheduler if needed."""
        with self._lock:
            self._tasks.append(task)
        self._ensure_scheduler_running()

    def cancel_task(self, task_id: str) -> None:
        """Cancel a specific task (whether queued or in-progress)."""
        with self._lock:
            dl = self._active_downloaders.get(task_id)
        if dl:
            dl.cancel()
        else:
            # Mark queued task as cancelled
            for task in self._tasks:
                if task.task_id == task_id and task.status == DownloadStatus.QUEUED:
                    task.status = DownloadStatus.CANCELLED
                    if self._progress_callback:
                        self._progress_callback(task)

    def pause_task(self, task_id: str) -> None:
        """Pause an active download."""
        with self._lock:
            dl = self._active_downloaders.get(task_id)
        if dl:
            dl.pause()

    def resume_task(self, task_id: str) -> None:
        """Resume a paused download."""
        with self._lock:
            dl = self._active_downloaders.get(task_id)
        if dl:
            dl.resume()

    def retry_task(self, task: DownloadTask) -> None:
        """Reset a failed/cancelled task and re-enqueue it."""
        task.status = DownloadStatus.QUEUED
        task.progress = 0.0
        task.error_message = ""
        task.retries += 1
        self.add_task(task)

    def get_tasks(self) -> list[DownloadTask]:
        """Return a snapshot of all tasks (any status)."""
        with self._lock:
            return list(self._tasks)

    def clear_completed(self) -> None:
        """Remove completed / cancelled / errored tasks from the list."""
        with self._lock:
            self._tasks = [
                t for t in self._tasks
                if t.status not in (
                    DownloadStatus.COMPLETED,
                    DownloadStatus.CANCELLED,
                    DownloadStatus.ERROR,
                )
            ]

    # ------------------------------------------------------------------
    # Scheduler
    # ------------------------------------------------------------------

    def _ensure_scheduler_running(self) -> None:
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            return
        self._stop_event.clear()
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop, daemon=True, name="DownloadScheduler"
        )
        self._scheduler_thread.start()

    def _scheduler_loop(self) -> None:
        """Continuously start queued tasks up to the worker limit."""
        while not self._stop_event.is_set():
            self._tick()
            time.sleep(0.5)

    def _tick(self) -> None:
        with self._lock:
            active_count = len(self._active_downloaders)
            if active_count >= self._max_workers:
                return
            # Find next queued task
            queued = [t for t in self._tasks if t.status == DownloadStatus.QUEUED]
            if not queued:
                return
            task = queued[0]
            task.status = DownloadStatus.DOWNLOADING

        self._start_download(task)

    def _start_download(self, task: DownloadTask) -> None:
        dl = Downloader(task, progress_callback=self._wrapped_callback)
        with self._lock:
            self._active_downloaders[task.task_id] = dl
        thread = threading.Thread(
            target=self._run_download,
            args=(dl,),
            daemon=True,
            name=f"Download-{task.task_id}",
        )
        thread.start()

    def _run_download(self, dl: Downloader) -> None:
        try:
            dl.download()
        finally:
            with self._lock:
                self._active_downloaders.pop(dl.task.task_id, None)

    def _wrapped_callback(self, task: DownloadTask) -> None:
        if self._progress_callback:
            self._progress_callback(task)

    def stop(self) -> None:
        """Stop the scheduler (does not cancel in-progress downloads)."""
        self._stop_event.set()

    def update_max_workers(self, n: int) -> None:
        """Update the maximum number of simultaneous downloads."""
        self._max_workers = max(1, n)

    def next_task_id(self) -> str:
        """Generate a unique task ID."""
        self._task_counter += 1
        return f"task_{self._task_counter}"
