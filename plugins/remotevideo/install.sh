#!/bin/bash
# RemoteVideo plugin installer for KDE Connect
# Supports: Fedora, Arch, Debian/Ubuntu, openSUSE
set -e

PLUGIN_NAME="kdeconnect_remotevideo"
SCRIPT_NAME="gnome_screencast.py"
JSON_NAME="kdeconnect_remotevideo.json"

# Resolve script directory (where built .so and source files live)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Find the built .so — could be in build dir or alongside this script
find_so() {
    # Look in common build locations
    for candidate in \
        "$SCRIPT_DIR/kdeconnect_remotevideo.so" \
        "$SCRIPT_DIR/../../build-remotevideo/bin/kdeconnect/kdeconnect_remotevideo.so" \
        "$SCRIPT_DIR/build/bin/kdeconnect/kdeconnect_remotevideo.so"; do
        if [ -f "$candidate" ]; then
            echo "$(readlink -f "$candidate")"
            return 0
        fi
    done
    return 1
}

SO_FILE=$(find_so)
if [ -z "$SO_FILE" ]; then
    echo "ERROR: Built kdeconnect_remotevideo.so not found."
    echo "Please build the plugin first with cmake, or place the .so next to this script."
    exit 1
fi

PY_FILE="$SCRIPT_DIR/$SCRIPT_NAME"
JSON_FILE="$SCRIPT_DIR/$JSON_NAME"

if [ ! -f "$PY_FILE" ]; then
    echo "ERROR: $SCRIPT_NAME not found in $SCRIPT_DIR"
    exit 1
fi

# Detect distro and find plugin path
detect_plugin_dir() {
    if [ -d "/usr/lib64/qt6/plugins/kdeconnect" ]; then
        echo "/usr/lib64/qt6/plugins/kdeconnect"
    elif [ -d "/usr/lib/qt6/plugins/kdeconnect" ]; then
        echo "/usr/lib/qt6/plugins/kdeconnect"
    elif [ -d "/usr/lib/x86_64-linux-gnu/qt6/plugins/kdeconnect" ]; then
        echo "/usr/lib/x86_64-linux-gnu/qt6/plugins/kdeconnect"
    elif [ -d "/usr/lib/qt6/plugins/kdeconnect" ]; then
        echo "/usr/lib/qt6/plugins/kdeconnect"
    else
        # Try to find it
        found=$(find /usr/lib* -type d -name kdeconnect 2>/dev/null | grep qt6 | head -1)
        if [ -n "$found" ]; then
            echo "$found"
        else
            echo ""
        fi
    fi
}

PLUGIN_DIR=$(detect_plugin_dir)
if [ -z "$PLUGIN_DIR" ]; then
    echo "ERROR: Could not find KDE Connect plugin directory."
    echo "Is kdeconnect installed? Looking for qt6/plugins/kdeconnect/"
    exit 1
fi

echo "============================================"
echo "  KDE Connect RemoteVideo Plugin Installer"
echo "============================================"
echo ""
echo "Detected plugin directory: $PLUGIN_DIR"
echo "Plugin .so: $SO_FILE"
echo "Python helper: $PY_FILE"
echo ""

# Check dependencies
echo "Checking dependencies..."
missing=()

check_cmd() {
    if ! command -v "$1" &>/dev/null; then
        missing+=("$1")
    fi
}

check_pkg() {
    if command -v dnf &>/dev/null; then
        dnf list installed "$1" &>/dev/null || missing+=("$1 (dnf)")
    elif command -v pacman &>/dev/null; then
        pacman -Q "$1" &>/dev/null || missing+=("$1 (pacman)")
    elif command -v dpkg &>/dev/null; then
        dpkg -l "$1" &>/dev/null 2>&1 || missing+=("$1 (apt)")
    fi
}

check_cmd gst-launch-1.0
check_cmd python3
check_pkg pipewire
check_pkg python3-gobject 2>/dev/null || check_pkg python-gobject

# GStreamer plugins
if command -v dnf &>/dev/null; then
    check_pkg gstreamer1-plugins-good
    check_pkg gstreamer1-plugins-bad-free
    check_pkg gstreamer1-openh264
elif command -v pacman &>/dev/null; then
    check_pkg gst-plugins-good
    check_pkg gst-plugins-bad
    check_pkg openh264
fi

if [ ${#missing[@]} -gt 0 ]; then
    echo ""
    echo "WARNING: Missing dependencies:"
    for pkg in "${missing[@]}"; do
        echo "  - $pkg"
    done
    echo ""
    echo "Install them before using the plugin."
    echo ""
fi

# Install
echo "Installing..."
if [ -w "$PLUGIN_DIR" ]; then
    cp "$SO_FILE" "$PLUGIN_DIR/$PLUGIN_NAME.so"
    cp "$PY_FILE" "$PLUGIN_DIR/$SCRIPT_NAME"
    cp "$JSON_FILE" "$PLUGIN_DIR/$JSON_NAME" 2>/dev/null || true
else
    echo "Need root access to install to $PLUGIN_DIR"
    sudo cp "$SO_FILE" "$PLUGIN_DIR/$PLUGIN_NAME.so"
    sudo cp "$PY_FILE" "$PLUGIN_DIR/$SCRIPT_NAME"
    sudo cp "$JSON_FILE" "$PLUGIN_DIR/$JSON_NAME" 2>/dev/null || true
fi

echo ""
echo "Installation complete!"
echo "  $PLUGIN_DIR/$PLUGIN_NAME.so"
echo "  $PLUGIN_DIR/$SCRIPT_NAME"
echo ""
echo "Restart kdeconnectd for changes to take effect:"
echo "  systemctl --user restart kdeconnectd"
echo ""
