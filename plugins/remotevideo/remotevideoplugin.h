/**
 * SPDX-FileCopyrightText: 2025 DeskCam Contributors
 *
 * SPDX-License-Identifier: GPL-2.0-only OR GPL-3.0-only OR LicenseRef-KDE-Accepted-GPL
 */

#pragma once

#include <QObject>
#include <QProcess>
#include <QString>

#include <core/kdeconnectplugin.h>

#define PACKET_TYPE_REMOTEVIDEO_GETCAPABILITIES QStringLiteral("kdeconnect.remotevideo.getcapabilities")
#define PACKET_TYPE_REMOTEVIDEO_CAPABILITIES     QStringLiteral("kdeconnect.remotevideo.capabilities")
#define PACKET_TYPE_REMOTEVIDEO_REQUEST          QStringLiteral("kdeconnect.remotevideo.request")
#define PACKET_TYPE_REMOTEVIDEO_STOP             QStringLiteral("kdeconnect.remotevideo.stop")
#define PACKET_TYPE_REMOTEVIDEO_STREAM_START     QStringLiteral("kdeconnect.remotevideo.stream.start")
#define PACKET_TYPE_REMOTEVIDEO_STREAM_STOP      QStringLiteral("kdeconnect.remotevideo.stream.stop")

#define REMOTEVIDEO_STREAM_PORT 1739

class RemoteVideoPlugin : public KdeConnectPlugin
{
    Q_OBJECT
    Q_CLASSINFO("D-Bus Interface", "org.kde.kdeconnect.device.remotevideo")

public:
    explicit RemoteVideoPlugin(QObject *parent, const QVariantList &args);
    ~RemoteVideoPlugin() override;

    QString dbusPath() const override;
    void receivePacket(const NetworkPacket &np) override;

private:
    void sendCapabilities();
    void startStream(int width, int height, int quality);
    void stopStream();
    QString localIp() const;

    QProcess *m_gstProcess = nullptr;
    bool m_streaming = false;
};
