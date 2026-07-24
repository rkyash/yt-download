"""
settings.py
-----------
Persistent application settings stored as a JSON file in the user's
home directory (~/.yt_downloader/settings.json).

Provides get/set helpers and safe load/save with graceful fallback to defaults.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Location of the settings file
APP_DIR = Path.home() / ".yt_downloader"
SETTINGS_FILE = APP_DIR / "settings.json"

# History file alongside settings
HISTORY_FILE = APP_DIR / "history.json"

# Default values for every setting key
DEFAULTS: dict[str, Any] = {
    # Paths
    "download_folder": str(Path.home() / "Downloads"),
    # Appearance
    "theme": "dark",          # "dark" | "light" | "system"
    "color_theme": "blue",    # customtkinter color-theme name
    # Download preferences
    "preferred_quality": "best",      # "best" | "1080p" | "720p" | "480p" | "360p" | "240p"
    "preferred_format": "Video+Audio", # "Video+Audio" | "Video Only" | "Audio Only"
    "audio_format": "mp3",            # "mp3" | "m4a" | "aac" | "opus"
    "max_simultaneous": 2,
    # Output template
    "output_template": "%(title)s.%(ext)s",
    # Cookies
    "cookies_file": "",
    # Misc
    "auto_updates": False,
    "remember_folder": True,
    "open_after_download": False,
}


class Settings:
    """
    Singleton-like settings manager.

    Usage::

        from settings import settings
        settings.get("theme")          # -> "dark"
        settings.set("theme", "light")
        settings.save()
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = dict(DEFAULTS)
        APP_DIR.mkdir(parents=True, exist_ok=True)
        self.load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: str, fallback: Any = None) -> Any:
        """Return the setting value for *key*, or *fallback* if not found."""
        return self._data.get(key, DEFAULTS.get(key, fallback))

    def set(self, key: str, value: Any) -> None:
        """Update a setting in memory. Call :meth:`save` to persist."""
        self._data[key] = value

    def update(self, mapping: dict[str, Any]) -> None:
        """Bulk-update settings from a dictionary."""
        for key, value in mapping.items():
            self._data[key] = value

    def save(self) -> None:
        """Persist current settings to disk."""
        try:
            SETTINGS_FILE.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.error("Failed to save settings: %s", exc)

    def load(self) -> None:
        """Load settings from disk, merging with defaults for missing keys."""
        if not SETTINGS_FILE.exists():
            return
        try:
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                # Merge: keep defaults for keys absent in the file
                for key, default_val in DEFAULTS.items():
                    self._data[key] = raw.get(key, default_val)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not load settings (%s); using defaults.", exc)

    def reset(self) -> None:
        """Reset all settings to defaults and save."""
        self._data = dict(DEFAULTS)
        self.save()


# ---------------------------------------------------------------------------
# History helpers
# ---------------------------------------------------------------------------

MAX_HISTORY_ENTRIES = 200


def load_history() -> list[dict]:
    """Load download history from disk. Returns a list of entry dicts."""
    if not HISTORY_FILE.exists():
        return []
    try:
        raw = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return raw
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not load history: %s", exc)
    return []


def save_history(entries: list[dict]) -> None:
    """Persist download history to disk (trimmed to MAX_HISTORY_ENTRIES)."""
    trimmed = entries[-MAX_HISTORY_ENTRIES:]
    try:
        HISTORY_FILE.write_text(json.dumps(trimmed, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.error("Failed to save history: %s", exc)


def append_history(entry: dict) -> None:
    """Append a single entry to the persistent history file."""
    entries = load_history()
    entries.append(entry)
    save_history(entries)


# Module-level singleton – import this from other modules
settings = Settings()
