# Cerbo GX integration package

This directory contains the active Venus OS integration for the Scheiber
Multibloc V8 network. The passive analysis tools elsewhere in the repository
remain read-only.

The installer deploys two independent runit services that share the same
SocketCAN interface:

| Service | D-Bus service | Purpose |
|---|---|---|
| `scheiber-gx` | `com.victronenergy.genset.scheiber` plus tank/battery services | Existing field-tested generator and telemetry bridge |
| `scheiber-switch` | `com.victronenergy.switch.scheiber` | Native GX switchboard controls and pump-running feedback |

Keeping the switch service separate avoids destabilising the generator bridge
while the newly decoded control-panel path is field-validated.

## Native GX switchboard

The switch service publishes ten logical controls:

- Electronics
- Deck Floodlight
- Navigation Lights
- Anchor Light
- Steaming Light
- Port Bilge Pump
- Starboard Bilge Pump
- Fresh Water Pump
- Fridge Unit
- General Lighting

Anchor Light and both bilges use the native three-state GX control.

For each bilge the physical modes are:

```text
OFF     AUTO=0  MANUAL=0
AUTO    AUTO=1  MANUAL=0
MANUAL  AUTO=1  MANUAL=1
```

The GX row presents **OFF / AUTO / ON**, where `ON` is Scheiber MANUAL/forced
pumping. The ON segment also acts as the physical pump-activity lamp:

```text
OFF, stopped       Off
AUTO, idle         Auto
AUTO, pumping      Auto + On
MANUAL             On
```

Actual activity comes from `0x02141808`, not from the selected mode. It is also
published as a separate read-only activity card for each bilge.

Fresh Water Pump is a simple **OFF / ON** enable. When ON, the existing pressure
switch automatically starts the motor as taps are opened. A separate activity
card displays `Standby` or `ACTIVE` from `0x02141808` bit 0.

The service never assumes an output is OFF. At startup every physical state is
`UNKNOWN`; the service listens for the six paired state frames and issues CAN
RTR state requests. Writes are rejected until the relevant state is known.

The physical keys are momentary events rather than explicit ON/OFF commands. A
requested state is implemented by comparing desired state with synchronized CAN
feedback, transmitting one captured-style `0x04001808` press/release pair, and
waiting for authoritative output-state feedback. No direct `CMD_S_TOR` output
forcing is used, so Scheiber interlocks remain authoritative.

## Stable USB-CAN discovery

The Linux name assigned to the candleLight/`gs_usb` adapter is not stable. The
same physical adapter may be `can0`, `can1`, or `can2` after a reboot. The
integration therefore does not persist a boot-specific `canN` name by default.

`resolve_can_interface.py` discovers the current interface using:

1. driver `gs_usb`;
2. exact USB serial number when configured;
3. optional USB vendor/product IDs;
4. a fail-closed rule if more than one device matches.

The main service is the single owner of discovery and CAN configuration. After
bringing the interface up, it atomically publishes the selected name to:

```text
/run/scheiber-can-if
```

The switch service waits for that file and uses the same interface. It never
independently guesses a device.

Observed adapter identity on this vessel:

```text
driver:       gs_usb
USB VID:PID:  1d50:606f
USB serial:   0025003C5457530220383638
```

The native Cerbo CAN controller is `sun4i_can` and is deliberately excluded
from automatic `gs_usb` selection.

## Canonical runtime files

```text
cerbo/bridge.py                     existing generator/telemetry bridge
cerbo/resolve_can_interface.py      stable USB-CAN identity resolver
cerbo/scheiber_switch_protocol.py   pure switch protocol and state planner
cerbo/switch_service.py             native D-Bus/SocketCAN switch service
cerbo/service/run                   telemetry runit wrapper and CAN owner
cerbo/service-switch/run            switch-service runit wrapper
cerbo/install.sh                    transactional installer/updater
cerbo/uninstall.sh                  disables both services
```

The existing generator bridge remains version `5.4.2`, with canonical SHA-256:

```text
6c25ce4b095385217564fc6bf6fdc843dfefd835993d643843811e7f0f737097
```

## Fresh installation or update with curl

SSH to the Cerbo as `root`. For a pinned PR/commit build:

