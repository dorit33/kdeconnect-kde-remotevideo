#!/bin/bash
# RemoteVideo plugin installer/uninstaller for KDE Connect
# Supports: Fedora, Arch/Garuda, Debian/Ubuntu, openSUSE
set -e

PLUGIN_NAME="kdeconnect_remotevideo"
SCRIPT_NAME="gnome_screencast.py"
JSON_NAME="kdeconnect_remotevideo.json"
CLIPBOARD_SO="kdeconnect_clipboard.so"

# Resolve script directory (where built .so and source files live)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Detect package manager ---
detect_pkg_manager() {
    if command -v dnf &>/dev/null; then echo "dnf"
    elif command -v pacman &>/dev/null; then echo "pacman"
    elif command -v apt &>/dev/null; then echo "apt"
    elif command -v zypper &>/dev/null; then echo "zypper"
    else echo ""
    fi
}

PKG_MGR=$(detect_pkg_manager)

# --- Dependency names per distro ---
get_deps() {
    case "$PKG_MGR" in
        dnf) echo "kdeconnect gstreamer1-plugins-good gstreamer1-plugins-bad-free gstreamer1-openh264 pipewire python3-gobject gst-pipewire wl-clipboard" ;;
        pacman) echo "kdeconnect gst-plugins-good gst-plugins-bad openh264 pipewire python-gobject gst-pipewire wl-clipboard" ;;
        apt) echo "kdeconnect gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav pipewire python3-gi wl-clipboard" ;;
        zypper) echo "kdeconnect gstreamer-plugins-good gstreamer-plugins-bad gstreamer-plugin-openh264 pipewire python3-gobject wl-clipboard" ;;
        *) echo "" ;;
    esac
}

# --- Detect plugin directory ---
detect_plugin_dir() {
    for dir in \
        "/usr/lib64/qt6/plugins/kdeconnect" \
        "/usr/lib/qt6/plugins/kdeconnect" \
        "/usr/lib/x86_64-linux-gnu/qt6/plugins/kdeconnect" \
        "/usr/lib/qt6/plugins/kdeconnect"; do
        if [ -d "$dir" ]; then echo "$dir"; return 0; fi
    done
    # Fallback: search
    found=$(find /usr/lib* -type d -name kdeconnect 2>/dev/null | grep qt6 | head -1)
    if [ -n "$found" ]; then echo "$found"; else echo ""; fi
}

# --- Find the built .so ---
find_so() {
    for candidate in \
        "$SCRIPT_DIR/kdeconnect_remotevideo.so" \
        "$(pwd)/kdeconnect_remotevideo.so" \
        "$SCRIPT_DIR/../../build-remotevideo/bin/kdeconnect/kdeconnect_remotevideo.so" \
        "$SCRIPT_DIR/build/bin/kdeconnect/kdeconnect_remotevideo.so"; do
        if [ -f "$candidate" ]; then
            echo "$(readlink -f "$candidate")"
            return 0
        fi
    done
    return 1
}

# --- Find the patched clipboard .so ---
find_clipboard_so() {
    for candidate in \
        "$SCRIPT_DIR/$CLIPBOARD_SO" \
        "$(pwd)/$CLIPBOARD_SO" \
        "$SCRIPT_DIR/../../build-remotevideo/bin/kdeconnect/$CLIPBOARD_SO" \
        "$SCRIPT_DIR/build/bin/kdeconnect/$CLIPBOARD_SO"; do
        if [ -f "$candidate" ]; then
            echo "$(readlink -f "$candidate")"
            return 0
        fi
    done
    return 1
}

# --- Install dependencies ---
install_deps() {
    local deps=$(get_deps)
    if [ -z "$deps" ]; then
        echo "WARNING: Unknown distro, cannot auto-install dependencies."
        return
    fi
    echo "Installing dependencies: $deps"
    case "$PKG_MGR" in
        dnf) sudo dnf install -y $deps ;;
        pacman) sudo pacman -S --noconfirm --needed $deps ;;
        apt) sudo apt update && sudo apt install -y $deps ;;
        zypper) sudo zypper install -y $deps ;;
    esac
}

