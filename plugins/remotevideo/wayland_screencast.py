#!/usr/bin/env python3
"""Wayland screen capture for KDE Connect RemoteVideo.

Tries multiple APIs in order:
  1. GNOME Mutter ScreenCast (org.gnome.Mutter.ScreenCast) — GNOME Wayland
  2. xdg-desktop-portal ScreenCast — KDE Plasma Wayland, wlroots, etc.

Both produce a PipeWire node that we feed into a GStreamer pipeline:
  pipewiresrc -> videoconvert -> videoscale -> videorate -> openh264enc -> h264parse -> tcpserversink
"""

import sys
import signal
import json
import subprocess
import gi
gi.require_version('Gio', '2.0')
gi.require_version('GLib', '2.0')
gi.require_version('Gst', '1.0')
from gi.repository import Gio, GLib, Gst

# ---------------------------------------------------------------------------
# Monitor auto-detection
# ---------------------------------------------------------------------------

def detect_monitor_connector_gnome():
    """Query org.gnome.Mutter.DisplayConfig for the primary monitor connector."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        proxy = Gio.DBusProxy.new_sync(
            bus, Gio.DBusProxyFlags.NONE, None,
            "org.gnome.Mutter.DisplayConfig",
            "/org/gnome/Mutter/DisplayConfig",
            "org.gnome.Mutter.DisplayConfig", None
        )
        result = proxy.call_sync("GetCurrentState",
            GLib.Variant("()", ()), Gio.DBusCallFlags.NONE, -1, None)
        # Layout: (serial, monitors((id, connector, vendor, model, serial, modes, props)), logical_monitors, props)
        _serial, monitors, _logical, _props = result.unpack()
        for mon in monitors:
            # mon = (id, connector, vendor, model, serial, modes, props)
            connector = mon[1]
            props = mon[6] if len(mon) > 6 else {}
            # Check for primary monitor
            if props and "primary" in props:
                if props["primary"].get_boolean():
                    return connector
        # No primary found, return first connector
        if monitors:
            return monitors[0][1]
    except Exception as e:
        print(f"DisplayConfig failed: {e}", file=sys.stderr)
    return None


def detect_monitor_connector_wlr():
    """Try wlr-randr or kscreen-doctor for wlroots/KDE."""
    # Try wlr-randr (wlroots)
    try:
        out = subprocess.check_output(["wlr-randr"], stderr=subprocess.DEVNULL, timeout=3)
        for line in out.decode().strip().split("\n"):
            line = line.strip()
            if line and not line.startswith(" ") and " " not in line:
                return line  # First output name
    except Exception:
        pass
    # Try kscreen-doctor (KDE)
    try:
        out = subprocess.check_output(["kscreen-doctor", "-o"], stderr=subprocess.DEVNULL, timeout=3)
        for line in out.decode().strip().split("\n"):
            line = line.strip()
            if line.startswith("Output:"):
                return line.split(":")[1].strip().split()[0]
    except Exception:
        pass
    return None


def detect_monitor():
    """Auto-detect the primary monitor connector name."""
    c = detect_monitor_connector_gnome()
    if c:
        print(f"Detected monitor (GNOME): {c}", file=sys.stderr)
        return c
    c = detect_monitor_connector_wlr()
    if c:
        print(f"Detected monitor (wlr/kscreen): {c}", file=sys.stderr)
        return c
    print("No monitor detected, using 'DP-1' as fallback", file=sys.stderr)
    return "DP-1"


# ---------------------------------------------------------------------------
# GStreamer pipeline
# ---------------------------------------------------------------------------

def build_and_run_pipeline(node_id, width, height, bitrate, port, loop, pipeline_holder):
    """Create and start the GStreamer pipeline from a PipeWire node."""
    # videorate is essential: Mutter/wlroots provide variable framerate,
    # videorate converts it to the fixed 30fps required downstream.
    pipe_str = (
        f"pipewiresrc path={node_id} ! "
        f"videoconvert ! videoscale ! videorate ! "
        f"video/x-raw,width={width},height={height},framerate=30/1 ! "
        f"openh264enc bitrate={bitrate} usage-type=screen complexity=low gop-size=30 ! "
        f"h264parse config-interval=-1 ! "
        f"video/x-h264,stream-format=byte-stream,alignment=au ! "
        f"tcpserversink host=0.0.0.0 port={port} sync=false recover-policy=keyframe"
    )
    print(f"Creating pipeline: {pipe_str}", file=sys.stderr)
    try:
        pipeline_holder[0] = Gst.parse_launch(pipe_str)
        ret = pipeline_holder[0].set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            print("ERROR: Failed to start pipeline", file=sys.stderr)
            loop.quit()
        else:
            print("Pipeline playing", file=sys.stderr)
    except Exception as e:
        print(f"Pipeline creation error: {e}", file=sys.stderr)
        loop.quit()


def setup_pipeline_error_check(pipeline_holder, loop):
    """Periodically check for pipeline errors/EOS."""
    def check_pipeline():
        if pipeline_holder[0] is not None:
            pbus = pipeline_holder[0].get_bus()
            msg = pbus.pop_filtered(Gst.MessageType.ERROR | Gst.MessageType.EOS)
            if msg:
                if msg.type == Gst.MessageType.ERROR:
                    err, debug = msg.parse_error()
                    print(f"Pipeline error: {err.message} ({debug})", file=sys.stderr)
                else:
                    print("Pipeline EOS", file=sys.stderr)
                loop.quit()
                return False
        return True
    GLib.timeout_add(200, check_pipeline)


def setup_signal_handlers(pipeline_holder, session_stop_fn, loop):
    """Handle SIGTERM/SIGINT for clean shutdown."""
    def on_sigterm(signum, frame):
        print("Stopping...", file=sys.stderr)
        if pipeline_holder[0]:
            pipeline_holder[0].set_state(Gst.State.NULL)
        if session_stop_fn:
            try:
                session_stop_fn()
            except Exception:
                pass
        loop.quit()
    signal.signal(signal.SIGTERM, on_sigterm)
    signal.signal(signal.SIGINT, on_sigterm)


# ---------------------------------------------------------------------------
# Method 1: GNOME Mutter ScreenCast API
# ---------------------------------------------------------------------------

SCREENCAST_BUS = "org.gnome.Mutter.ScreenCast"
SCREENCAST_PATH = "/org/gnome/Mutter/ScreenCast"


def try_gnome_mutter(width, height, bitrate, port, connector, loop, pipeline_holder):
    """Try GNOME Mutter ScreenCast API. Returns True on success, False if unavailable."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

        # Check if Mutter ScreenCast is available
        try:
            Gio.DBusProxy.new_sync(
                bus, Gio.DBusProxyFlags.NONE, None,
                SCREENCAST_BUS, SCREENCAST_PATH, "org.gnome.Mutter.ScreenCast", None
            )
        except Exception:
            print("GNOME Mutter ScreenCast not available", file=sys.stderr)
            return False

        screencast = Gio.DBusProxy.new_sync(
            bus, Gio.DBusProxyFlags.NONE, None,
            SCREENCAST_BUS, SCREENCAST_PATH, "org.gnome.Mutter.ScreenCast", None
        )

        result = screencast.call_sync("CreateSession",
            GLib.Variant("(a{sv})", ({},)),
            Gio.DBusCallFlags.NONE, -1, None)
        session_path = result.unpack()[0]
        print(f"GNOME Session: {session_path}", file=sys.stderr)

        session = Gio.DBusProxy.new_sync(
            bus, Gio.DBusProxyFlags.NONE, None,
            SCREENCAST_BUS, session_path, "org.gnome.Mutter.ScreenCast.Session", None
        )

        stream_options = {
            "mode": GLib.Variant("s", "screencast"),
            "cursor-mode": GLib.Variant("u", 1),
        }
        result = session.call_sync("RecordMonitor",
            GLib.Variant("(sa{sv})", (connector, stream_options)),
            Gio.DBusCallFlags.NONE, -1, None)
        stream_path = result.unpack()[0]
        print(f"GNOME Stream: {stream_path}", file=sys.stderr)

        stream = Gio.DBusProxy.new_sync(
            bus, Gio.DBusProxyFlags.NONE, None,
            SCREENCAST_BUS, stream_path, "org.gnome.Mutter.ScreenCast.Stream", None
        )

        def on_signal(proxy, sender_name, signal_name, parameters):
            if signal_name == "PipeWireStreamAdded":
                node_id = parameters.unpack()[0]
                print(f"GNOME PipeWire node ID: {node_id}", file=sys.stderr)
                build_and_run_pipeline(node_id, width, height, bitrate, port, loop, pipeline_holder)

        stream.connect("g-signal", on_signal)

        session.call_sync("Start", GLib.Variant("()", ()),
            Gio.DBusCallFlags.NONE, -1, None)
        print("GNOME session started", file=sys.stderr)

        def stop_session():
            session.call_sync("Stop", GLib.Variant("()", ()),
                Gio.DBusCallFlags.NONE, 1000, None)
        setup_signal_handlers(pipeline_holder, stop_session, loop)
        setup_pipeline_error_check(pipeline_holder, loop)
        return True

    except Exception as e:
        print(f"GNOME Mutter ScreenCast failed: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Method 2: xdg-desktop-portal ScreenCast API
# ---------------------------------------------------------------------------

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
PORTAL_IFACE = "org.freedesktop.portal.ScreenCast"


def try_xdg_portal(width, height, bitrate, port, loop, pipeline_holder):
    """Try xdg-desktop-portal ScreenCast API. Returns True on success, False if unavailable."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

        screencast = Gio.DBusProxy.new_sync(
            bus, Gio.DBusProxyFlags.NONE, None,
            PORTAL_BUS, PORTAL_PATH, PORTAL_IFACE, None
        )

        # Create session
        result = screencast.call_sync("CreateSession",
            GLib.Variant("(a{sv})", ({"session_handle_token": GLib.Variant("s", "kdeconnect_remotevideo")},)),
            Gio.DBusCallFlags.NONE, -1, None)
        request_path = result.unpack()[0]
        print(f"Portal: CreateSession request: {request_path}", file=sys.stderr)

        # We need to handle the Response signal on the request object
        session_handle = [None]
        pipeline_started = [False]

        def on_request_response(proxy, sender_name, signal_name, parameters):
            if signal_name != "Response":
                return
            response, results = parameters.unpack()
            print(f"Portal response: {response}, results: {results}", file=sys.stderr)
            if response != 0:
                print(f"Portal request failed (response={response})", file=sys.stderr)
                loop.quit()
                return

            if session_handle[0] is None:
                # CreateSession response
                session_handle[0] = results.get("session_handle", None)
                if not session_handle[0]:
                    print("Portal: no session_handle in response", file=sys.stderr)
                    loop.quit()
                    return
                print(f"Portal session: {session_handle[0]}", file=sys.stderr)

                # Select sources
                select_result = screencast.call_sync("SelectSources",
                    GLib.Variant("(oa{sv})", (
                        session_handle[0],
                        {"multiple": GLib.Variant("b", False),
                         "types": GLib.Variant("u", 1)}  # MONITOR = 1
                    )),
                    Gio.DBusCallFlags.NONE, -1, None)
                select_request = select_result.unpack()[0]
                print(f"Portal: SelectSources request: {select_request}", file=sys.stderr)

                # Connect to the SelectSources response
                select_proxy = Gio.DBusProxy.new_sync(
                    bus, Gio.DBusProxyFlags.NONE, None,
                    "org.freedesktop.portal.Desktop", select_request,
                    "org.freedesktop.portal.Request", None
                )
                select_proxy.connect("g-signal", on_request_response)

            elif not pipeline_started[0]:
                # SelectSources response — now start the session
                # Register for PipeWireStreamAdded on the session
                session_proxy = Gio.DBusProxy.new_sync(
                    bus, Gio.DBusProxyFlags.NONE, None,
                    "org.freedesktop.portal.Desktop", session_handle[0],
                    "org.freedesktop.portal.ScreenCast.Session", None
                )

                def on_session_signal(proxy, sender_name, signal_name, parameters):
                    if signal_name == "PipeWireStreamAdded":
                        node_id = parameters.unpack()[0]
                        print(f"Portal PipeWire node ID: {node_id}", file=sys.stderr)
                        build_and_run_pipeline(node_id, width, height, bitrate, port, loop, pipeline_holder)
                        pipeline_started[0] = True

                session_proxy.connect("g-signal", on_session_signal)

                # Start the session
                start_result = screencast.call_sync("Start",
                    GLib.Variant("(osa{sv})", (
                        session_handle[0],
                        "",  # parent_window (empty = no parent)
                        {}
                    )),
                    Gio.DBusCallFlags.NONE, -1, None)
                start_request = start_result.unpack()[0]
                print(f"Portal: Start request: {start_request}", file=sys.stderr)

                start_proxy = Gio.DBusProxy.new_sync(
                    bus, Gio.DBusProxyFlags.NONE, None,
                    "org.freedesktop.portal.Desktop", start_request,
                    "org.freedesktop.portal.Request", None
                )

                def on_start_response(proxy, sender_name, signal_name, parameters):
                    if signal_name != "Response":
                        return
                    response, results = parameters.unpack()
                    print(f"Portal Start response: {response}", file=sys.stderr)
                    if response != 0:
                        print(f"Portal Start failed (response={response})", file=sys.stderr)
                        loop.quit()

                start_proxy.connect("g-signal", on_start_response)

        # Connect to the CreateSession response
        request_proxy = Gio.DBusProxy.new_sync(
            bus, Gio.DBusProxyFlags.NONE, None,
            "org.freedesktop.portal.Desktop", request_path,
            "org.freedesktop.portal.Request", None
        )
        request_proxy.connect("g-signal", on_request_response)

        def stop_session():
            if session_handle[0]:
                session_proxy = Gio.DBusProxy.new_sync(
                    bus, Gio.DBusProxyFlags.NONE, None,
                    "org.freedesktop.portal.Desktop", session_handle[0],
                    "org.freedesktop.portal.ScreenCast.Session", None
                )
                session_proxy.call_sync("Close", GLib.Variant("()", ()),
                    Gio.DBusCallFlags.NONE, 1000, None)

        setup_signal_handlers(pipeline_holder, stop_session, loop)
        setup_pipeline_error_check(pipeline_holder, loop)
        return True

    except Exception as e:
        print(f"xdg-desktop-portal ScreenCast failed: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    width = int(sys.argv[1]) if len(sys.argv) > 1 else 1280
    height = int(sys.argv[2]) if len(sys.argv) > 2 else 720
    bitrate = int(sys.argv[3]) if len(sys.argv) > 3 else 2400000
    port = int(sys.argv[4]) if len(sys.argv) > 4 else 1739
    connector = sys.argv[5] if len(sys.argv) > 5 and sys.argv[5] != "auto" else None

    Gst.init(None)
    loop = GLib.MainLoop()
    pipeline_holder = [None]

    # Auto-detect monitor if not specified
    if not connector:
        connector = detect_monitor()

    # Try GNOME Mutter first
    if try_gnome_mutter(width, height, bitrate, port, connector, loop, pipeline_holder):
        print("Using GNOME Mutter ScreenCast API", file=sys.stderr)
        loop.run()
    # Fallback to xdg-desktop-portal
    elif try_xdg_portal(width, height, bitrate, port, loop, pipeline_holder):
        print("Using xdg-desktop-portal ScreenCast API", file=sys.stderr)
        loop.run()
    else:
        print("ERROR: No Wayland ScreenCast API available. "
              "Need either GNOME Mutter ScreenCast or xdg-desktop-portal with ScreenCast support.",
              file=sys.stderr)
        sys.exit(1)

    # Cleanup
    if pipeline_holder[0]:
        pipeline_holder[0].set_state(Gst.State.NULL)


if __name__ == "__main__":
    main()
