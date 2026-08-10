# KDE Connect RemoteVideo Plugin

Screen mirroring plugin for KDE Connect — stream your PC screen to your Android phone in real-time.

## Features

- **Wayland support** — uses GNOME Mutter ScreenCast API + PipeWire via `pipewiresrc`
- **X11 support** — uses `ximagesrc` (GStreamer)
- **Windows support** — uses `dx9screencapsrc` (GStreamer, experimental)
- H264 encoding via `openh264enc` with screen-optimized settings
- TCP server on port 1739 — phone connects directly to PC
- Bitrate auto-scaled by quality setting (500 kbps – 6 Mbps)
- Touchpad integration — video surface doubles as mouse touchpad
- Compact keyboard control bar with special keys (F1-F12, Ctrl+C/V/X/Z, Alt+Tab, etc.)

## Requirements

### PC (Linux)
- KDE Connect (kdeconnectd)
- GStreamer 1.0 + plugins:
  - `gst-plugins-good` (ximagesrc, videoconvert, videoscale)
  - `gst-plugins-bad` (pipewiresrc)
  - `openh264` (gst-openh264enc)
- PipeWire (Wayland mode)
- Python 3 + `python-gobject` (Wayland mode)
- `gst-pipewire` (Wayland mode)

### PC (Windows, experimental)
- KDE Connect for Windows
- GStreamer 1.0 with `dx9screencapsrc` and `openh264` plugins

### Android
- Android 5.0+ (API 21+)
- H264 hardware decoder (MediaCodec)

## Installation

### Option 1: Shell installer (any Linux distro)

```bash
chmod +x install.sh
sudo ./install.sh
```

The script auto-detects the Qt6 plugin directory and copies the files.

### Option 2: RPM (Fedora/openSUSE)

```bash
sudo dnf install ./kdeconnect-remotevideo-1.0.0-1.fc44.x86_64.rpm
```

Dependencies are installed automatically.

### Option 3: PKGBUILD (Arch/Garuda Linux)

```bash
cd arch
makepkg -si
```

### Option 4: Manual install

```bash
# Build
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release -DWITH_PULSEAUDIO=OFF
make kdeconnect_remotevideo

# Install
sudo cp bin/kdeconnect/kdeconnect_remotevideo.so /usr/lib64/qt6/plugins/kdeconnect/
sudo cp plugins/remotevideo/gnome_screencast.py /usr/lib64/qt6/plugins/kdeconnect/
sudo cp plugins/remotevideo/kdeconnect_remotevideo.json /usr/lib64/qt6/plugins/kdeconnect/

# Restart KDE Connect
systemctl --user restart kdeconnectd
```

## Usage

1. Install the plugin on PC and the APK on your phone
2. Pair your phone with PC in KDE Connect
3. Open "DeskCam Preview" from the KDE Connect app on your phone
4. The screen mirror appears — drag to move mouse, tap to click
5. Toggle the keyboard icon for special keys and mouse buttons

## Architecture

```
PC (GStreamer pipeline)                    Phone (Android)
┌─────────────────────────────┐           ┌──────────────────────┐
│ Screen capture (PipeWire/   │           │                      │
│   ximagesrc/dx9screencapsrc)│           │  DeskCamPreviewActivity
│         ↓                   │           │  ┌──────────────────┐ │
│ videoconvert → videoscale   │           │  │ MediaCodec H264  │ │
│         ↓                   │    TCP    │  │    decoder       │ │
│ openh264enc (H264)          │──────────→│  │        ↓         │ │
│         ↓                   │  port 1739│  │  SurfaceView     │ │
│ h264parse (AU alignment)    │           │  │  (video render)  │ │
│         ↓                   │           │  └──────────────────┘ │
│ tcpserversink               │           │  + Touchpad gestures │
└─────────────────────────────┘           │  + Keyboard panel    │
                                          └──────────────────────┘
```

## Packet types

| Packet | Direction | Description |
|--------|-----------|-------------|
| `kdeconnect.remotevideo.getcapabilities` | Phone → PC | Request screen info |
| `kdeconnect.remotevideo.capabilities` | PC → Phone | Screen resolution, host, port, codec |
| `kdeconnect.remotevideo.request` | Phone → PC | Start stream with width/height/quality |
| `kdeconnect.remotevideo.stream.start` | PC → Phone | Stream ready, connect to TCP |
| `kdeconnect.remotevideo.stop` | Phone → PC | Stop stream |
| `kdeconnect.remotevideo.stream.stop` | PC → Phone | Stream stopped |

## License

GPL-2.0-only OR GPL-3.0-only OR LicenseRef-KDE-Accepted-GPL