# --- Uninstall ---
do_uninstall() {
    local PLUGIN_DIR=$(detect_plugin_dir)
    if [ -z "$PLUGIN_DIR" ]; then
        echo "ERROR: Could not find KDE Connect plugin directory."
        exit 1
    fi

    echo "============================================"
    echo "  RemoteVideo Plugin — Uninstall"
    echo "============================================"
    echo ""
    echo "Plugin directory: $PLUGIN_DIR"
    echo ""

    local found=0
    for f in "$PLUGIN_NAME.so" "$SCRIPT_NAME" "$JSON_NAME" "$CLIPBOARD_SO"; do
        if [ -f "$PLUGIN_DIR/$f" ]; then
            echo "Removing: $PLUGIN_DIR/$f"
            sudo rm -f "$PLUGIN_DIR/$f"
            found=1
        fi
    done

    if [ "$found" = "0" ]; then
        echo "Plugin not found — nothing to remove."
        exit 0
    fi

    echo ""
    echo "Uninstall complete!"
    echo "Restart kdeconnectd:"
    echo "  systemctl --user restart kdeconnectd"
    echo ""
    exit 0
}

# --- Install ---
do_install() {
    local SO_FILE=$(find_so)
    if [ -z "$SO_FILE" ]; then
        echo "ERROR: kdeconnect_remotevideo.so not found."
        echo "Place the .so next to this script, or build with cmake first."
        exit 1
    fi

    local PY_FILE="$SCRIPT_DIR/$SCRIPT_NAME"
    local JSON_FILE="$SCRIPT_DIR/$JSON_NAME"

    if [ ! -f "$PY_FILE" ]; then
        echo "ERROR: $SCRIPT_NAME not found in $SCRIPT_DIR"
        exit 1
    fi

    local PLUGIN_DIR=$(detect_plugin_dir)
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
    echo "Package manager: ${PKG_MGR:-unknown}"
    echo ""

    # Install dependencies
    if [ -n "$PKG_MGR" ]; then
        echo "Installing dependencies..."
        install_deps
        echo ""
    else
        echo "WARNING: Unknown package manager. Please install dependencies manually:"
        echo "  GStreamer 1.0 (good, bad, openh264), PipeWire, python-gobject"
        echo ""
    fi

    # Install files
    echo "Installing plugin files..."
    sudo cp "$SO_FILE" "$PLUGIN_DIR/$PLUGIN_NAME.so"
    sudo cp "$PY_FILE" "$PLUGIN_DIR/$SCRIPT_NAME"
    sudo cp "$JSON_FILE" "$PLUGIN_DIR/$JSON_NAME" 2>/dev/null || true

    # Install patched clipboard plugin (Wayland fix: wl-copy/wl-paste)
    CLIPBOARD_SO_FILE=$(find_clipboard_so)
    if [ -n "$CLIPBOARD_SO_FILE" ]; then
        echo "Installing patched clipboard plugin (Wayland fix)..."
        sudo cp "$CLIPBOARD_SO_FILE" "$PLUGIN_DIR/$CLIPBOARD_SO"
        echo "  $PLUGIN_DIR/$CLIPBOARD_SO"
    else
        echo "NOTE: Patched clipboard .so not found — clipboard sync on Wayland may not work."
        echo "      Build kdeconnect_clipboard target to enable Wayland clipboard support."
    fi

    echo ""
    echo "Installation complete!"
    echo "  $PLUGIN_DIR/$PLUGIN_NAME.so"
    echo "  $PLUGIN_DIR/$SCRIPT_NAME"
    echo "  $PLUGIN_DIR/$JSON_NAME"
    if [ -n "$CLIPBOARD_SO_FILE" ]; then
        echo "  $PLUGIN_DIR/$CLIPBOARD_SO (Wayland clipboard fix)"
    fi
    echo ""
    echo "Restart kdeconnectd for changes to take effect:"
    echo "  systemctl --user restart kdeconnectd"
    echo "  (or: killall kdeconnectd && kdeconnectd --replace &)"
    echo ""
    echo "To uninstall later: sudo ./install.sh --uninstall"
    echo ""
}

# --- Main ---
case "${1:-}" in
    --uninstall|-u) do_uninstall ;;
    --help|-h)
        echo "Usage: sudo ./install.sh [--uninstall]"
        echo ""
        echo "  (no args)    Install the RemoteVideo plugin"
        echo "  --uninstall  Remove the RemoteVideo plugin"
        ;;
    *) do_install ;;
esac
