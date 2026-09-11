"""
gui.py
------
Main GUI for the YouTube Downloader application built with CustomTkinter.

Layout
──────
┌─────────────────────────────────────────────────┐
│  Sidebar  │            Main Content              │
│  • Home   │  (URL entry, info panel, queue)      │
│  • Queue  │                                      │
│  • History│                                      │
│  • Settings│                                     │
│  • About  │                                      │
└─────────────────────────────────────────────────┘
"""

import io
import logging
import os
import threading
import time
import tkinter as tk
import tkinter.messagebox as messagebox
import tkinter.filedialog as filedialog
import uuid
from pathlib import Path
from typing import Optional

import customtkinter as ctk
from PIL import Image, ImageTk

# Try to import requests for thumbnail downloads
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from downloader import (
    DownloadQueue,
    DownloadStatus,
    DownloadTask,
    VideoInfo,
    fetch_video_info,
)
from settings import settings, load_history, save_history
from utils import (
    format_duration,
    format_eta,
    format_filesize,
    format_speed,
    get_resource_path,
    is_valid_youtube_url,
    is_playlist_url,
    normalize_url,
    open_file,
    open_in_file_manager,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants / palette helpers
# ---------------------------------------------------------------------------

APP_NAME = "YT Downloader"
APP_VERSION = "1.0.0"

SIDEBAR_WIDTH = 200
QUALITY_OPTIONS = ["Best", "1080p", "720p", "480p", "360p", "240p"]
DOWNLOAD_TYPE_OPTIONS = ["Video+Audio", "Video Only", "Audio Only"]
AUDIO_FORMAT_OPTIONS = ["mp3", "m4a", "aac", "opus"]
THEME_OPTIONS = ["dark", "light", "system"]
COLOR_THEME_OPTIONS = ["blue", "green", "dark-blue"]
MAX_WORKERS_OPTIONS = ["1", "2", "3", "4"]

STATUS_COLORS = {
    DownloadStatus.QUEUED:       ("#6C7A89", "#95A5A6"),
    DownloadStatus.FETCHING_INFO:("#F39C12", "#E67E22"),
    DownloadStatus.DOWNLOADING:  ("#2980B9", "#3498DB"),
    DownloadStatus.PROCESSING:   ("#8E44AD", "#9B59B6"),
    DownloadStatus.COMPLETED:    ("#27AE60", "#2ECC71"),
    DownloadStatus.CANCELLED:    ("#7F8C8D", "#95A5A6"),
    DownloadStatus.ERROR:        ("#C0392B", "#E74C3C"),
    DownloadStatus.PAUSED:       ("#D35400", "#E67E22"),
}

STATUS_LABELS = {
    DownloadStatus.QUEUED:       "Queued",
    DownloadStatus.FETCHING_INFO:"Fetching info…",
    DownloadStatus.DOWNLOADING:  "Downloading",
    DownloadStatus.PROCESSING:   "Processing",
    DownloadStatus.COMPLETED:    "Completed",
    DownloadStatus.CANCELLED:    "Cancelled",
    DownloadStatus.ERROR:        "Error",
    DownloadStatus.PAUSED:       "Paused",
}


# ---------------------------------------------------------------------------
# Thumbnail loader (runs in a background thread)
# ---------------------------------------------------------------------------

def _load_thumbnail(url: str, size: tuple[int, int] = (160, 90)) -> Optional[Image.Image]:
    """Download and resize a thumbnail image. Returns None on failure."""
    if not url or not REQUESTS_AVAILABLE:
        return None
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        img.thumbnail(size, Image.LANCZOS)
        return img
    except Exception as exc:
        logger.debug("Thumbnail load failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Reusable widgets
# ---------------------------------------------------------------------------

class SidebarButton(ctk.CTkButton):
    """Styled sidebar navigation button."""

    def __init__(self, master, text: str, icon: str = "", **kwargs):
        label = f"{icon}  {text}" if icon else text
        super().__init__(
            master,
            text=label,
            anchor="w",
            corner_radius=10,
            height=44,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="transparent",
            hover_color=("gray75", "gray25"),
            text_color=("black", "white"),
            **kwargs,
        )


class SectionTitle(ctk.CTkLabel):
    """Large bold section heading."""

    def __init__(self, master, text: str, **kwargs):
        super().__init__(
            master,
            text=text,
            font=ctk.CTkFont(size=22, weight="bold"),
            **kwargs,
        )


class Card(ctk.CTkFrame):
    """Rounded card container."""

    def __init__(self, master, **kwargs):
        super().__init__(master, corner_radius=14, **kwargs)


# ---------------------------------------------------------------------------
# Download queue row widget
# ---------------------------------------------------------------------------

class QueueRow(ctk.CTkFrame):
    """
    One row in the download queue panel, displaying:
      thumbnail | title / uploader / status | progress bar | speed/ETA | controls
    """

    THUMB_W, THUMB_H = 112, 63

    def __init__(self, master, task: DownloadTask, queue_ref: DownloadQueue, **kwargs):
        super().__init__(master, corner_radius=12, **kwargs)
        self.task = task
        self.queue_ref = queue_ref
        self._thumb_image: Optional[ctk.CTkImage] = None

        self.columnconfigure(1, weight=1)

        # --- Thumbnail ---
        self._thumb_label = ctk.CTkLabel(self, text="", width=self.THUMB_W, height=self.THUMB_H)
        self._thumb_label.grid(row=0, column=0, rowspan=3, padx=(10, 8), pady=8, sticky="ns")

        # --- Title ---
        self._title_var = tk.StringVar(value=task.title)
        ctk.CTkLabel(
            self, textvariable=self._title_var,
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w", wraplength=320,
        ).grid(row=0, column=1, sticky="ew", padx=4, pady=(8, 0))

        # --- Sub-info: uploader + status ---
        self._info_var = tk.StringVar(value=f"{task.uploader}  ·  {STATUS_LABELS.get(task.status, '?')}")
        self._info_label = ctk.CTkLabel(
            self, textvariable=self._info_var,
            font=ctk.CTkFont(size=11),
            anchor="w",
            text_color=("gray50", "gray60"),
        )
        self._info_label.grid(row=1, column=1, sticky="ew", padx=4)

        # --- Progress bar ---
        self._progress_var = tk.DoubleVar(value=task.progress)
        self._progress_bar = ctk.CTkProgressBar(self, variable=self._progress_var, height=8)
        self._progress_bar.grid(row=2, column=1, sticky="ew", padx=4, pady=(4, 0))

        # --- Speed / ETA / Percent ---
        self._speed_var = tk.StringVar(value="")
        ctk.CTkLabel(
            self, textvariable=self._speed_var,
            font=ctk.CTkFont(size=10),
            text_color=("gray50", "gray60"),
            anchor="w",
        ).grid(row=3, column=1, sticky="w", padx=4, pady=(2, 6))

        # --- Buttons ---
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=0, column=2, rowspan=4, padx=8, pady=8, sticky="ns")

        self._pause_btn = ctk.CTkButton(
            btn_frame, text="⏸", width=32, height=32, corner_radius=8,
            command=self._toggle_pause,
        )
        self._pause_btn.pack(pady=2)

        ctk.CTkButton(
            btn_frame, text="✕", width=32, height=32, corner_radius=8,
            fg_color=("#C0392B", "#922B21"),
            hover_color=("#A93226", "#7B241C"),
            command=self._cancel,
        ).pack(pady=2)

        ctk.CTkButton(
            btn_frame, text="📂", width=32, height=32, corner_radius=8,
            command=self._open_folder,
        ).pack(pady=2)

        # Load thumbnail in background
        if task.thumbnail_url:
            threading.Thread(target=self._fetch_thumb, daemon=True).start()

    # ------------------------------------------------------------------

    def _fetch_thumb(self) -> None:
        img = _load_thumbnail(self.task.thumbnail_url, (self.THUMB_W, self.THUMB_H))
        if img:
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img,
                                   size=(self.THUMB_W, self.THUMB_H))
            self._thumb_image = ctk_img
            try:
                self._thumb_label.configure(image=ctk_img)
            except Exception:
                pass

    def _toggle_pause(self) -> None:
        if self.task.status == DownloadStatus.PAUSED:
            self.queue_ref.resume_task(self.task.task_id)
            self._pause_btn.configure(text="⏸")
        else:
            self.queue_ref.pause_task(self.task.task_id)
            self._pause_btn.configure(text="▶")

    def _cancel(self) -> None:
        self.queue_ref.cancel_task(self.task.task_id)

    def _open_folder(self) -> None:
        open_in_file_manager(self.task.output_folder)

    def update_ui(self) -> None:
        """Refresh all dynamic labels from self.task (call from main thread)."""
        self._title_var.set(self.task.title)
        status_label = STATUS_LABELS.get(self.task.status, "?")
        uploader = self.task.uploader or ""
        self._info_var.set(f"{uploader}  ·  {status_label}" if uploader else status_label)
        self._progress_var.set(self.task.progress / 100.0)

        speed_str = format_speed(self.task.speed)
        eta_str = format_eta(self.task.eta)
        pct = f"{self.task.progress:.1f}%"
        self._speed_var.set(f"{pct}   ↓ {speed_str}   ETA {eta_str}")

        # Color the progress bar
        colors = STATUS_COLORS.get(self.task.status, ("#3498DB", "#2980B9"))
        self._progress_bar.configure(progress_color=colors[1])

        # Enable/disable pause button
        can_pause = self.task.status in (DownloadStatus.DOWNLOADING, DownloadStatus.PAUSED)
        self._pause_btn.configure(state="normal" if can_pause else "disabled")


