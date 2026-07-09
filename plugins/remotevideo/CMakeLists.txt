kdeconnect_add_plugin(kdeconnect_remotevideo SOURCES remotevideoplugin.cpp)
target_link_libraries(kdeconnect_remotevideo
    kdeconnectcore
    Qt::Network
    Qt::Gui
)

install(FILES wayland_screencast.py
    DESTINATION ${KDE_INSTALL_QTPLUGINDIR}/kdeconnect
)
