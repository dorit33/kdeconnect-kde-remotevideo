/**
 * SPDX-FileCopyrightText: 2025 DeskCam Contributors
 *
 * SPDX-License-Identifier: GPL-2.0-only OR GPL-3.0-only OR LicenseRef-KDE-Accepted-GPL
 */

#include "remotevideoplugin.h"

#include <KPluginFactory>

#include <QDebug>
#include <QHostAddress>
#include <QNetworkInterface>
#include <QUdpSocket>
#include <QScreen>
#include <QGuiApplication>
#include <QAbstractSocket>
#include <QTimer>
#include <QCoreApplication>
#include <QFile>

#include "plugin_remotevideo_debug.h"
#include <core/device.h>

K_PLUGIN_CLASS_WITH_JSON(RemoteVideoPlugin, "kdeconnect_remotevideo.json")

RemoteVideoPlugin::RemoteVideoPlugin(QObject *parent, const QVariantList &args)
    : KdeConnectPlugin(parent, args)
{
}

RemoteVideoPlugin::~RemoteVideoPlugin()
{
    stopStream();
}

QString RemoteVideoPlugin::dbusPath() const
{
    return QLatin1String("/modules/kdeconnect/devices/%1/remotevideo").arg(device()->id());
}

QString RemoteVideoPlugin::localIp() const
{
    // Note: Device::getLocalIpAddress() is misleadingly named - it returns the PEER's
    // IP address (i.e. the phone's IP), not the local PC IP. We need to find OUR local
    // IP that can route to that peer.
    QHostAddress peer = device()->getLocalIpAddress();

    if (!peer.isNull() && peer != QHostAddress::Any && peer != QHostAddress::AnyIPv6) {
        // Use a UDP socket trick: "connecting" a UDP socket doesn't send anything,
        // but it sets the local address based on the OS routing table.
        QUdpSocket sock;
        sock.connectToHost(peer, 53); // any port works
        if (sock.waitForConnected(500)) {
            QHostAddress local = sock.localAddress();
            QString s = local.toString();
            // Strip IPv6 scope id if present
            int pct = s.indexOf(QLatin1Char('%'));
            if (pct >= 0) s = s.left(pct);
            if (!s.isEmpty() && s != QStringLiteral("0.0.0.0") && s != QStringLiteral("::")) {
                return s;
            }
        }
    }

    // Fallback: find a non-loopback IPv4
    for (const auto &iface : QNetworkInterface::allInterfaces()) {
        if ((iface.flags() & QNetworkInterface::IsUp) && !(iface.flags() & QNetworkInterface::IsLoopBack)) {
            for (const auto &entry : iface.addressEntries()) {
                if (entry.ip().protocol() == QAbstractSocket::IPv4Protocol) {
                    return entry.ip().toString();
                }
            }
        }
    }
    return QStringLiteral("0.0.0.0");
}

void RemoteVideoPlugin::receivePacket(const NetworkPacket &np)
{
    if (np.type() == PACKET_TYPE_REMOTEVIDEO_GETCAPABILITIES) {
        sendCapabilities();
    } else if (np.type() == PACKET_TYPE_REMOTEVIDEO_REQUEST) {
        int width = np.get<int>(QStringLiteral("width"), 1280);
        int height = np.get<int>(QStringLiteral("height"), 720);
        int quality = np.get<int>(QStringLiteral("quality"), 80);
        startStream(width, height, quality);
    } else if (np.type() == PACKET_TYPE_REMOTEVIDEO_STOP) {
        stopStream();
    }
}

void RemoteVideoPlugin::sendCapabilities()
{
    QString host = localIp();

    int screenWidth = 1920;
    int screenHeight = 1080;
    auto *screen = QGuiApplication::primaryScreen();
    if (screen) {
        screenWidth = screen->geometry().width();
        screenHeight = screen->geometry().height();
    }

    NetworkPacket np(PACKET_TYPE_REMOTEVIDEO_CAPABILITIES);
    np.set<QString>(QStringLiteral("host"), host);
    np.set<int>(QStringLiteral("port"), REMOTEVIDEO_STREAM_PORT);
    np.set<QString>(QStringLiteral("codec"), QStringLiteral("h264"));
    np.set<int>(QStringLiteral("width"), screenWidth);
    np.set<int>(QStringLiteral("height"), screenHeight);
    sendPacket(np);

    qCDebug(KDECONNECT_PLUGIN_REMOTEVIDEO) << "Sent capabilities: host=" << host
                                           << "port=" << REMOTEVIDEO_STREAM_PORT
                                           << "resolution=" << screenWidth << "x" << screenHeight;
}

