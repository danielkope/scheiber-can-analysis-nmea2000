#!/bin/sh
# Disable both Scheiber GX runit services while leaving /data files intact.
set -eu

SERVICE_LINK="${SERVICE_LINK:-/service/scheiber-gx}"
SWITCH_SERVICE_LINK="${SWITCH_SERVICE_LINK:-/service/scheiber-switch}"
RC_LOCAL="/data/rc.local"
MAIN_MARKER="# scheiber-gx persistent runit service"
SWITCH_MARKER="# scheiber-switch persistent runit service"

if [ "$(id -u)" != "0" ]; then
    echo "ERROR: run this script as root." >&2
    exit 1
fi

if command -v svc >/dev/null 2>&1; then
    [ ! -e "$SWITCH_SERVICE_LINK" ] || svc -d "$SWITCH_SERVICE_LINK" 2>/dev/null || true
    [ ! -e "$SERVICE_LINK" ] || svc -d "$SERVICE_LINK" 2>/dev/null || true
fi
[ ! -L "$SWITCH_SERVICE_LINK" ] || rm -f "$SWITCH_SERVICE_LINK"
[ ! -L "$SERVICE_LINK" ] || rm -f "$SERVICE_LINK"

# Remove each marker and the immediately following symlink command only.
if [ -f "$RC_LOCAL" ]; then
    awk -v main_marker="$MAIN_MARKER" -v switch_marker="$SWITCH_MARKER" '
        $0 == main_marker || $0 == switch_marker { skip_next=1; next }
        skip_next { skip_next=0; next }
        { print }
    ' "$RC_LOCAL" > "$RC_LOCAL.tmp"
    mv "$RC_LOCAL.tmp" "$RC_LOCAL"
    chmod 755 "$RC_LOCAL"
fi

echo "Scheiber GX services disabled. Runtime files remain in /data/scheiber-gx."
echo "To purge them manually: rm -rf /data/scheiber-gx"
