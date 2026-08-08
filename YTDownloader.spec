# -*- mode: python ; coding: utf-8 -*-
import sys

is_windows = sys.platform == 'win32'
ffmpeg_binary = 'ffmpeg.exe' if is_windows else 'ffmpeg'

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[(ffmpeg_binary, '.')],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='YTDownloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[ffmpeg_binary],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app_icon.ico' if is_windows else None,
)
