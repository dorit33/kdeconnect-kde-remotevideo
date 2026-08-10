Name:           kdeconnect-remotevideo
Version:        1.0.0
Release:        1%{?dist}
Summary:        RemoteVideo screen mirroring plugin for KDE Connect

License:        GPL-2.0-only OR GPL-3.0-only
URL:            https://github.com/KDE/kdeconnect-kde
Source0:        remotevideo-plugin.tar.gz
# BuildArch: noarch — not applicable, contains x86_64 .so
%define debug_package %{nil}
Requires:       kdeconnect
Requires:       gstreamer1-plugins-good
Requires:       gstreamer1-plugins-bad-free
Requires:       gstreamer1-openh264
Requires:       pipewire
Requires:       python3-gobject
Requires:       gst-pipewire

%description
RemoteVideo plugin for KDE Connect that enables screen mirroring from PC to phone.
Supports Wayland (via GNOME Mutter ScreenCast API + PipeWire) and X11 (via ximagesrc).
The phone receives an H264 stream over TCP and decodes it with MediaCodec.

%prep
%setup -q

%build
# Pre-built binary RPM — no compilation needed

%install
install -D -m 755 kdeconnect_remotevideo.so \
    %{buildroot}%{_qt6_plugindir}/kdeconnect/kdeconnect_remotevideo.so
install -D -m 644 gnome_screencast.py \
    %{buildroot}%{_qt6_plugindir}/kdeconnect/gnome_screencast.py
install -D -m 644 kdeconnect_remotevideo.json \
    %{buildroot}%{_qt6_plugindir}/kdeconnect/kdeconnect_remotevideo.json

%files
%{_qt6_plugindir}/kdeconnect/kdeconnect_remotevideo.so
%{_qt6_plugindir}/kdeconnect/gnome_screencast.py
%{_qt6_plugindir}/kdeconnect/kdeconnect_remotevideo.json

%changelog
* Mon Aug 10 2026 DeskCam Contributors - 1.0.0-1
- Initial package: RemoteVideo plugin with Wayland PipeWire support
