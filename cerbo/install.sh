#!/bin/sh
# Install/update the Scheiber CAN <-> Victron bridge and native switch service.
# Run as root on a Cerbo GX / Venus OS device.
set -eu

APP_DIR="${APP_DIR:-/data/scheiber-gx}"
SERVICE_LINK="${SERVICE_LINK:-/service/scheiber-gx}"
SWITCH_SERVICE_LINK="${SWITCH_SERVICE_LINK:-/service/scheiber-switch}"
CAN_IF="${CAN_IF:-auto}"
CAN_BITRATE="${CAN_BITRATE:-250000}"
CAN_USB_SERIAL="${CAN_USB_SERIAL:-}"
CAN_USB_VENDOR_ID="${CAN_USB_VENDOR_ID:-}"
CAN_USB_PRODUCT_ID="${CAN_USB_PRODUCT_ID:-}"
SWITCH_TX_ENABLED="${SWITCH_TX_ENABLED:-1}"
SWITCH_RTR_ENABLED="${SWITCH_RTR_ENABLED:-1}"
RAW_BASE="${RAW_BASE:-https://raw.githubusercontent.com/danielkope/scheiber-can-analysis-nmea2000/main/cerbo}"
SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
EXPECTED_BRIDGE_SHA256="31bf49883c7cfff8ccaa26f2e4d69d793d4655d8ce51e5fe1ec8940733ed20e1"
RC_LOCAL="${RC_LOCAL:-/data/rc.local}"
MAIN_MARKER="# scheiber-gx persistent runit service"
SWITCH_MARKER="# scheiber-switch persistent runit service"

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

case "$CAN_IF" in
    ""|*[!A-Za-z0-9_.:-]*)
        echo "ERROR: CAN_IF must be 'auto' or a valid interface name." >&2
        exit 1
        ;;
esac
case "$CAN_BITRATE" in
    ""|*[!0-9]*) echo "ERROR: CAN_BITRATE must be numeric." >&2; exit 1 ;;
esac
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

fetch_file "bridge.py" "$STAGE/bridge.py"
fetch_file "resolve_can_interface.py" "$STAGE/resolve_can_interface.py"
fetch_file "service/run" "$STAGE/run-main"
fetch_file "scheiber_switch_protocol.py" "$STAGE/scheiber_switch_protocol.py"
fetch_file "switch_service.py" "$STAGE/switch_service.py"
fetch_file "service-switch/run" "$STAGE/run-switch"
fetch_file "node-red-anchor-light-flow.json" "$STAGE/node-red-anchor-light-flow.json"
fetch_file "node-red-bilge-alarms-flow.json" "$STAGE/node-red-bilge-alarms-flow.json"

python3 -m py_compile \
    "$STAGE/bridge.py" \
    "$STAGE/resolve_can_interface.py" \
    "$STAGE/scheiber_switch_protocol.py" \
    "$STAGE/switch_service.py"

actual_bridge_sha="$(sha256sum "$STAGE/bridge.py" | awk '{print $1}')"
if [ "$actual_bridge_sha" != "$EXPECTED_BRIDGE_SHA256" ]; then
    echo "ERROR: bridge.py SHA-256 mismatch." >&2
    echo "Expected: $EXPECTED_BRIDGE_SHA256" >&2
    echo "Actual:   $actual_bridge_sha" >&2
    exit 1
fi

# Best-effort install-time discovery. The runit service repeats this operation
# on every boot, so a temporarily disconnected adapter does not block updates.
modprobe can 2>/dev/null || true
modprobe can_raw 2>/dev/null || true
modprobe gs_usb 2>/dev/null || true
resolved_can_if=""
if resolved_can_if="$(
    python3 "$STAGE/resolve_can_interface.py" \
        --interface "$CAN_IF" \
        --usb-serial "$CAN_USB_SERIAL" \
        --vendor-id "$CAN_USB_VENDOR_ID" \
        --product-id "$CAN_USB_PRODUCT_ID"
)"; then
    if [ -z "$CAN_USB_SERIAL" ]; then
        CAN_USB_SERIAL="$(
            python3 "$STAGE/resolve_can_interface.py" \
                --interface "$resolved_can_if" \
                --field serial
        )"
        [ -z "$CAN_USB_SERIAL" ] || echo "Auto-enrolled CAN USB serial: $CAN_USB_SERIAL"
    fi
    if [ -z "$CAN_USB_VENDOR_ID" ]; then
        CAN_USB_VENDOR_ID="$(
            python3 "$STAGE/resolve_can_interface.py" \
                --interface "$resolved_can_if" \
                --field vendor
        )"
    fi
    if [ -z "$CAN_USB_PRODUCT_ID" ]; then
        CAN_USB_PRODUCT_ID="$(
            python3 "$STAGE/resolve_can_interface.py" \
                --interface "$resolved_can_if" \
                --field product
        )"
    fi
