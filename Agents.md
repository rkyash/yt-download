Build a modern Python desktop application that downloads YouTube videos from a user-provided URL.

Requirements:

- Use Python 3.12+.
- Create a clean and modern GUI using CustomTkinter (preferred) or Tkinter.
- Use yt-dlp as the download backend.
- The application should allow users to:
  - Enter a YouTube video URL.
  - Validate the URL before downloading.
  - Fetch and display the video title, thumbnail, duration, uploader, and available resolutions.
  - Choose the download type:
    - Video + Audio
    - Video Only
    - Audio Only
  - Select the video quality (Best, 1080p, 720p, 480p, 360p, etc.).
  - Choose the download folder using a folder picker.
  - Start, pause (if supported), and cancel downloads.
  - Download multiple videos using a queue.
  - Optionally download playlists with a confirmation prompt.

The application should display:

- Video thumbnail
- Video title
- Channel name
- Duration
- File size (if available)
- Resolution
- Progress bar
- Download percentage
- Download speed
- ETA (estimated time remaining)
- Current download status

Additional Features:

- Dark and Light mode toggle.
- Responsive interface that never freezes during downloads.
- Background downloading using threading or asyncio.
- Clipboard paste button for YouTube URLs.
- Drag-and-drop support for YouTube links.
- Open downloaded file button.
- Open download folder button.
- Download history.
- Remember the last selected download folder.
- Automatically sanitize filenames.
- Prevent duplicate downloads.
- Display meaningful success and error messages.
- Retry failed downloads.
- Support age-restricted videos when cookies are provided.
- Allow users to specify custom output filename templates.

Technical Requirements:

- Use Python 3.12+.
- Use yt-dlp as the backend.
- Use FFmpeg automatically when available for merging video and audio.
- Organize the project into multiple files:
  - main.py
  - gui.py
  - downloader.py
  - utils.py
  - settings.py
  - requirements.txt
- Follow Object-Oriented Programming (OOP).
- Follow PEP 8 coding standards.
- Use logging instead of print statements.
- Add clear comments explaining important sections.
- Handle all exceptions gracefully.
- Use type hints where appropriate.

GUI Requirements:

- Modern rounded UI using CustomTkinter.
- Sidebar navigation.
- Large URL input box.
- Download button.
- Resolution dropdown.
- Download type dropdown.
- Folder selection button.
- Thumbnail preview.
- Download progress section.
- Download history tab.
- Settings tab.
- About tab.

Settings:

- Default download location.
- Theme selection.
- Preferred download quality.
- Preferred download format.
- Maximum simultaneous downloads.
- Enable automatic updates (placeholder).

Output Requirements:

- Generate complete, production-ready source code.
- Do not omit any code.
- Do not use placeholders.
- Include every required file with full implementations.
- Generate requirements.txt.
- Provide installation instructions.
- Explain how to install FFmpeg.
- Explain how to package the application into a standalone Windows executable using PyInstaller.
- Ensure the application runs on Windows 10 and Windows 11.
- Make the code clean, modular, well-documented, and easy to maintain.
