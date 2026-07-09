# RemoteVideo Plugin (DeskCam)

Screen mirroring plugin for KDE Connect. Streams the PC screen to the paired
Android device over TCP using H264 video encoding.

## Architecture

```
PC Screen → GStreamer (capture → H264 encode) → TCP server :1739
                                                      ↑
Android (MediaCodec H264 decode → Surface) ────────────┘
```

The plugin uses the KDE Connect packet system for signalling (capabilities,
stream start/stop) and a direct TCP connection for the video data.

## Platform Support

| Platform | Capture Method | Status |
|----------|---------------|--------|
| Linux X11 | `ximagesrc` | Working |
| Linux Wayland (GNOME) | `pipewiresrc` + Mutter ScreenCast API | Working |
| Linux Wayland (KDE/wlroots) | `pipewiresrc` + xdg-desktop-portal | Experimental |
| Windows | `dx9screencapsrc` | Untested |

## Dependencies (Linux)

### All platforms
- GStreamer 1.0 (`gstreamer1.0`, `gstreamer1.0-plugins-base`, `gstreamer1.0-plugins-good`)
- `gstreamer1.0-openh264` (or `openh264enc` from `gst-plugins-bad`)
- `gst-launch-1.0` in PATH

### Wayland (GNOME)
- `python3`
- `python3-gi` (PyGObject)
- `gstreamer1.0-pipewire` (PipeWire GStreamer plugin)
- `pipewire`
- GNOME Shell with Mutter ScreenCast support

### Wayland (KDE Plasma / wlroots)
- `xdg-desktop-portal`
- `xdg-desktop-portal-kde` (or appropriate backend)
- Same Python/PipeWire deps as above

### Fedora
```bash
sudo dnf install gstreamer1 gstreamer1-plugins-base gstreamer1-plugins-good \
    gstreamer1-plugins-bad-free gstreamer1-pipewire python3-gobject-base pipewire
```

### Ubuntu/Debian
```bash
sudo apt install gstreamer1.0-tools gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
    gstreamer1.0-pipewire python3-gi pipewire
```

## Building

```bash
mkdir build && cd build
cmake .. -DCMAKE_INSTALL_PREFIX=/usr -DWITH_PULSEAUDIO=OFF
make -j$(nproc)
sudo make install
```

The plugin (`kdeconnect_remotevideo.so`) installs to the KDE Connect plugin
directory, and the Wayland helper script (`wayland_screencast.py`) installs
alongside it.

## How It Works

1. Android sends `kdeconnect.remotevideo.getcapabilities` → PC responds with
   resolution, codec, host IP, and port.
2. Android sends `kdeconnect.remotevideo.request` with desired width/height/quality.
3. PC starts a GStreamer pipeline:
   - **X11**: `ximagesrc → openh264enc → tcpserversink`
   - **Wayland**: Python script creates a PipeWire stream via Mutter/portal
     DBus API, then `pipewiresrc → openh264enc → tcpserversink`
4. PC sends `kdeconnect.remotevideo.stream.start` with connection info.
5. Android connects to the TCP port and decodes H264 with MediaCodec.
6. Either side can stop with `kdeconnect.remotevideo.stop`.

## Configuration

The quality parameter (0-100) maps to bitrate:
- `quality * 20000` → 500 kbps (quality=25) to 6 Mbps (quality=100)
- Default: quality=80 → 1.6 Mbps

## Files

- `remotevideoplugin.cpp` / `.h` — Qt/C++ plugin for KDE Connect
- `wayland_screencast.py` — Python helper for Wayland screen capture
- `kdeconnect_remotevideo.json` — Plugin metadata
- `CMakeLists.txt` — Build configuration