else
    echo "WARNING: CAN adapter is not currently resolvable; runit will retry at boot." >&2
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
for file in resolve_can_interface.py scheiber_switch_protocol.py switch_service.py; do
    [ ! -f "$APP_DIR/$file" ] || cp "$APP_DIR/$file" "$APP_DIR/$file.previous"
done

mv "$STAGE/bridge.py" "$APP_DIR/bridge.py"
mv "$STAGE/resolve_can_interface.py" "$APP_DIR/resolve_can_interface.py"
mv "$STAGE/scheiber_switch_protocol.py" "$APP_DIR/scheiber_switch_protocol.py"
mv "$STAGE/switch_service.py" "$APP_DIR/switch_service.py"
mv "$STAGE/run-main" "$APP_DIR/service/run"
mv "$STAGE/run-switch" "$APP_DIR/service-switch/run"
mv "$STAGE/node-red-anchor-light-flow.json" "$APP_DIR/node-red-anchor-light-flow.json"
mv "$STAGE/node-red-bilge-alarms-flow.json" "$APP_DIR/node-red-bilge-alarms-flow.json"
chmod 755 \
    "$APP_DIR/bridge.py" \
    "$APP_DIR/resolve_can_interface.py" \
    "$APP_DIR/switch_service.py" \
    "$APP_DIR/service/run" \
    "$APP_DIR/service-switch/run"
chmod 644 "$APP_DIR/scheiber_switch_protocol.py" "$APP_DIR/node-red-anchor-light-flow.json" "$APP_DIR/node-red-bilge-alarms-flow.json"
rm -rf "$STAGE"

# Remove obsolete packaging files from earlier installer revisions.
rm -f "$APP_DIR/assemble_bridge.py"
rm -rf "$APP_DIR/source"

# CAN_INTERFACE is a selector ('auto' is preferred), not necessarily the
# boot-specific canN name. The resolved name is written to /run at service start.
printf '%s\n' "$CAN_IF" > "$APP_DIR/CAN_INTERFACE"
printf '%s\n' "$CAN_BITRATE" > "$APP_DIR/CAN_BITRATE"
printf '%s\n' "$CAN_USB_SERIAL" > "$APP_DIR/CAN_USB_SERIAL"
printf '%s\n' "$CAN_USB_VENDOR_ID" > "$APP_DIR/CAN_USB_VENDOR_ID"
printf '%s\n' "$CAN_USB_PRODUCT_ID" > "$APP_DIR/CAN_USB_PRODUCT_ID"
printf '%s\n' "$SWITCH_TX_ENABLED" > "$APP_DIR/SWITCH_TX_ENABLED"
printf '%s\n' "$SWITCH_RTR_ENABLED" > "$APP_DIR/SWITCH_RTR_ENABLED"

# Install the persistent service links before the first `exit 0`. Older revisions appended the block after `exit 0`, which made it unreachable.
# Remove any prior marker blocks wherever they occur, then insert one canonical
# block immediately before the first exit. Preserve all unrelated rc.local
# content and append the block if no exit statement exists.
if [ ! -f "$RC_LOCAL" ]; then
    printf '%s\n' '#!/bin/sh' 'exit 0' > "$RC_LOCAL"
fi
awk \
    -v main_marker="$MAIN_MARKER" \
    -v switch_marker="$SWITCH_MARKER" \
    -v main_cmd='[ -e /service/scheiber-gx ] || ln -s /data/scheiber-gx/service /service/scheiber-gx' \
    -v switch_cmd='[ -e /service/scheiber-switch ] || ln -s /data/scheiber-gx/service-switch /service/scheiber-switch' '
    $0 == main_marker || $0 == switch_marker { skip_next=1; next }
    skip_next { skip_next=0; next }
    !inserted && $0 ~ /^[[:space:]]*exit[[:space:]]+0[[:space:]]*$/ {
        print main_marker
        print main_cmd
        print switch_marker
        print switch_cmd
        inserted=1
    }
    { print }
    END {
        if (!inserted) {
            print main_marker
            print main_cmd
            print switch_marker
            print switch_cmd
        }
    }
' "$RC_LOCAL" > "$RC_LOCAL.tmp"
mv "$RC_LOCAL.tmp" "$RC_LOCAL"
chmod 755 "$RC_LOCAL"

