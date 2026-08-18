#!/bin/sh
set -eu
APP_DIR="${APP_DIR:-/data/scheiber-switches}"
SERVICE_LINK="${SERVICE_LINK:-/service/scheiber-switches}"
if [ "$(id -u)" != "0" ]; then
    echo "ERROR: run this uninstaller as root." >&2
    exit 1
fi
if command -v svc >/dev/null 2>&1; then
    svc -d "$SERVICE_LINK" 2>/dev/null || true
fi
[ ! -L "$SERVICE_LINK" ] || rm -f "$SERVICE_LINK"
if [ -f /data/rc.local ]; then
    # Remove the exact two-line persistence stanza while preserving unrelated rc.local entries.
    tmp="/data/rc.local.scheiber-switches.$$"
    awk '
      $0 == "# scheiber-switches persistent runit service" { skip=1; next }
      skip > 0 { skip--; next }
      { print }
    ' /data/rc.local > "$tmp"
    mv "$tmp" /data/rc.local
    chmod 755 /data/rc.local
fi
rm -rf "$APP_DIR"
echo "Scheiber native switch bridge removed."