# ---------------------------------------------------------------------------
# Main Application Window
# ---------------------------------------------------------------------------

class App(ctk.CTk):
    """Root window of the YouTube Downloader."""

    def __init__(self) -> None:
        super().__init__()

        # --- Apply saved appearance settings ---
        ctk.set_appearance_mode(settings.get("theme", "dark"))
        ctk.set_default_color_theme(settings.get("color_theme", "blue"))

        self.title(APP_NAME)
        self.geometry("1100x720")
        self.minsize(900, 600)

        # Fix taskbar icon on Windows
        if os.name == "nt":
            try:
                import ctypes
                myappid = f"mycompany.ytdownloader.app.{APP_VERSION}"
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            except Exception as e:
                logger.warning(f"Could not set AppUserModelID: {e}")

        icon_path = get_resource_path("app_icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception as e:
                logger.warning(f"Could not load icon: {e}")

        # --- Download queue ---
        self._queue = DownloadQueue(
            max_workers=int(settings.get("max_simultaneous", 2)),
            progress_callback=self._on_task_progress,
        )

        # --- Pending UI updates from background threads ---
        self._pending_updates: dict[str, DownloadTask] = {}
        self._update_lock = threading.Lock()

        # --- Currently fetched video info ---
        self._current_info: Optional[VideoInfo] = None
        self._fetching = False

        # --- Queue row widgets keyed by task_id ---
        self._queue_rows: dict[str, QueueRow] = {}

        # --- Build layout ---
        self._build_layout()

        # --- Periodic UI refresh ---
        self.after(400, self._poll_updates)

    # ==================================================================
    # Layout construction
    # ==================================================================

    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar
        self._sidebar = ctk.CTkFrame(self, width=SIDEBAR_WIDTH, corner_radius=0, fg_color=("white", "gray17"))
        self._sidebar.grid(row=0, column=0, sticky="nsew")
        self._sidebar.grid_propagate(False)

        # Content area (swapped by navigation)
        self._content = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self._content.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        self._content.grid_rowconfigure(0, weight=1)
        self._content.grid_columnconfigure(0, weight=1)

        self._build_sidebar()
        self._pages: dict[str, ctk.CTkFrame] = {}
        self._build_home_page()
        self._build_queue_page()
        self._build_history_page()
        self._build_settings_page()
        self._build_about_page()

        self._show_page("home")

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------

    def _build_sidebar(self) -> None:
        sb = self._sidebar
        sb.grid_rowconfigure(6, weight=1)

        # Logo / app name
        logo_frame = ctk.CTkFrame(sb, fg_color="transparent")
        logo_frame.grid(row=0, column=0, padx=16, pady=(24, 8), sticky="ew")
        ctk.CTkLabel(
            logo_frame, text="▶ YT-DL",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=("black", "white"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            logo_frame, text=f"v{APP_VERSION}",
            font=ctk.CTkFont(size=11),
            text_color=("gray30", "gray55"),
        ).pack(anchor="w")

        ctk.CTkFrame(sb, height=1, fg_color=("gray80", "gray30")).grid(
            row=1, column=0, sticky="ew", padx=12, pady=4
        )

        nav_items = [
            ("🏠", "Home",     "home"),
            ("⬇", "Queue",    "queue"),
            ("📋", "History",  "history"),
            ("⚙", "Settings", "settings"),
            ("ℹ", "About",    "about"),
        ]
        self._nav_buttons: dict[str, SidebarButton] = {}
        for idx, (icon, label, page) in enumerate(nav_items):
            btn = SidebarButton(
                sb, text=label, icon=icon,
                command=lambda p=page: self._show_page(p),
            )
            btn.grid(row=idx + 2, column=0, padx=10, pady=4, sticky="ew")
            self._nav_buttons[page] = btn

        # Theme toggle at bottom
        ctk.CTkFrame(sb, height=1, fg_color=("gray80", "gray30")).grid(
            row=7, column=0, sticky="ew", padx=12, pady=4
        )
        ctk.CTkLabel(sb, text="Appearance", font=ctk.CTkFont(size=11),
                     text_color=("gray30", "gray55")).grid(
            row=8, column=0, sticky="w", padx=16)
        self._theme_menu = ctk.CTkOptionMenu(
            sb,
            values=THEME_OPTIONS,
            command=self._on_theme_change,
        )
        self._theme_menu.set(settings.get("theme", "dark"))
        self._theme_menu.grid(row=9, column=0, padx=10, pady=(2, 16), sticky="ew")

    # ------------------------------------------------------------------
    # Page management
    # ------------------------------------------------------------------

    def _show_page(self, name: str) -> None:
        for page_name, frame in self._pages.items():
            frame.grid_remove()
        if name in self._pages:
            self._pages[name].grid(row=0, column=0, sticky="nsew")
        # Highlight active nav button
        for page_name, btn in self._nav_buttons.items():
            if page_name == name:
                btn.configure(fg_color=("gray70", "gray30"))
            else:
                btn.configure(fg_color="transparent")

    # ==================================================================
    # HOME PAGE
    # ==================================================================

    def _build_home_page(self) -> None:
        page = ctk.CTkScrollableFrame(self._content, fg_color="transparent")
        page.grid_columnconfigure(0, weight=1)
        self._pages["home"] = page

        # ---- Section title ----
        SectionTitle(page, text="Download a Video").grid(
            row=0, column=0, sticky="w", padx=28, pady=(28, 4))

        # ---- URL input card ----
        url_card = Card(page)
        url_card.grid(row=1, column=0, sticky="ew", padx=20, pady=8)
        url_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(url_card, text="YouTube URL",
                     font=ctk.CTkFont(size=12)).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=16, pady=(14, 2))

        self._url_var = tk.StringVar()
        self._url_entry = ctk.CTkEntry(
            url_card, textvariable=self._url_var,
            placeholder_text="https://www.youtube.com/watch?v=...",
            height=44, font=ctk.CTkFont(size=13),
            corner_radius=10,
        )
        self._url_entry.grid(row=1, column=0, sticky="ew", padx=(16, 4), pady=8)
        self._url_entry.bind("<Return>", lambda _: self._fetch_info())

        # Paste button
        ctk.CTkButton(
            url_card, text="📋 Paste", width=90, height=44, corner_radius=10,
            command=self._paste_url,
        ).grid(row=1, column=1, padx=4, pady=8)

        # Fetch button
        self._fetch_btn = ctk.CTkButton(
            url_card, text="🔍 Fetch Info", width=110, height=44, corner_radius=10,
            command=self._fetch_info,
        )
        self._fetch_btn.grid(row=1, column=2, padx=(4, 16), pady=8)

        # ---- Info panel (hidden until info is fetched) ----
        self._info_card = Card(page)
        self._info_card.grid(row=2, column=0, sticky="ew", padx=20, pady=8)
        self._info_card.grid_columnconfigure(1, weight=1)
        self._info_card.grid_remove()   # hide initially

        # Thumbnail
        self._thumb_label_home = ctk.CTkLabel(self._info_card, text="", width=180, height=101)
        self._thumb_label_home.grid(row=0, column=0, rowspan=5, padx=(16, 12), pady=16, sticky="ns")

        # Metadata labels
        self._meta_title_var = tk.StringVar(value="")
        ctk.CTkLabel(self._info_card, textvariable=self._meta_title_var,
                     font=ctk.CTkFont(size=15, weight="bold"),
                     wraplength=480, anchor="w").grid(
            row=0, column=1, sticky="ew", padx=8, pady=(16, 2))

        self._meta_uploader_var = tk.StringVar(value="")
        ctk.CTkLabel(self._info_card, textvariable=self._meta_uploader_var,
                     font=ctk.CTkFont(size=12),
                     text_color=("gray50", "gray60"), anchor="w").grid(
            row=1, column=1, sticky="ew", padx=8)

        self._meta_duration_var = tk.StringVar(value="")
        ctk.CTkLabel(self._info_card, textvariable=self._meta_duration_var,
                     font=ctk.CTkFont(size=12), anchor="w").grid(
            row=2, column=1, sticky="ew", padx=8)

        self._meta_size_var = tk.StringVar(value="")
        ctk.CTkLabel(self._info_card, textvariable=self._meta_size_var,
                     font=ctk.CTkFont(size=12), anchor="w").grid(
            row=3, column=1, sticky="ew", padx=8)

        # Playlist label
        self._playlist_label_var = tk.StringVar(value="")
        ctk.CTkLabel(self._info_card, textvariable=self._playlist_label_var,
                     font=ctk.CTkFont(size=12),
                     text_color=("#E67E22", "#F39C12")).grid(
            row=4, column=1, sticky="ew", padx=8, pady=(0, 8))

        # ---- Download options card ----
        self._options_card = Card(page)
        self._options_card.grid(row=3, column=0, sticky="ew", padx=20, pady=8)
        self._options_card.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self._options_card.grid_remove()   # hide initially

        ctk.CTkLabel(self._options_card, text="Download Type",
                     font=ctk.CTkFont(size=12)).grid(
            row=0, column=0, sticky="w", padx=16, pady=(14, 2))
        self._type_var = tk.StringVar(value=settings.get("preferred_format", "Video+Audio"))
        self._type_menu = ctk.CTkOptionMenu(
            self._options_card, values=DOWNLOAD_TYPE_OPTIONS,
            variable=self._type_var, corner_radius=10,
        )
        self._type_menu.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 14))

        ctk.CTkLabel(self._options_card, text="Quality",
                     font=ctk.CTkFont(size=12)).grid(
            row=0, column=1, sticky="w", padx=16, pady=(14, 2))
        self._quality_var = tk.StringVar(value=settings.get("preferred_quality", "Best").capitalize())
        self._quality_menu = ctk.CTkOptionMenu(
            self._options_card, values=QUALITY_OPTIONS,
            variable=self._quality_var, corner_radius=10,
        )
        self._quality_menu.grid(row=1, column=1, sticky="ew", padx=16, pady=(0, 14))

        ctk.CTkLabel(self._options_card, text="Save to",
                     font=ctk.CTkFont(size=12)).grid(
            row=0, column=2, sticky="w", padx=16, pady=(14, 2))
        self._folder_var = tk.StringVar(value=settings.get("download_folder", str(Path.home() / "Downloads")))
        self._folder_entry = ctk.CTkEntry(
            self._options_card, textvariable=self._folder_var,
            corner_radius=10,
        )
        self._folder_entry.grid(row=1, column=2, sticky="ew", padx=(16, 4), pady=(0, 14))

        ctk.CTkButton(
            self._options_card, text="📂", width=40, corner_radius=10,
            command=self._choose_folder,
        ).grid(row=1, column=3, padx=(0, 16), pady=(0, 14), sticky="w")

        # Filename template row
        ctk.CTkLabel(self._options_card, text="Filename Template",
                     font=ctk.CTkFont(size=12)).grid(
            row=2, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 2))
        self._template_var = tk.StringVar(value=settings.get("output_template", "%(title)s.%(ext)s"))
        ctk.CTkEntry(
            self._options_card, textvariable=self._template_var, corner_radius=10,
        ).grid(row=3, column=0, columnspan=2, sticky="ew", padx=(16, 4), pady=(0, 14))

        ctk.CTkLabel(self._options_card, text="Cookies File (optional)",
                     font=ctk.CTkFont(size=12)).grid(
            row=2, column=2, columnspan=2, sticky="w", padx=16, pady=(0, 2))
        self._cookies_var = tk.StringVar(value=settings.get("cookies_file", ""))
        ctk.CTkEntry(
            self._options_card, textvariable=self._cookies_var,
            placeholder_text="Path to cookies.txt …", corner_radius=10,
        ).grid(row=3, column=2, sticky="ew", padx=(16, 4), pady=(0, 14))

        ctk.CTkButton(
            self._options_card, text="📂", width=40, corner_radius=10,
            command=self._choose_cookies,
        ).grid(row=3, column=3, padx=(0, 16), pady=(0, 14), sticky="w")

        # ---- Download button ----
        self._dl_btn = ctk.CTkButton(
            page, text="⬇  Add to Queue",
            height=52, corner_radius=12,
            font=ctk.CTkFont(size=16, weight="bold"),
            command=self._add_to_queue,
        )
        self._dl_btn.grid(row=5, column=0, sticky="ew", padx=20, pady=(8, 24))
        self._dl_btn.grid_remove()

        # ---- Status message ----
        self._status_var = tk.StringVar(value="")
        self._status_label = ctk.CTkLabel(
            page, textvariable=self._status_var,
            font=ctk.CTkFont(size=12),
            text_color=("gray50", "gray60"),
        )
        self._status_label.grid(row=6, column=0, sticky="w", padx=28, pady=(0, 8))

        # ---- Split download card (row 4, hidden initially) ----
        self._split_card = Card(page)
        self._split_card.grid(row=4, column=0, sticky="ew", padx=20, pady=4)
        self._split_card.grid_columnconfigure(0, weight=1)
        self._split_card.grid_remove()
        self._build_split_card(self._split_card)

    # ==================================================================
    # SPLIT DOWNLOAD CARD
    # ==================================================================

    def _build_split_card(self, parent: ctk.CTkFrame) -> None:
        """Build the split-download control panel."""
        # Header row: toggle + label
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 4))
        header.grid_columnconfigure(1, weight=1)

        self._split_enabled = tk.BooleanVar(value=False)
        ctk.CTkSwitch(
            header,
            text="",
            variable=self._split_enabled,
            onvalue=True, offvalue=False,
            command=self._on_split_toggle,
            width=46,
        ).grid(row=0, column=0, padx=(0, 8))

        ctk.CTkLabel(
            header,
            text="✂  Split into multiple parts",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=1, sticky="w")

        # Controls row (hidden when disabled)
        self._split_controls = ctk.CTkFrame(parent, fg_color="transparent")
        self._split_controls.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 4))
        self._split_controls.grid_columnconfigure(2, weight=1)
        self._split_controls.grid_remove()

        ctk.CTkLabel(
            self._split_controls,
            text="Number of parts:",
            font=ctk.CTkFont(size=12),
        ).grid(row=0, column=0, padx=(0, 8), pady=4)

        self._num_parts_var = tk.StringVar(value="2")
        parts_menu = ctk.CTkOptionMenu(
            self._split_controls,
            values=[str(n) for n in range(2, 11)],
            variable=self._num_parts_var,
            width=80,
            command=lambda _: self._refresh_split_table(),
        )
        parts_menu.grid(row=0, column=1, padx=(0, 16), pady=4)

        self._split_info_label = ctk.CTkLabel(
            self._split_controls,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=("gray50", "gray60"),
        )
        self._split_info_label.grid(row=0, column=2, sticky="w")

        # Table of parts
        self._split_table = ctk.CTkFrame(parent, fg_color="transparent")
        self._split_table.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 12))
        self._split_table.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self._split_table.grid_remove()

    def _on_split_toggle(self) -> None:
        """Show/hide the split controls when the toggle changes."""
        if self._split_enabled.get():
            self._split_controls.grid()
            self._split_table.grid()
            self._refresh_split_table()
        else:
            self._split_controls.grid_remove()
            self._split_table.grid_remove()

    def _refresh_split_table(self) -> None:
        """Rebuild the parts table based on current video duration and part count."""
        # Clear existing table rows
        for widget in self._split_table.winfo_children():
            widget.destroy()

        info = self._current_info
        if not info or not info.duration:
            self._split_info_label.configure(
                text="⚠ Duration unknown — parts will be estimated during download")
            return

        total_sec = info.duration
        n = int(self._num_parts_var.get())
        part_sec = total_sec / n

        self._split_info_label.configure(
            text=f"Total: {format_duration(total_sec)}  ·  Each part ≈ {format_duration(int(part_sec))}")

        # Column headers
        for col, text in enumerate(("Part", "Start", "End", "Duration")):
            ctk.CTkLabel(
                self._split_table, text=text,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=("gray50", "gray60"),
            ).grid(row=0, column=col, sticky="w", padx=8, pady=(4, 2))

        # One row per part
        for i in range(n):
            start = int(i * part_sec)
            end   = int((i + 1) * part_sec) if i < n - 1 else total_sec
            dur   = end - start

            bg = ("gray88", "gray22") if i % 2 == 0 else ("gray82", "gray18")
            for col, val in enumerate((
                f"Part {i + 1} of {n}",
                format_duration(start),
                format_duration(end),
                format_duration(dur),
            )):
                ctk.CTkLabel(
                    self._split_table, text=val,
                    font=ctk.CTkFont(size=12),
                    fg_color=bg, corner_radius=6,
                ).grid(row=i + 1, column=col, sticky="ew",
                       padx=4, pady=2, ipadx=6, ipady=4)

    # ==================================================================
    # QUEUE PAGE
    # ==================================================================

    def _build_queue_page(self) -> None:
        page = ctk.CTkFrame(self._content, fg_color="transparent")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        self._pages["queue"] = page

        header = ctk.CTkFrame(page, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(28, 4))
        header.grid_columnconfigure(0, weight=1)
        SectionTitle(header, text="Download Queue").grid(row=0, column=0, sticky="w")

        btn_row = ctk.CTkFrame(header, fg_color="transparent")
        btn_row.grid(row=0, column=1, sticky="e")

        ctk.CTkButton(
            btn_row, text="🗑 Clear Completed", corner_radius=10, height=36,
            command=self._clear_completed,
        ).pack(side="left", padx=4)

        self._queue_scroll = ctk.CTkScrollableFrame(page, fg_color="transparent")
        self._queue_scroll.grid(row=1, column=0, sticky="nsew", padx=12, pady=8)
        self._queue_scroll.grid_columnconfigure(0, weight=1)

        self._queue_empty_label = ctk.CTkLabel(
            self._queue_scroll,
            text="No downloads in queue.\nGo to Home and add a video!",
            font=ctk.CTkFont(size=14),
            text_color=("gray55", "gray55"),
        )
        self._queue_empty_label.grid(row=0, column=0, pady=60)

    # ==================================================================
    # HISTORY PAGE
    # ==================================================================

    def _build_history_page(self) -> None:
        page = ctk.CTkFrame(self._content, fg_color="transparent")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        self._pages["history"] = page

        header = ctk.CTkFrame(page, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(28, 4))
        header.grid_columnconfigure(0, weight=1)
        SectionTitle(header, text="Download History").grid(row=0, column=0, sticky="w")
        
        btn_row = ctk.CTkFrame(header, fg_color="transparent")
        btn_row.grid(row=0, column=1, sticky="e")

        ctk.CTkButton(
            btn_row, text="🗑 Clear All", corner_radius=10, height=36,
            command=self._clear_all_history,
            fg_color=("#C0392B", "#922B21"),
            hover_color=("#A93226", "#7B241C"),
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            btn_row, text="🔄 Refresh", corner_radius=10, height=36,
            command=self._refresh_history,
        ).pack(side="left", padx=4)

        self._history_scroll = ctk.CTkScrollableFrame(page, fg_color="transparent")
        self._history_scroll.grid(row=1, column=0, sticky="nsew", padx=12, pady=8)
        self._history_scroll.grid_columnconfigure(0, weight=1)

        self._refresh_history()

    def _refresh_history(self) -> None:
        for widget in self._history_scroll.winfo_children():
            widget.destroy()

        entries = load_history()
        if not entries:
            ctk.CTkLabel(
                self._history_scroll,
                text="No download history yet.",
                font=ctk.CTkFont(size=14),
                text_color=("gray55", "gray55"),
            ).grid(row=0, column=0, pady=60)
            return

        for idx, entry in enumerate(reversed(entries)):
            self._build_history_row(idx, entry)

    def _build_history_row(self, idx: int, entry: dict) -> None:
        row = Card(self._history_scroll)
        row.grid(row=idx, column=0, sticky="ew", padx=4, pady=4)
        row.grid_columnconfigure(1, weight=1)

        # Status icon
        ctk.CTkLabel(row, text="✅", font=ctk.CTkFont(size=20)).grid(
            row=0, column=0, rowspan=2, padx=12, pady=10)

        title = entry.get("title", "Unknown")
        ts = entry.get("timestamp", "")
        uploader = entry.get("uploader", "")
        dl_type = entry.get("download_type", "")
        quality = entry.get("quality", "")

        ctk.CTkLabel(row, text=title, font=ctk.CTkFont(size=13, weight="bold"),
                     anchor="w", wraplength=420).grid(
            row=0, column=1, sticky="ew", padx=8, pady=(8, 0))
        ctk.CTkLabel(
            row,
            text=f"{uploader}  ·  {dl_type}  ·  {quality}  ·  {ts}",
            font=ctk.CTkFont(size=11),
            text_color=("gray50", "gray60"), anchor="w",
        ).grid(row=1, column=1, sticky="ew", padx=8, pady=(0, 8))

        btn_frame = ctk.CTkFrame(row, fg_color="transparent")
        btn_frame.grid(row=0, column=2, rowspan=2, padx=8)

        output_file = entry.get("output_file", "")
        output_folder = entry.get("output_folder", "")

        ctk.CTkButton(
            btn_frame, text="📄 Open File", width=100, height=32, corner_radius=8,
            command=lambda f=output_file: open_file(f),
            state="normal" if output_file and os.path.isfile(output_file) else "disabled",
        ).pack(pady=2)

        ctk.CTkButton(
            btn_frame, text="📂 Folder", width=100, height=32, corner_radius=8,
            command=lambda f=output_folder: open_in_file_manager(f),
        ).pack(pady=2)

        ctk.CTkButton(
            btn_frame, text="🗑 Remove", width=100, height=32, corner_radius=8,
            fg_color=("#C0392B", "#922B21"),
            hover_color=("#A93226", "#7B241C"),
            command=lambda e=entry: self._remove_history_item(e),
        ).pack(pady=2)

    def _clear_all_history(self) -> None:
        if messagebox.askyesno("Clear History", "Are you sure you want to clear all download history?"):
            save_history([])
            self._refresh_history()

    def _remove_history_item(self, entry_to_remove: dict) -> None:
        entries = load_history()
        if entry_to_remove in entries:
            entries.remove(entry_to_remove)
            save_history(entries)
            self._refresh_history()

    # ==================================================================
    # SETTINGS PAGE
    # ==================================================================

    def _build_settings_page(self) -> None:
        page = ctk.CTkScrollableFrame(self._content, fg_color="transparent")
        page.grid_columnconfigure(0, weight=1)
        self._pages["settings"] = page

        SectionTitle(page, text="Settings").grid(
            row=0, column=0, sticky="w", padx=28, pady=(28, 12))

        # ---------- Download settings card ----------
        dl_card = Card(page)
        dl_card.grid(row=1, column=0, sticky="ew", padx=20, pady=8)
        dl_card.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(dl_card, text="Default Download Folder",
                     font=ctk.CTkFont(size=12)).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 2))
        self._s_folder_var = tk.StringVar(value=settings.get("download_folder"))
        ctk.CTkEntry(dl_card, textvariable=self._s_folder_var, corner_radius=10).grid(
            row=1, column=0, sticky="ew", padx=(16, 4), pady=(0, 14))
        ctk.CTkButton(
            dl_card, text="📂", width=40, corner_radius=10,
            command=lambda: self._choose_folder_setting(self._s_folder_var),
        ).grid(row=1, column=1, sticky="w", padx=(0, 16), pady=(0, 14))

        # Preferred quality
        ctk.CTkLabel(dl_card, text="Preferred Quality",
                     font=ctk.CTkFont(size=12)).grid(
            row=2, column=0, sticky="w", padx=16, pady=(0, 2))
        self._s_quality_var = tk.StringVar(value=settings.get("preferred_quality", "best").capitalize())
        ctk.CTkOptionMenu(dl_card, values=QUALITY_OPTIONS,
                          variable=self._s_quality_var, corner_radius=10).grid(
            row=3, column=0, sticky="ew", padx=16, pady=(0, 14))

        # Preferred format
        ctk.CTkLabel(dl_card, text="Preferred Format",
                     font=ctk.CTkFont(size=12)).grid(
            row=2, column=1, sticky="w", padx=16, pady=(0, 2))
        self._s_format_var = tk.StringVar(value=settings.get("preferred_format", "Video+Audio"))
        ctk.CTkOptionMenu(dl_card, values=DOWNLOAD_TYPE_OPTIONS,
                          variable=self._s_format_var, corner_radius=10).grid(
            row=3, column=1, sticky="ew", padx=16, pady=(0, 14))

        # Audio format
        ctk.CTkLabel(dl_card, text="Audio Format (when Audio Only)",
                     font=ctk.CTkFont(size=12)).grid(
            row=4, column=0, sticky="w", padx=16, pady=(0, 2))
        self._s_audio_var = tk.StringVar(value=settings.get("audio_format", "mp3"))
        ctk.CTkOptionMenu(dl_card, values=AUDIO_FORMAT_OPTIONS,
                          variable=self._s_audio_var, corner_radius=10).grid(
            row=5, column=0, sticky="ew", padx=16, pady=(0, 14))

        # Max simultaneous downloads
        ctk.CTkLabel(dl_card, text="Max Simultaneous Downloads",
                     font=ctk.CTkFont(size=12)).grid(
            row=4, column=1, sticky="w", padx=16, pady=(0, 2))
        self._s_workers_var = tk.StringVar(value=str(settings.get("max_simultaneous", 2)))
        ctk.CTkOptionMenu(dl_card, values=MAX_WORKERS_OPTIONS,
                          variable=self._s_workers_var, corner_radius=10).grid(
            row=5, column=1, sticky="ew", padx=16, pady=(0, 14))

        # ---------- Appearance card ----------
        app_card = Card(page)
        app_card.grid(row=2, column=0, sticky="ew", padx=20, pady=8)
        app_card.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(app_card, text="Appearance",
                     font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 4))

        ctk.CTkLabel(app_card, text="Theme", font=ctk.CTkFont(size=12)).grid(
            row=1, column=0, sticky="w", padx=16, pady=(0, 2))
        self._s_theme_var = tk.StringVar(value=settings.get("theme", "dark"))
        ctk.CTkOptionMenu(app_card, values=THEME_OPTIONS,
                          variable=self._s_theme_var, corner_radius=10,
                          command=self._on_theme_change).grid(
            row=2, column=0, sticky="ew", padx=16, pady=(0, 14))

        ctk.CTkLabel(app_card, text="Color Theme", font=ctk.CTkFont(size=12)).grid(
            row=1, column=1, sticky="w", padx=16, pady=(0, 2))
        self._s_color_var = tk.StringVar(value=settings.get("color_theme", "blue"))
        ctk.CTkOptionMenu(app_card, values=COLOR_THEME_OPTIONS,
                          variable=self._s_color_var, corner_radius=10).grid(
            row=2, column=1, sticky="ew", padx=16, pady=(0, 14))

        # ---------- Save button ----------
        ctk.CTkButton(
            page, text="💾 Save Settings",
            height=48, corner_radius=12,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._save_settings,
        ).grid(row=3, column=0, sticky="ew", padx=20, pady=(8, 24))

    # ==================================================================
    # ABOUT PAGE
    # ==================================================================

    def _build_about_page(self) -> None:
        page = ctk.CTkFrame(self._content, fg_color="transparent")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(0, weight=1)
        self._pages["about"] = page

        center = ctk.CTkFrame(page, fg_color="transparent")
        center.place(relx=0.5, rely=0.45, anchor="center")

        ctk.CTkLabel(center, text="▶ YT Downloader",
                     font=ctk.CTkFont(size=32, weight="bold")).pack(pady=(0, 4))
        ctk.CTkLabel(center, text=f"Version {APP_VERSION}",
                     font=ctk.CTkFont(size=14),
                     text_color=("gray55", "gray55")).pack(pady=(0, 16))

        ctk.CTkLabel(
            center,
            text=(
                "A modern, feature-rich YouTube downloader\n"
                "powered by yt-dlp and CustomTkinter.\n\n"
                "Supports Video+Audio, Video Only, and Audio Only downloads.\n"
                "Queue multiple videos, track progress in real-time,\n"
                "and manage your download history — all in one place."
            ),
            font=ctk.CTkFont(size=13),
            justify="center",
        ).pack(pady=(0, 24))

        ctk.CTkLabel(center, text="Dependencies",
                     font=ctk.CTkFont(size=14, weight="bold")).pack()
        for dep in ["yt-dlp", "CustomTkinter", "Pillow", "FFmpeg (external)"]:
            ctk.CTkLabel(center, text=f"• {dep}",
                         font=ctk.CTkFont(size=12)).pack()

    # ==================================================================
    # Event handlers
    # ==================================================================

    def _paste_url(self) -> None:
        try:
            text = self.clipboard_get()
            self._url_var.set(text.strip())
        except tk.TclError:
            pass

    def _fetch_info(self) -> None:
        if self._fetching:
            return
        url = normalize_url(self._url_var.get())
        if not url:
            self._set_status("⚠ Please enter a URL.", error=True)
            return
        if not is_valid_youtube_url(url):
            self._set_status("⚠ That doesn't look like a valid YouTube URL.", error=True)
            return

        self._fetching = True
        self._fetch_btn.configure(state="disabled", text="⏳ Fetching…")
        self._set_status("Fetching video information…")
        self._info_card.grid_remove()
        self._options_card.grid_remove()
        self._dl_btn.grid_remove()
        self._current_info = None

        threading.Thread(
            target=self._fetch_info_thread,
            args=(url,),
            daemon=True,
        ).start()

    def _fetch_info_thread(self, url: str) -> None:
        try:
            cookies = self._cookies_var.get() if hasattr(self, "_cookies_var") else ""
            info = fetch_video_info(url, cookies_file=cookies)
            self.after(0, self._on_info_fetched, info)
        except Exception as exc:
            logger.error("Info fetch error: %s", exc)
            self.after(0, self._on_info_error, str(exc))

    def _on_info_fetched(self, info: VideoInfo) -> None:
        self._fetching = False
        self._fetch_btn.configure(state="normal", text="🔍 Fetch Info")
        self._current_info = info

        # Populate metadata card
        self._meta_title_var.set(info.title)
        self._meta_uploader_var.set(f"👤 {info.uploader}")
        self._meta_duration_var.set(f"⏱ {format_duration(info.duration)}")
        self._meta_size_var.set(f"💾 {format_filesize(info.filesize)}")

        if info.is_playlist:
            count = len(info.playlist_entries)
            self._playlist_label_var.set(f"📃 Playlist detected — {count} videos")
        else:
            self._playlist_label_var.set("")

        # Populate quality dropdown with available resolutions
        if info.formats:
            res_labels = [f["label"] for f in info.formats]
            unique = list(dict.fromkeys(["Best"] + res_labels))
            self._quality_menu.configure(values=unique)

        self._info_card.grid()
        self._options_card.grid()
        self._dl_btn.grid()
        self._set_status("✅ Ready to download.")

        # Show split card (only for single videos, not playlists)
        if not info.is_playlist:
            self._split_card.grid()
            # Reset split toggle to off when a new video is fetched
            self._split_enabled.set(False)
            self._split_controls.grid_remove()
            self._split_table.grid_remove()
        else:
            self._split_card.grid_remove()

        # Load thumbnail in background
        if info.thumbnail_url:
            threading.Thread(
                target=self._load_home_thumb,
                args=(info.thumbnail_url,),
                daemon=True,
            ).start()

    def _on_info_error(self, msg: str) -> None:
        self._fetching = False
        self._fetch_btn.configure(state="normal", text="🔍 Fetch Info")
        self._set_status(f"❌ Error: {msg}", error=True)
        # Also show a clear popup so the user can't miss it
        friendly = self._friendly_error(msg)
        messagebox.showerror(
            "Could Not Fetch Video Info",
            friendly,
        )

    @staticmethod
    def _friendly_error(raw: str) -> str:
        """Convert a raw exception message into a plain-English explanation."""
        r = raw.lower()
        if "ffmpeg" in r:
            return (
                "FFmpeg was not found.\n\n"
                "If running from source: place ffmpeg.exe in the project folder.\n"
                "If running the .exe: re-download it — the bundled FFmpeg may be missing."
            )
        if "video unavailable" in r or "private video" in r:
            return "This video is unavailable or private. Please check the URL and try again."
        if "sign in" in r or "age" in r or "login" in r:
            return (
                "This video requires sign-in or is age-restricted.\n\n"
                "Fix: Go to Settings and provide a cookies file from your browser."
            )
        if "copyright" in r or "blocked" in r:
            return "This video is blocked or restricted in your region."
        if "urlopen error" in r or "getaddrinfo" in r or "connection" in r:
            return (
                "Could not connect to YouTube.\n\n"
                "Please check your internet connection and try again."
            )
        if "no such format" in r or "requested format" in r:
            return (
                "The selected video quality is not available for this video.\n\n"
                "Try choosing a lower quality (e.g. 720p or 480p)."
            )
        if "winError 5" in raw or "access is denied" in r:
            return (
                "Access Denied.\n\n"
                "Try running the application as Administrator, "
                "or choose a different download folder in Settings."
            )
        if "no space" in r or "disk" in r:
            return "Not enough disk space. Please free up space and try again."
        # Generic fallback
        return f"An error occurred:\n\n{raw}"

    def _load_home_thumb(self, url: str) -> None:
        img = _load_thumbnail(url, (180, 101))
        if img:
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(180, 101))
            self.after(0, self._thumb_label_home.configure, {"image": ctk_img})

    def _set_status(self, text: str, error: bool = False) -> None:
        self._status_var.set(text)
        color = ("#C0392B", "#E74C3C") if error else ("gray50", "gray60")
        self._status_label.configure(text_color=color)

    def _choose_folder(self) -> None:
        folder = filedialog.askdirectory(initialdir=self._folder_var.get())
        if folder:
            self._folder_var.set(folder)
            if settings.get("remember_folder"):
                settings.set("download_folder", folder)
                settings.save()

    def _choose_cookies(self) -> None:
        path = filedialog.askopenfilename(
            title="Select cookies.txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            self._cookies_var.set(path)

    def _add_to_queue(self) -> None:
        if not self._current_info:
            self._set_status("⚠ Please fetch video info first.", error=True)
            return

        info = self._current_info
        url = normalize_url(self._url_var.get())
        download_type = self._type_var.get()
        quality = self._quality_var.get().lower()
        folder = self._folder_var.get()
        template = self._template_var.get()
        cookies = self._cookies_var.get()

        if not folder:
            self._set_status("⚠ Please select a download folder.", error=True)
            return

        # ── Playlist ────────────────────────────────────────────────────
        if info.is_playlist:
            count = len(info.playlist_entries)
            answer = messagebox.askyesno(
                "Playlist Detected",
                f'"{info.title}" is a playlist with {count} videos.\n\n'
                "Download all videos?",
            )
            if answer:
                for entry in info.playlist_entries:
                    task = self._make_task(
                        url=entry.get("url", ""),
                        title=entry.get("title", "Unknown"),
                        download_type=download_type,
                        quality=quality,
                        folder=folder,
                        template=template,
                        cookies=cookies,
                        thumbnail_url=entry.get("thumbnail", ""),
                        duration=entry.get("duration"),
                        uploader=info.uploader,
                    )
                    self._add_task_to_ui(task)
            return

        # ── Split download ───────────────────────────────────────────────
        if self._split_enabled.get() and info.duration:
            n = int(self._num_parts_var.get())
            total_sec = info.duration
            part_sec = total_sec / n

            for i in range(n):
                start = int(i * part_sec)
                end   = int((i + 1) * part_sec) if i < n - 1 else total_sec
                part_title = f"{info.title} — Part {i + 1} of {n}"

                task = self._make_task(
                    url=url,
                    title=info.title,
                    download_type=download_type,
                    quality=quality,
                    folder=folder,
                    template=template,
                    cookies=cookies,
                    thumbnail_url=info.thumbnail_url or "",
                    duration=end - start,
                    uploader=info.uploader,
                    start_time=start,
                    end_time=end,
                    part_number=i + 1,
                    total_parts=n,
                    display_title=part_title,
                )
                self._add_task_to_ui(task)

            self._set_status(
                f'✅ Added "{info.title}" as {n} parts to the queue.')
            return

        # ── Single download ──────────────────────────────────────────────
        task = self._make_task(
            url=url,
            title=info.title,
            download_type=download_type,
            quality=quality,
            folder=folder,
            template=template,
            cookies=cookies,
            thumbnail_url=info.thumbnail_url or "",
            duration=info.duration,
            uploader=info.uploader,
        )
        self._add_task_to_ui(task)
        self._set_status(f'✅ Added "{info.title}" to the queue.')

    def _make_task(
        self, url: str, title: str, download_type: str, quality: str,
        folder: str, template: str, cookies: str,
        thumbnail_url: str, duration: Optional[int], uploader: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        part_number: int = 0,
        total_parts: int = 0,
        display_title: str = "",
    ) -> DownloadTask:
        task_id = self._queue.next_task_id()
        return DownloadTask(
            task_id=task_id,
            url=url,
            title=display_title or title,
            download_type=download_type,
            quality=quality,
            output_folder=folder,
            output_template=template,
            cookies_file=cookies,
            thumbnail_url=thumbnail_url,
            duration=duration,
            uploader=uploader,
            start_time=start_time,
            end_time=end_time,
            part_number=part_number,
            total_parts=total_parts,
        )

    def _add_task_to_ui(self, task: DownloadTask) -> None:
        self._queue.add_task(task)
        self._add_queue_row(task)
        self._show_page("queue")

    def _add_queue_row(self, task: DownloadTask) -> None:
        # Remove "empty" label
        self._queue_empty_label.grid_remove()

        row_idx = len(self._queue_rows)
        row = QueueRow(self._queue_scroll, task, self._queue)
        row.grid(row=row_idx, column=0, sticky="ew", padx=4, pady=4)
        self._queue_rows[task.task_id] = row

    def _clear_completed(self) -> None:
        self._queue.clear_completed()
        # Remove completed rows from UI
        to_remove = []
        for task_id, row in self._queue_rows.items():
            if row.task.status in (
                DownloadStatus.COMPLETED,
                DownloadStatus.CANCELLED,
                DownloadStatus.ERROR,
            ):
                row.destroy()
                to_remove.append(task_id)
        for tid in to_remove:
            del self._queue_rows[tid]

        # Re-grid remaining rows
        for idx, row in enumerate(self._queue_rows.values()):
            row.grid(row=idx, column=0, sticky="ew", padx=4, pady=4)

        if not self._queue_rows:
            self._queue_empty_label.grid(row=0, column=0, pady=60)

    # ------------------------------------------------------------------
    # Settings handlers
    # ------------------------------------------------------------------

    def _choose_folder_setting(self, var: tk.StringVar) -> None:
        folder = filedialog.askdirectory(initialdir=var.get())
        if folder:
            var.set(folder)

    def _save_settings(self) -> None:
        settings.update(
            {
                "download_folder": self._s_folder_var.get(),
                "preferred_quality": self._s_quality_var.get().lower(),
                "preferred_format": self._s_format_var.get(),
                "audio_format": self._s_audio_var.get(),
                "max_simultaneous": int(self._s_workers_var.get()),
                "theme": self._s_theme_var.get(),
                "color_theme": self._s_color_var.get(),
            }
        )
        settings.save()
        self._queue.update_max_workers(int(self._s_workers_var.get()))
        messagebox.showinfo("Settings", "Settings saved successfully.")

    def _on_theme_change(self, value: str) -> None:
        ctk.set_appearance_mode(value)
        settings.set("theme", value)
        settings.save()
        # Keep sidebar theme menu in sync
        if hasattr(self, "_theme_menu"):
            self._theme_menu.set(value)

    # ==================================================================
    # Progress & polling
    # ==================================================================

    def _on_task_progress(self, task: DownloadTask) -> None:
        """Called from background thread; just store the update."""
        with self._update_lock:
            self._pending_updates[task.task_id] = task

    def _poll_updates(self) -> None:
        """Scheduled in the main thread every 400 ms to apply UI updates."""
        with self._update_lock:
            updates = dict(self._pending_updates)
            self._pending_updates.clear()

        for task_id, task in updates.items():
            row = self._queue_rows.get(task_id)
            if row:
                row.update_ui()
                # Show popup when a download finishes with an error
                if task.status == DownloadStatus.ERROR and task.error_message:
                    friendly = self._friendly_error(task.error_message)
                    messagebox.showerror(
                        f"Download Failed — {task.title[:50]}",
                        friendly,
                    )
                    # Clear error_message so the popup doesn't fire again on next poll
                    task.error_message = ""

        self.after(400, self._poll_updates)
