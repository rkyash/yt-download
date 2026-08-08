"""
main.py
-------
Entry point for the YouTube Downloader application.

Run with:
    python main.py
"""

import logging
import os
import sys
import traceback

# ---------------------------------------------------------------------------
# Log file setup  (works for both script and PyInstaller .exe)
# ---------------------------------------------------------------------------

LOG_DIR = os.path.join(os.path.expanduser("~"), "AppData", "Local", "YTDownloader")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "error.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),   # always log to file
    ],
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Global uncaught exception handler
# ---------------------------------------------------------------------------

def _show_fatal_error(exc_type, exc_value, exc_tb) -> None:
    """
    Called for any unhandled exception.  Shows a popup with the error so
    the user is never left staring at a silently-closed window.
    """
    error_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logger.critical("UNHANDLED EXCEPTION:\n%s", error_text)

    # Build a friendly, human-readable message
    short_msg = str(exc_value)

    # Map common technical errors to plain-English explanations
    friendly: dict[str, str] = {
        "ffmpeg": (
            "FFmpeg was not found.\n"
            "If you are running from source, place ffmpeg.exe in the project folder.\n"
            "If you are running the .exe, please re-download it — the bundled FFmpeg may be missing."
        ),
        "No module named": (
            f"A required Python module is missing: {short_msg}\n"
            "Try reinstalling the application."
        ),
        "DownloadError": (
            f"Download failed:\n{short_msg}\n\n"
            "Possible causes:\n"
            "  • The video is private or region-locked\n"
            "  • No internet connection\n"
            "  • The YouTube URL is invalid"
        ),
        "WinError 5": (
            "Access Denied (WinError 5).\n"
            "Try running the application as Administrator, or choose a different download folder."
        ),
        "WinError 2": (
            "A required file was not found (WinError 2).\n"
            "Ensure ffmpeg.exe is present and the application folder has not been moved."
        ),
    }

    popup_msg = None
    for keyword, friendly_text in friendly.items():
        if keyword.lower() in short_msg.lower() or keyword.lower() in error_text.lower():
            popup_msg = friendly_text
            break

    if popup_msg is None:
        popup_msg = (
            f"An unexpected error occurred:\n\n{short_msg}\n\n"
            f"The full error has been saved to:\n{LOG_FILE}"
        )
    else:
        popup_msg += f"\n\nFull error log saved to:\n{LOG_FILE}"

    # Show the popup (tkinter must be available even on crash)
    try:
        import tkinter as tk
        import tkinter.messagebox as messagebox
        root = tk.Tk()
        root.withdraw()  # hide the blank root window
        messagebox.showerror("YT Downloader — Error", popup_msg)
        root.destroy()
    except Exception:
        # Last resort: if even tkinter fails, at least the log file has everything
        pass


sys.excepthook = _show_fatal_error


# ---------------------------------------------------------------------------
# Application entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Create and launch the application window."""
    logger.info("Starting YT Downloader …")
    logger.info("Log file: %s", LOG_FILE)

    try:
        # Lazy import so logging is configured before modules load
        from gui import App
        app = App()
        app.mainloop()
    except Exception as exc:
        _show_fatal_error(type(exc), exc, exc.__traceback__)
        sys.exit(1)

    logger.info("YT Downloader closed.")


if __name__ == "__main__":
    main()