```sh
mkdir -p /data/scheiber-gx-installer
cd /data/scheiber-gx-installer

REF="<commit-sha>"
RAW_BASE="https://raw.githubusercontent.com/danielkope/scheiber-can-analysis-nmea2000/${REF}/cerbo"

curl -fL "${RAW_BASE}/install.sh" -o install.sh
chmod 755 install.sh

CAN_IF=auto \
CAN_USB_SERIAL=0025003C5457530220383638 \
CAN_USB_VENDOR_ID=1d50 \
CAN_USB_PRODUCT_ID=606f \
CAN_BITRATE=250000 \
SWITCH_TX_ENABLED=1 \
SWITCH_RTR_ENABLED=1 \
RAW_BASE="${RAW_BASE}" \
./install.sh
```

`CAN_IF=auto` is preferred. If exactly one `gs_usb` device is connected and no
serial is supplied, the installer auto-enrols its USB serial. Pinning the serial
is still recommended because it remains unambiguous if another USB-CAN adapter
is added later.

An explicit interface such as `CAN_IF=can0` is supported for diagnostics, but
it reintroduces boot-order dependence and should not be the normal vessel
configuration.

`SWITCH_TX_ENABLED=1` enables active panel-key CAN commands. Set it to `0` for
receive-only UI validation. `SWITCH_RTR_ENABLED=1` permits startup state-query
frames.

The installer stages and compiles all Python sources, validates the pinned
bridge hash, replaces the runtime files, persists the selector and USB identity,
and starts both runit services. A failed fetch, compile, or checksum happens
before the live files are replaced.

## Verify the services

```sh
cat /run/scheiber-can-if
ip -details -statistics link show "$(cat /run/scheiber-can-if)"
sv status /service/scheiber-gx /service/scheiber-switch

tail -n 100 /data/scheiber-gx/bridge.log
tail -n 100 /data/scheiber-gx/switch.log

dbus -y com.victronenergy.switch.scheiber /Connected GetValue
dbus -y com.victronenergy.switch.scheiber \
  /Scheiber/SynchronizedOutputCount GetValue
dbus -y com.victronenergy.switch.scheiber \
  /SwitchableOutput/deck_floodlight/State GetValue
dbus -y com.victronenergy.switch.scheiber \
  /GenericInput/bilge_port_running/Value GetValue
```

The expected synchronized output count is `12`. The current switch-service
snapshot is written to:

```text
/data/scheiber-gx/switch-status.json
```

## Existing generator and tank verification

```sh
dbus -y com.victronenergy.genset.scheiber /Connected GetValue

for s in \
  com.victronenergy.tank.scheiber_fresh \
  com.victronenergy.tank.scheiber_diesel1 \
  com.victronenergy.tank.scheiber_diesel2
do
  echo "===== $s ====="
  for p in Level Capacity Remaining FluidType CustomName; do
    printf '%-12s ' "$p:"
    dbus -y "$s" "/$p" GetValue
  done
done
```

## Node-RED Anchor Light Sunset/Sunrise automation

The repository includes a ready-to-use Node-RED flow for Anchor Light Auto mode:
[`node-red-anchor-light-flow.json`](./node-red-anchor-light-flow.json).

### Behavior
- Listens to `/SwitchableOutput/anchor_light/Auto` on `com.victronenergy.switch.scheiber`.
- When `Auto = 0` (Manual), the flow is inactive and preserves manual switch control.
- When `Auto = 1` (Auto mode):
  - Reads GPS position from `com.victronenergy.gps` (`/Position/Latitude`, `/Position/Longitude`) with fallback coordinates.
  - Computes astronomical sunrise and sunset times (NOAA solar algorithm).
  - Automatically commands `/SwitchableOutput/anchor_light/State` to `1` (ON) at sunset (15 min buffer) and `0` (OFF) at sunrise (30 min buffer).
  - Prevents command loops by only writing to D-Bus when state changes are needed.

Read [`../docs/SWITCH_SERVICE_HANDOVER.md`](../docs/SWITCH_SERVICE_HANDOVER.md)
for the architecture, safety rules, field evidence, rollback procedure, and
Node-RED alarm/automation plan.
