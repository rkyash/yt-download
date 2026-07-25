# ▶ YT Downloader

A modern, feature-rich YouTube video/audio downloader with a sleek CustomTkinter GUI.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## ✨ Features

| Feature | Details |
|---|---|
| **Video + Audio / Video Only / Audio Only** | Selectable per download |
| **Quality selector** | Best, 1080p, 720p, 480p, 360p, 240p |
| **Playlist support** | Confirmation prompt, queues all entries |
| **Download queue** | Multiple simultaneous downloads |
| **Real-time progress** | Progress bar, speed, ETA, status |
| **Thumbnail preview** | Shown on info fetch and in queue rows |
| **Pause / Resume / Cancel** | Per-task controls |
| **Retry failed downloads** | Automatic up to 3 retries |
| **Download history** | Persistent, viewable in the History tab |
| **Dark / Light / System theme** | Toggle in sidebar or Settings |
| **Clipboard paste** | One-click URL paste |
| **Custom filename template** | `%(title)s`, `%(uploader)s`, `%(id)s`, etc. |
| **Cookie support** | For age-restricted videos |
| **Open file / folder** | Buttons in history and queue rows |
| **Settings persistence** | JSON file in `~/.yt_downloader/` |
| **Filename sanitization** | Safe names on all platforms |
| **Duplicate prevention** | Checks existing files before downloading |

---

## 🗂 Project Structure

```
yt-download/
├── main.py          # Entry point
├── gui.py           # CustomTkinter UI
├── downloader.py    # yt-dlp wrapper + queue manager
├── settings.py      # JSON settings & history persistence
├── utils.py         # URL validation, formatting, helpers
├── requirements.txt
└── README.md
```

---

## 🚀 Installation

### 1. Clone / Download

```bash
git clone <repo-url>
cd yt-download
```

### 2. Setup & Install Dependencies

You can set up the project using either `pip` or `uv` (recommended for faster dependency resolution).

#### Option A: Using `pip`

Create and activate a virtual environment:
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
```

Install dependencies:
```bash
pip install -r requirements.txt
```

#### Option B: Using `uv`

If you have [uv](https://docs.astral.sh/uv/) installed, you can simply sync the dependencies:
```bash
uv sync
```
*This automatically creates a `.venv` virtual environment and installs all required packages from `pyproject.toml`.*

### 3. Install FFmpeg

FFmpeg is required for merging video+audio streams and audio extraction.

#### Windows
1. Download a build from <https://github.com/BtbN/FFmpeg-Builds/releases>
   (choose `ffmpeg-master-latest-win64-gpl.zip`).
2. Extract and copy `ffmpeg.exe`, `ffprobe.exe`, `ffplay.exe` into a folder.
3. Add that folder to your system `PATH`.
4. Verify: `ffmpeg -version`

#### macOS
```bash
brew install ffmpeg
```

#### Linux (Ubuntu/Debian)
```bash
sudo apt update && sudo apt install ffmpeg -y
```

---

## ▶ Running the Application

If you used **pip** (make sure your virtual environment is activated):
```bash
python main.py
```

If you used **uv**:
```bash
uv run main.py
```

---

## 📦 Packaging as a Windows Executable (PyInstaller)

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "YTDownloader" main.py
```

The standalone `.exe` will be in the `dist/` folder.

> **Tip:** Include FFmpeg binaries alongside the `.exe` or bundle them with `--add-binary`.

---

## ⚙ Settings File

Settings are stored at:

```
~/.yt_downloader/settings.json
~/.yt_downloader/history.json
```

---

## 📋 Requirements

- Python 3.12+
- customtkinter ≥ 5.2.0
- yt-dlp ≥ 2024.1.1
- Pillow ≥ 10.0.0
- requests ≥ 2.31.0
- FFmpeg (external binary, on `PATH`)
