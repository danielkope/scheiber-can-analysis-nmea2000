#!/bin/sh
# Install/update the Scheiber V8 native SwitchableOutput bridge on Venus OS.
set -eu

APP_DIR="${APP_DIR:-/data/scheiber-switches}"
SERVICE_LINK="${SERVICE_LINK:-/service/scheiber-switches}"
CAN_IF="${CAN_IF:-can2}"
CAN_BITRATE="${CAN_BITRATE:-250000}"
SCHEIBER_SWITCH_TX="${SCHEIBER_SWITCH_TX:-1}"
SCHEIBER_SWITCH_QUERY_STATES="${SCHEIBER_SWITCH_QUERY_STATES:-1}"
RAW_BASE="${RAW_BASE:-https://raw.githubusercontent.com/danielkope/scheiber-can-analysis-nmea2000/main/cerbo}"
SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

EXPECTED_BRIDGE_SHA256="fbba9ff574bf23a6f315270cf22726859fa3c68fb100d91d426196f46b548863"
EXPECTED_PROTOCOL_SHA256="5da27a59f876a9f2b31a963f3fa27cb5487d846c32f49852eaac82aa03103d7a"
EXPECTED_RUN_SHA256="094b18f7d7448d69ea47646d6ee9cf090f2980d28f7ce551fc5080ac002922d6"

if [ "$(id -u)" != "0" ]; then
    echo "ERROR: run this installer as root." >&2
    exit 1
fi

for cmd in python3 ip sha256sum ln chmod mkdir mv cp rm grep awk readlink sleep; do
    command -v "$cmd" >/dev/null 2>&1 || {
        echo "ERROR: required command not found: $cmd" >&2
        exit 1
    }
done

case "$SCHEIBER_SWITCH_TX" in
    0|1) ;;
    *) echo "ERROR: SCHEIBER_SWITCH_TX must be 0 or 1" >&2; exit 1 ;;
esac
case "$SCHEIBER_SWITCH_QUERY_STATES" in
    0|1) ;;
    *) echo "ERROR: SCHEIBER_SWITCH_QUERY_STATES must be 0 or 1" >&2; exit 1 ;;
esac

mkdir -p "$APP_DIR/switch-service"

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

verify_sha() {
    path="$1"
    expected="$2"
    actual="$(sha256sum "$path" | awk '{print $1}')"
    if [ "$actual" != "$expected" ]; then
        echo "ERROR: SHA-256 mismatch for $path" >&2
        echo "Expected: $expected" >&2
        echo "Actual:   $actual" >&2
        exit 1
    fi
}

fetch_file "switch_bridge.py" "$APP_DIR/switch_bridge.py.new"
fetch_file "switch_protocol.py" "$APP_DIR/switch_protocol.py.new"
fetch_file "switch-service/run" "$APP_DIR/switch-service/run.new"

python3 -m py_compile "$APP_DIR/switch_bridge.py.new" "$APP_DIR/switch_protocol.py.new"
verify_sha "$APP_DIR/switch_bridge.py.new" "$EXPECTED_BRIDGE_SHA256"
verify_sha "$APP_DIR/switch_protocol.py.new" "$EXPECTED_PROTOCOL_SHA256"
verify_sha "$APP_DIR/switch-service/run.new" "$EXPECTED_RUN_SHA256"

install_mode="fresh"
if [ -f "$APP_DIR/switch_bridge.py" ]; then
    install_mode="update"
    cp "$APP_DIR/switch_bridge.py" "$APP_DIR/switch_bridge.py.previous"
    [ ! -f "$APP_DIR/switch_protocol.py" ] || cp "$APP_DIR/switch_protocol.py" "$APP_DIR/switch_protocol.py.previous"
fi

mv "$APP_DIR/switch_bridge.py.new" "$APP_DIR/switch_bridge.py"
mv "$APP_DIR/switch_protocol.py.new" "$APP_DIR/switch_protocol.py"
mv "$APP_DIR/switch-service/run.new" "$APP_DIR/switch-service/run"
chmod 755 "$APP_DIR/switch_bridge.py" "$APP_DIR/switch_protocol.py" "$APP_DIR/switch-service/run"

echo "$CAN_IF" > "$APP_DIR/CAN_INTERFACE"
echo "$CAN_BITRATE" > "$APP_DIR/CAN_BITRATE"
echo "$SCHEIBER_SWITCH_TX" > "$APP_DIR/TX_ENABLED"
echo "$SCHEIBER_SWITCH_QUERY_STATES" > "$APP_DIR/QUERY_STATES"

RC_LOCAL="/data/rc.local"
MARKER="# scheiber-switches persistent runit service"
if [ ! -f "$RC_LOCAL" ]; then
    printf '%s\n' '#!/bin/sh' > "$RC_LOCAL"
fi
if ! grep -Fq "$MARKER" "$RC_LOCAL"; then
    cat >> "$RC_LOCAL" <<'RC_EOF'
# scheiber-switches persistent runit service
[ -e /service/scheiber-switches ] || ln -s /data/scheiber-switches/switch-service /service/scheiber-switches
RC_EOF
fi
chmod 755 "$RC_LOCAL"

if [ -L "$SERVICE_LINK" ]; then
    target="$(readlink "$SERVICE_LINK" 2>/dev/null || true)"
    if [ "$target" != "$APP_DIR/switch-service" ]; then
        rm -f "$SERVICE_LINK"
    fi
elif [ -e "$SERVICE_LINK" ]; then
    echo "ERROR: $SERVICE_LINK exists and is not a symlink; refusing to replace it." >&2
    exit 1
fi
[ -e "$SERVICE_LINK" ] || ln -s "$APP_DIR/switch-service" "$SERVICE_LINK"

if command -v svc >/dev/null 2>&1; then
    svc -d "$SERVICE_LINK" 2>/dev/null || true
    sleep 1
    svc -u "$SERVICE_LINK"
fi

cat <<EOF2
Scheiber native switch bridge installed.

  mode:       $install_mode
  app:        $APP_DIR
  service:    $SERVICE_LINK
  CAN:        $CAN_IF @ $CAN_BITRATE bit/s
  CAN TX:     $SCHEIBER_SWITCH_TX
  RTR sync:   $SCHEIBER_SWITCH_QUERY_STATES
  D-Bus:      com.victronenergy.switch.scheiber
  log:        $APP_DIR/switch_bridge.log
  status:     $APP_DIR/switch_status.json

Verification:
  tail -n 100 $APP_DIR/switch_bridge.log
  dbus -y com.victronenergy.switch.scheiber /Connected GetValue
  dbus -y com.victronenergy.switch.scheiber /Scheiber/AllOutputsSynchronized GetValue
  dbus -y com.victronenergy.switch.scheiber /SwitchableOutput/deck_floodlight/State GetValue

IMPORTANT: first active command validation must be a non-critical lighting circuit.
Do not begin active bilge-mode testing until the lighting press/feedback loop is proven.
EOF2
