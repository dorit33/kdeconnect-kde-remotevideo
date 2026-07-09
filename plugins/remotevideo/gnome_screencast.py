#!/usr/bin/env python3
"""GNOME Mutter ScreenCast — PipeWire stream → H264 → TCP for KDE Connect RemoteVideo."""

import sys
import signal
import gi
gi.require_version('Gio', '2.0')
gi.require_version('GLib', '2.0')
gi.require_version('Gst', '1.0')
from gi.repository import Gio, GLib, Gst

SCREENCAST_BUS = "org.gnome.Mutter.ScreenCast"
SCREENCAST_PATH = "/org/gnome/Mutter/ScreenCast"

def main():
    width = int(sys.argv[1]) if len(sys.argv) > 1 else 1280
    height = int(sys.argv[2]) if len(sys.argv) > 2 else 720
    bitrate = int(sys.argv[3]) if len(sys.argv) > 3 else 2400000
    port = int(sys.argv[4]) if len(sys.argv) > 4 else 1739
    connector = sys.argv[5] if len(sys.argv) > 5 else "DP-3"

    Gst.init(None)
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    loop = GLib.MainLoop()
    pipeline = [None]

    screencast = Gio.DBusProxy.new_sync(
        bus, Gio.DBusProxyFlags.NONE, None,
        SCREENCAST_BUS, SCREENCAST_PATH, "org.gnome.Mutter.ScreenCast", None
    )

    result = screencast.call_sync("CreateSession",
        GLib.Variant("(a{sv})", ({},)),
        Gio.DBusCallFlags.NONE, -1, None)
    session_path = result.unpack()[0]
    print(f"Session: {session_path}", file=sys.stderr)

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
    print(f"Stream: {stream_path}", file=sys.stderr)

    stream = Gio.DBusProxy.new_sync(
        bus, Gio.DBusProxyFlags.NONE, None,
        SCREENCAST_BUS, stream_path, "org.gnome.Mutter.ScreenCast.Stream", None
    )

    def on_signal(proxy, sender_name, signal_name, parameters):
        if signal_name == "PipeWireStreamAdded":
            node_id = parameters.unpack()[0]
            print(f"PipeWire node ID: {node_id}", file=sys.stderr)

            # videorate is essential: Mutter provides variable framerate,
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
                pipeline[0] = Gst.parse_launch(pipe_str)
                ret = pipeline[0].set_state(Gst.State.PLAYING)
                if ret == Gst.StateChangeReturn.FAILURE:
                    print("ERROR: Failed to start pipeline", file=sys.stderr)
                    loop.quit()
                else:
                    print("Pipeline playing", file=sys.stderr)
            except Exception as e:
                print(f"Pipeline creation error: {e}", file=sys.stderr)
                loop.quit()

    stream.connect("g-signal", on_signal)

    session.call_sync("Start", GLib.Variant("()", ()),
        Gio.DBusCallFlags.NONE, -1, None)
    print("Session started", file=sys.stderr)

    def check_pipeline():
        if pipeline[0] is not None:
            pbus = pipeline[0].get_bus()
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

    def on_sigterm(signum, frame):
        print("Stopping...", file=sys.stderr)
        if pipeline[0]:
            pipeline[0].set_state(Gst.State.NULL)
        try:
            session.call_sync("Stop", GLib.Variant("()", ()),
                Gio.DBusCallFlags.NONE, 1000, None)
        except Exception:
            pass
        loop.quit()

    signal.signal(signal.SIGTERM, on_sigterm)
    signal.signal(signal.SIGINT, on_sigterm)

    loop.run()

    if pipeline[0]:
        pipeline[0].set_state(Gst.State.NULL)
    try:
        session.call_sync("Stop", GLib.Variant("()", ()),
            Gio.DBusCallFlags.NONE, 1000, None)
    except Exception:
        pass

if __name__ == "__main__":
    main()