void RemoteVideoPlugin::startStream(int width, int height, int quality)
{
    if (m_streaming) {
        qCWarning(KDECONNECT_PLUGIN_REMOTEVIDEO) << "Stream already running, stopping first";
        stopStream();
    }

    // Pipeline: capture screen -> H264 (raw byte-stream) -> TCP server on port 1739
    // The phone connects to this port and reads raw H264 Annex-B bytestream,
    // which MediaCodec can decode directly.
    //
    // On Wayland, ximagesrc only captures XWayland windows (not native Wayland).
    // We use a Python helper script that talks to org.gnome.Mutter.ScreenCast DBus API
    // to create a PipeWire stream, then uses pipewiresrc in GStreamer.
    // On X11, we fall back to ximagesrc directly.

    // Map quality (0-100) to bitrate (bps for openh264enc)
    // Lower mapping to stay reliable over Tailscale/mobile links
    int bitrate = qBound(500000, quality * 20000, 6000000); // 500 kbps .. 6 Mbps

    m_gstProcess = new QProcess(this);
    m_gstProcess->setProcessChannelMode(QProcess::MergedChannels);

    // Check if we're on Wayland
    bool isWayland = qEnvironmentVariable("XDG_SESSION_TYPE") == QLatin1String("wayland");

    if (isWayland) {
        // Use GNOME ScreenCast helper script with pipewiresrc
        QString scriptPath = QStringLiteral("/usr/lib64/qt6/plugins/kdeconnect/gnome_screencast.py");
        if (!QFile::exists(scriptPath)) {
            scriptPath = QStringLiteral("%1/../gnome_screencast.py").arg(QCoreApplication::applicationDirPath());
        }
        qCInfo(KDECONNECT_PLUGIN_REMOTEVIDEO) << "Wayland detected, using GNOME ScreenCast script:" << scriptPath;

        QStringList args{
            scriptPath,
            QString::number(width),
            QString::number(height),
            QString::number(bitrate),
            QString::number(REMOTEVIDEO_STREAM_PORT)
        };
        m_gstProcess->start(QStringLiteral("python3"), args);
    } else {
#ifdef Q_OS_WIN
        QString pipeline = QStringLiteral(
            "gst-launch-1.0 -e dx9screencapsrc ! "
            "videoconvert ! videoscale ! "
            "video/x-raw,width=%1,height=%2,framerate=30/1 ! "
            "openh264enc bitrate=%3 complexity=low gop-size=30 ! "
            "h264parse config-interval=-1 ! "
            "video/x-h264,stream-format=byte-stream,alignment=au ! "
            "tcpserversink host=0.0.0.0 port=%4 sync=false recover-policy=keyframe"
        ).arg(width).arg(height).arg(bitrate).arg(REMOTEVIDEO_STREAM_PORT);
#else
        QString pipeline = QStringLiteral(
            "gst-launch-1.0 -e ximagesrc use-damage=false ! "
            "videoconvert ! videoscale ! "
            "video/x-raw,width=%1,height=%2,framerate=30/1 ! "
            "openh264enc bitrate=%3 complexity=low gop-size=30 ! "
            "h264parse config-interval=-1 ! "
            "video/x-h264,stream-format=byte-stream,alignment=au ! "
            "tcpserversink host=0.0.0.0 port=%4 sync=false recover-policy=keyframe"
        ).arg(width).arg(height).arg(bitrate).arg(REMOTEVIDEO_STREAM_PORT);
#endif
        qCInfo(KDECONNECT_PLUGIN_REMOTEVIDEO) << "Starting GStreamer pipeline:" << pipeline;
        m_gstProcess->start(QStringLiteral("bash"), QStringList{QStringLiteral("-c"), pipeline});
    }

    connect(m_gstProcess, &QProcess::errorOccurred, this, [](QProcess::ProcessError err) {
        qCCritical(KDECONNECT_PLUGIN_REMOTEVIDEO) << "GStreamer process error:" << err;
    });

    connect(m_gstProcess, &QProcess::readyReadStandardOutput, this, [this]() {
        const QByteArray out = m_gstProcess->readAllStandardOutput();
        qCDebug(KDECONNECT_PLUGIN_REMOTEVIDEO) << "[gst]" << out.trimmed();
    });

    connect(m_gstProcess, QOverload<int, QProcess::ExitStatus>::of(&QProcess::finished), this, [this](int code, QProcess::ExitStatus) {
        qCInfo(KDECONNECT_PLUGIN_REMOTEVIDEO) << "GStreamer finished with code" << code;
        m_streaming = false;
    });

    m_streaming = true;

    // Notify phone that stream has started so it can connect.
    // Delay to give the ScreenCast session + GStreamer time to bind the TCP port.
    // (Android side also retries connecting 20x300ms.)
    QTimer::singleShot(800, this, [this, width, height]() {
        if (!m_streaming) return;
        NetworkPacket startNp(PACKET_TYPE_REMOTEVIDEO_STREAM_START);
        startNp.set<QString>(QStringLiteral("host"), localIp());
        startNp.set<int>(QStringLiteral("port"), REMOTEVIDEO_STREAM_PORT);
        startNp.set<QString>(QStringLiteral("codec"), QStringLiteral("h264"));
        startNp.set<int>(QStringLiteral("width"), width);
        startNp.set<int>(QStringLiteral("height"), height);
        sendPacket(startNp);
    });
}

void RemoteVideoPlugin::stopStream()
{
    if (!m_streaming && !m_gstProcess) return;

    qCInfo(KDECONNECT_PLUGIN_REMOTEVIDEO) << "Stopping stream";

    m_streaming = false;

    if (m_gstProcess) {
        // SIGTERM so the helper script can clean up the ScreenCast session
        m_gstProcess->terminate();
        disconnect(m_gstProcess, nullptr, this, nullptr);
        QProcess *proc = m_gstProcess;
        m_gstProcess = nullptr;
        // Force-kill if it doesn't exit within 2s, then delete
        QTimer::singleShot(2000, proc, [proc]() {
            if (proc->state() != QProcess::NotRunning) {
                proc->kill();
            }
            proc->deleteLater();
        });
    }

    NetworkPacket np(PACKET_TYPE_REMOTEVIDEO_STREAM_STOP);
    sendPacket(np);
}

#include "moc_remotevideoplugin.cpp"
#include "remotevideoplugin.moc"
