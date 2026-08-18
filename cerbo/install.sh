#!/bin/sh
# Install/update the Scheiber CAN <-> Victron bridge on Venus OS.
# Run as root on a Cerbo GX / Venus OS device.
set -eu

APP_DIR="${APP_DIR:-/data/scheiber-gx}"
SERVICE_LINK="${SERVICE_LINK:-/service/scheiber-gx}"
CAN_IF="${CAN_IF:-can2}"
CAN_BITRATE="${CAN_BITRATE:-250000}"
RAW_BASE="${RAW_BASE:-https://raw.githubusercontent.com/danielkope/scheiber-can-analysis-nmea2000/main/cerbo}"
SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
EXPECTED_BRIDGE_SHA256="6c25ce4b095385217564fc6bf6fdc843dfefd835993d643843811e7f0f737097"

if [ "$(id -u)" != "0" ]; then
    echo "ERROR: run this installer as root." >&2
    exit 1
fi

for cmd in python3 ip sha256sum ln chmod mkdir mv cp rm grep awk; do
    command -v "$cmd" >/dev/null 2>&1 || {
        echo "ERROR: required command not found: $cmd" >&2
        exit 1
    }
done

mkdir -p "$APP_DIR/service"

fetch_file() {
    src_name="$1"
    dst="$2"

    if [ -f "$SELF_DIR/$src_name" ]; then
        cp "$SELF_DIR/$src_name" "$dst"
        return
    fi

    if command -v wget >/dev/null 2>&1; then
        wget -q -O "$dst" "$RAW_BASE/$src_name"
        return
    fi

    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$RAW_BASE/$src_name" -o "$dst"
        return
    fi

    echo "ERROR: cannot obtain $src_name (no local copy, wget, or curl)." >&2
    exit 1
}

# Fetch and validate the complete canonical script before touching the running
# installation. A failed download, compile, or checksum leaves the old bridge
# in place.
fetch_file "bridge.py" "$APP_DIR/bridge.py.new"
python3 -m py_compile "$APP_DIR/bridge.py.new"

actual_sha="$(sha256sum "$APP_DIR/bridge.py.new" | awk '{print $1}')"
if [ "$actual_sha" != "$EXPECTED_BRIDGE_SHA256" ]; then
    echo "ERROR: bridge.py SHA-256 mismatch." >&2
    echo "Expected: $EXPECTED_BRIDGE_SHA256" >&2
    echo "Actual:   $actual_sha" >&2
    rm -f "$APP_DIR/bridge.py.new"
    exit 1
fi

fetch_file "service/run" "$APP_DIR/service/run.new"

# Only after validation succeeds do we back up and replace the installed files.
install_mode="fresh"
if [ -f "$APP_DIR/bridge.py" ]; then
    install_mode="update"
    cp "$APP_DIR/bridge.py" "$APP_DIR/bridge.py.previous"
fi
mv "$APP_DIR/bridge.py.new" "$APP_DIR/bridge.py"
mv "$APP_DIR/service/run.new" "$APP_DIR/service/run"
chmod 755 "$APP_DIR/bridge.py" "$APP_DIR/service/run"

# Remove obsolete packaging files from earlier installer revisions. They are no
# longer part of the runtime or installation path.
rm -f "$APP_DIR/assemble_bridge.py"
rm -rf "$APP_DIR/source"

echo "$CAN_IF" > "$APP_DIR/CAN_INTERFACE"
echo "$CAN_BITRATE" > "$APP_DIR/CAN_BITRATE"

RC_LOCAL="/data/rc.local"
MARKER="# scheiber-gx persistent runit service"
if [ ! -f "$RC_LOCAL" ]; then
    printf '%s\n' '#!/bin/sh' > "$RC_LOCAL"
fi
if ! grep -Fq "$MARKER" "$RC_LOCAL"; then
    cat >> "$RC_LOCAL" <<'RC_EOF'
# scheiber-gx persistent runit service
[ -e /service/scheiber-gx ] || ln -s /data/scheiber-gx/service /service/scheiber-gx
RC_EOF
fi
chmod 755 "$RC_LOCAL"

if [ -L "$SERVICE_LINK" ]; then
    target="$(readlink "$SERVICE_LINK" 2>/dev/null || true)"
    if [ "$target" != "$APP_DIR/service" ]; then
        rm -f "$SERVICE_LINK"
    fi
elif [ -e "$SERVICE_LINK" ]; then
    echo "ERROR: $SERVICE_LINK exists and is not a symlink; refusing to replace it." >&2
    exit 1
fi
[ -e "$SERVICE_LINK" ] || ln -s "$APP_DIR/service" "$SERVICE_LINK"

if command -v svc >/dev/null 2>&1; then
    svc -d "$SERVICE_LINK" 2>/dev/null || true
    sleep 1
    svc -u "$SERVICE_LINK"
fi

cat <<EOF2
Scheiber GX bridge installed.

  mode:      $install_mode
  bridge:    $APP_DIR/bridge.py
  version:   5.4.2
  service:   $SERVICE_LINK
  CAN:       $CAN_IF @ $CAN_BITRATE bit/s
  SHA-256:   $actual_sha
  backup:    $APP_DIR/bridge.py.previous (created on updates)
  log:       $APP_DIR/bridge.log
  status:    $APP_DIR/status.json

Next checks:
  ip -details -statistics link show $CAN_IF
  tail -n 80 $APP_DIR/bridge.log
  dbus -y com.victronenergy.genset.scheiber /Connected GetValue
  dbus -y com.victronenergy.tank.scheiber_fresh /Capacity GetValue
EOF2
