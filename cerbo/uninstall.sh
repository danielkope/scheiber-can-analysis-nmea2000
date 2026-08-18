#!/bin/sh
# Disable the Scheiber GX bridge while leaving /data/scheiber-gx intact.
set -eu

SERVICE_LINK="${SERVICE_LINK:-/service/scheiber-gx}"
RC_LOCAL="/data/rc.local"
MARKER="# scheiber-gx persistent runit service"

if [ "$(id -u)" != "0" ]; then
    echo "ERROR: run this script as root." >&2
    exit 1
fi

if command -v svc >/dev/null 2>&1 && [ -e "$SERVICE_LINK" ]; then
    svc -d "$SERVICE_LINK" 2>/dev/null || true
fi
[ -L "$SERVICE_LINK" ] && rm -f "$SERVICE_LINK"

# Remove the marker and the immediately following symlink line inserted by
# install.sh. Keep all unrelated rc.local content.
if [ -f "$RC_LOCAL" ]; then
    awk -v marker="$MARKER" '
        $0 == marker { skip_next=1; next }
        skip_next { skip_next=0; next }
        { print }
    ' "$RC_LOCAL" > "$RC_LOCAL.tmp"
    mv "$RC_LOCAL.tmp" "$RC_LOCAL"
    chmod 755 "$RC_LOCAL"
fi

echo "Scheiber GX bridge disabled. Persistent files remain in /data/scheiber-gx."
echo "To purge them manually: rm -rf /data/scheiber-gx"
