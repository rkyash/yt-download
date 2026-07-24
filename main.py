"""
main.py
-------
Entry point for the YouTube Downloader application.

Run with:
    python main.py
"""

import logging
import sys

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger(__name__)


def main() -> None:
    """Create and launch the application window."""
    logger.info("Starting YT Downloader …")

    # Lazy import so logging is configured before modules load
    from gui import App

    app = App()
    app.mainloop()

    logger.info("YT Downloader closed.")


if __name__ == "__main__":
    main()