[ -e "$SERVICE_LINK" ] || ln -s "$APP_DIR/service" "$SERVICE_LINK"
[ -e "$SWITCH_SERVICE_LINK" ] || ln -s "$APP_DIR/service-switch" "$SWITCH_SERVICE_LINK"

# Venus OS commonly provides daemontools/runit `svc` rather than the newer
# `sv` command. Search the usual locations in case it is outside root's PATH.
SVC="$(command -v svc 2>/dev/null || true)"
if [ -z "$SVC" ]; then
    for candidate in /command/svc /usr/bin/svc /bin/svc /sbin/svc; do
        if [ -x "$candidate" ]; then
            SVC="$candidate"
            break
        fi
    done
fi

if [ -n "$SVC" ]; then
    "$SVC" -d "$SWITCH_SERVICE_LINK" 2>/dev/null || true
    "$SVC" -d "$SERVICE_LINK" 2>/dev/null || true
    sleep 1
    rm -f /run/scheiber-can-if
    "$SVC" -u "$SERVICE_LINK"

    # The main service owns CAN discovery. Give it a short head start before
    # enabling the dependent switch process.
    attempt=0
    while [ "$attempt" -lt 10 ] && [ ! -s /run/scheiber-can-if ]; do
        attempt=$((attempt + 1))
        sleep 1
    done
    "$SVC" -u "$SWITCH_SERVICE_LINK"
else
    echo "WARNING: svc was not found; service links are installed and will start on boot." >&2
fi

# Auto-install or update the Node-RED flows (Anchor Auto, Bilge Alarms) if Node-RED is present
nodered_status="skipped (Node-RED flows not found)"
for candidate_flow in /data/home/nodered/.node-red/flows.json /data/nodered/flows.json /root/.node-red/flows.json; do
    if [ -f "$candidate_flow" ]; then
        if python3 -c "
import json, sys
flow_path = sys.argv[1]
template_paths = sys.argv[2:]
try:
    with open(flow_path, 'r', encoding='utf-8') as f:
        flows = json.load(f)
    for template_path in template_paths:
        with open(template_path, 'r', encoding='utf-8') as f:
            new_nodes = json.load(f)
        tab_ids = {n['id'] for n in new_nodes if n.get('type') == 'tab'}
        flows = [n for n in flows if n.get('z') not in tab_ids and n.get('id') not in tab_ids]
        flows.extend(new_nodes)
    with open(flow_path + '.bak', 'w', encoding='utf-8') as f:
        json.dump(flows, f, indent=2)
    with open(flow_path, 'w', encoding='utf-8') as f:
        json.dump(flows, f, indent=2)
except Exception as e:
    sys.exit(1)
" "$candidate_flow" "$APP_DIR/node-red-anchor-light-flow.json" "$APP_DIR/node-red-bilge-alarms-flow.json" 2>/dev/null; then
            chown nodered:nodered "$candidate_flow" 2>/dev/null || true
            chmod 644 "$candidate_flow" 2>/dev/null || true
            nodered_status="installed to $candidate_flow"
            if [ -n "$SVC" ]; then
                "$SVC" -t /service/node-red-venus 2>/dev/null || "$SVC" -t /service/node-red 2>/dev/null || true
            fi
            break
        fi
    fi
done

cat <<EOF
Scheiber GX services installed.

  mode:             $install_mode
  app:              $APP_DIR
  telemetry:        $SERVICE_LINK
  native switches:  $SWITCH_SERVICE_LINK
  CAN selector:     $CAN_IF
  CAN detected now: ${resolved_can_if:-pending}
  CAN USB serial:   ${CAN_USB_SERIAL:-not pinned}
  CAN USB ID:       ${CAN_USB_VENDOR_ID:-*}:${CAN_USB_PRODUCT_ID:-*}
  CAN bitrate:      $CAN_BITRATE bit/s
  switch CAN TX:    $SWITCH_TX_ENABLED
  switch RTR sync:  $SWITCH_RTR_ENABLED
  node-red flow:    $nodered_status
  bridge SHA-256:   $actual_bridge_sha
  rc.local:         $RC_LOCAL (service block before exit 0)
  telemetry log:    $APP_DIR/bridge.log
  switch log:       $APP_DIR/switch.log
  switch status:    $APP_DIR/switch-status.json

Next checks:
  cat /run/scheiber-can-if 2>/dev/null || true
  command -v svc 2>/dev/null || true
  tail -n 100 $APP_DIR/switch.log
  dbus -y com.victronenergy.switch.scheiber /Connected GetValue
  dbus -y com.victronenergy.switch.scheiber /Scheiber/SynchronizedOutputCount GetValue
EOF
