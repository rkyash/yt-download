[Setup]
AppName=YT Downloader
AppVersion=1.0.0
DefaultDirName={autopf}\YT Downloader
DefaultGroupName=YT Downloader
OutputDir=dist
OutputBaseFilename=YTDownloader-Windows-Setup
SetupIconFile=app_icon.ico
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "dist\YTDownloader.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\YT Downloader"; Filename: "{app}\YTDownloader.exe"; IconFilename: "{app}\YTDownloader.exe"
Name: "{autodesktop}\YT Downloader"; Filename: "{app}\YTDownloader.exe"; IconFilename: "{app}\YTDownloader.exe"
