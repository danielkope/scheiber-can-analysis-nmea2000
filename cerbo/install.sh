#!/bin/sh
# Install/update the Scheiber CAN <-> Victron bridge and native switch service.
# Run as root on a Cerbo GX / Venus OS device.
set -eu

APP_DIR="${APP_DIR:-/data/scheiber-gx}"
SERVICE_LINK="${SERVICE_LINK:-/service/scheiber-gx}"
SWITCH_SERVICE_LINK="${SWITCH_SERVICE_LINK:-/service/scheiber-switch}"
CAN_IF="${CAN_IF:-can2}"
CAN_BITRATE="${CAN_BITRATE:-250000}"
SWITCH_TX_ENABLED="${SWITCH_TX_ENABLED:-1}"
SWITCH_RTR_ENABLED="${SWITCH_RTR_ENABLED:-1}"
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

case "$SWITCH_TX_ENABLED" in 0|1) ;; *) echo "ERROR: SWITCH_TX_ENABLED must be 0 or 1." >&2; exit 1 ;; esac
case "$SWITCH_RTR_ENABLED" in 0|1) ;; *) echo "ERROR: SWITCH_RTR_ENABLED must be 0 or 1." >&2; exit 1 ;; esac

mkdir -p "$APP_DIR/service" "$APP_DIR/service-switch" "$APP_DIR/.install-new"
STAGE="$APP_DIR/.install-new"
rm -f "$STAGE"/*

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

# Fetch and validate every runtime file before replacing the installed service.
fetch_file "bridge.py" "$STAGE/bridge.py"
fetch_file "service/run" "$STAGE/run-main"
fetch_file "scheiber_switch_protocol.py" "$STAGE/scheiber_switch_protocol.py"
fetch_file "switch_service.py" "$STAGE/switch_service.py"
fetch_file "service-switch/run" "$STAGE/run-switch"

python3 -m py_compile \
    "$STAGE/bridge.py" \
    "$STAGE/scheiber_switch_protocol.py" \
    "$STAGE/switch_service.py"

actual_bridge_sha="$(sha256sum "$STAGE/bridge.py" | awk '{print $1}')"
if [ "$actual_bridge_sha" != "$EXPECTED_BRIDGE_SHA256" ]; then
    echo "ERROR: bridge.py SHA-256 mismatch." >&2
    echo "Expected: $EXPECTED_BRIDGE_SHA256" >&2
    echo "Actual:   $actual_bridge_sha" >&2
    exit 1
fi

# Refuse to replace unrelated runit entries.
check_service_path() {
    link="$1"
    expected="$2"
    if [ -L "$link" ]; then
        target="$(readlink "$link" 2>/dev/null || true)"
        [ "$target" = "$expected" ] || {
            echo "ERROR: $link points to $target, not $expected; refusing to replace it." >&2
            exit 1
        }
    elif [ -e "$link" ]; then
        echo "ERROR: $link exists and is not a symlink; refusing to replace it." >&2
        exit 1
    fi
}
check_service_path "$SERVICE_LINK" "$APP_DIR/service"
check_service_path "$SWITCH_SERVICE_LINK" "$APP_DIR/service-switch"

install_mode="fresh"
if [ -f "$APP_DIR/bridge.py" ]; then
    install_mode="update"
    cp "$APP_DIR/bridge.py" "$APP_DIR/bridge.py.previous"
fi
for file in scheiber_switch_protocol.py switch_service.py; do
    [ ! -f "$APP_DIR/$file" ] || cp "$APP_DIR/$file" "$APP_DIR/$file.previous"
done

mv "$STAGE/bridge.py" "$APP_DIR/bridge.py"
mv "$STAGE/scheiber_switch_protocol.py" "$APP_DIR/scheiber_switch_protocol.py"
mv "$STAGE/switch_service.py" "$APP_DIR/switch_service.py"
mv "$STAGE/run-main" "$APP_DIR/service/run"
mv "$STAGE/run-switch" "$APP_DIR/service-switch/run"
chmod 755 \
    "$APP_DIR/bridge.py" \
    "$APP_DIR/switch_service.py" \
    "$APP_DIR/service/run" \
    "$APP_DIR/service-switch/run"
chmod 644 "$APP_DIR/scheiber_switch_protocol.py"
rm -rf "$STAGE"

# Remove obsolete packaging files from earlier installer revisions.
rm -f "$APP_DIR/assemble_bridge.py"
rm -rf "$APP_DIR/source"

echo "$CAN_IF" > "$APP_DIR/CAN_INTERFACE"
echo "$CAN_BITRATE" > "$APP_DIR/CAN_BITRATE"
echo "$SWITCH_TX_ENABLED" > "$APP_DIR/SWITCH_TX_ENABLED"
echo "$SWITCH_RTR_ENABLED" > "$APP_DIR/SWITCH_RTR_ENABLED"

RC_LOCAL="/data/rc.local"
MAIN_MARKER="# scheiber-gx persistent runit service"
SWITCH_MARKER="# scheiber-switch persistent runit service"
if [ ! -f "$RC_LOCAL" ]; then
    printf '%s\n' '#!/bin/sh' > "$RC_LOCAL"
fi
if ! grep -Fq "$MAIN_MARKER" "$RC_LOCAL"; then
    cat >> "$RC_LOCAL" <<'RC_MAIN'
# scheiber-gx persistent runit service
[ -e /service/scheiber-gx ] || ln -s /data/scheiber-gx/service /service/scheiber-gx
RC_MAIN
fi
if ! grep -Fq "$SWITCH_MARKER" "$RC_LOCAL"; then
    cat >> "$RC_LOCAL" <<'RC_SWITCH'
# scheiber-switch persistent runit service
[ -e /service/scheiber-switch ] || ln -s /data/scheiber-gx/service-switch /service/scheiber-switch
RC_SWITCH
fi
chmod 755 "$RC_LOCAL"

[ -e "$SERVICE_LINK" ] || ln -s "$APP_DIR/service" "$SERVICE_LINK"
[ -e "$SWITCH_SERVICE_LINK" ] || ln -s "$APP_DIR/service-switch" "$SWITCH_SERVICE_LINK"

if command -v svc >/dev/null 2>&1; then
    svc -d "$SWITCH_SERVICE_LINK" 2>/dev/null || true
    svc -d "$SERVICE_LINK" 2>/dev/null || true
    sleep 1
    svc -u "$SERVICE_LINK"
    svc -u "$SWITCH_SERVICE_LINK"
fi

cat <<EOF
Scheiber GX services installed.

  mode:             $install_mode
  app:              $APP_DIR
  telemetry:        $SERVICE_LINK
  native switches:  $SWITCH_SERVICE_LINK
  CAN:              $CAN_IF @ $CAN_BITRATE bit/s
  switch CAN TX:    $SWITCH_TX_ENABLED
  switch RTR sync:  $SWITCH_RTR_ENABLED
  bridge SHA-256:   $actual_bridge_sha
  telemetry log:    $APP_DIR/bridge.log
  switch log:       $APP_DIR/switch.log
  switch status:    $APP_DIR/switch-status.json

Next checks:
  ip -details -statistics link show $CAN_IF
  sv status $SERVICE_LINK $SWITCH_SERVICE_LINK
  tail -n 100 $APP_DIR/switch.log
  dbus -y com.victronenergy.switch.scheiber /Connected GetValue
  dbus -y com.victronenergy.switch.scheiber /Scheiber/SynchronizedOutputCount GetValue
EOF
