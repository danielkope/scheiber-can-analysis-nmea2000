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

Anchor Light, Fresh Water Pump and both bilges use the native three-state GX
control. For the bilges this means **OFF / AUTO / ON**, where `ON` is the
Scheiber MANUAL/forced mode. Actual motor-running feedback is independent of
the selected mode and is also published for the freshwater pump and both bilge
pumps.

The service never assumes that an output is OFF. At startup every physical
state is `UNKNOWN`; the service listens for the six paired state frames and
issues CAN RTR state requests. Writes are rejected until the relevant state is
known.

The physical keys are momentary events rather than explicit ON/OFF commands.
A requested state is therefore implemented by:

1. comparing desired state with synchronized CAN feedback;
2. transmitting one captured-style `0x04001808` key press;
3. transmitting the matching release after approximately 150 ms;
4. waiting for authoritative output-state feedback;
5. advancing only after the expected state is observed.

No direct `CMD_S_TOR` output-forcing command is used, so Scheiber interlocks
remain authoritative, including the observed steaming-light/navigation-light
dependency.

## Canonical runtime files

```text
cerbo/bridge.py                     existing generator/telemetry bridge
cerbo/scheiber_switch_protocol.py   pure switch protocol and state planner
cerbo/switch_service.py             native D-Bus/SocketCAN switch service
cerbo/service/run                   telemetry runit wrapper
cerbo/service-switch/run            switch-service runit wrapper
cerbo/install.sh                    transactional installer/updater
cerbo/uninstall.sh                  disables both services
```

The existing generator bridge remains version `5.4.2`, with canonical SHA-256:

```text
6c25ce4b095385217564fc6bf6fdc843dfefd835993d643843811e7f0f737097
```

## Fresh installation

SSH to the Cerbo as `root` and run:

```bash
mkdir -p /data/scheiber-gx-installer
cd /data/scheiber-gx-installer

wget -O install.sh \
  https://raw.githubusercontent.com/danielkope/scheiber-can-analysis-nmea2000/main/cerbo/install.sh
chmod +x install.sh

CAN_IF=can2 CAN_BITRATE=250000 \
SWITCH_TX_ENABLED=1 SWITCH_RTR_ENABLED=1 \
./install.sh
```

`SWITCH_TX_ENABLED=1` is the initial field-test configuration requested for
this implementation. Set it to `0` for receive-only UI validation. The value is
persisted under `/data/scheiber-gx` and used by the switch runit service.

For a PR branch or checked-out repository, run the local installer instead:

```bash
cd /path/to/scheiber-can-analysis-nmea2000
CAN_IF=can2 CAN_BITRATE=250000 \
SWITCH_TX_ENABLED=1 SWITCH_RTR_ENABLED=1 \
./cerbo/install.sh
```

The installer downloads or copies all runtime files to a staging directory,
compiles the Python sources, validates the pinned generator bridge hash, then
replaces the installed files and starts both runit services. A failed fetch,
compile or bridge checksum occurs before the live files are replaced.

## Verify the services

```bash
ip -details -statistics link show can2
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

The current switch-service snapshot is written to:

```text
/data/scheiber-gx/switch-status.json
```

## First active test

Do not begin with a bilge control. Use **Deck Floodlight** first:

1. confirm all 12 output states have synchronized;
2. command Deck Floodlight ON from the GX Switch pane;
3. verify a single press/release pair in `switch.log`;
4. verify the physical panel indicator and CAN state both change;
5. command it OFF and repeat;
6. test a physical-panel press and confirm the GX UI follows it.

Only after that path is reliable should the bilge mode transitions be tested.
The remaining evidence gap is a controlled AUTO-triggered bilge cycle to prove
that `0x02141808` bits 1 and 2 follow physical pump operation in AUTO exactly as
they do in MANUAL.

Read [`../docs/SWITCH_SERVICE_HANDOVER.md`](../docs/SWITCH_SERVICE_HANDOVER.md)
for the complete architecture, safety rules, validation sequence, rollback and
future Node-RED plan.

## Existing generator and tank verification

```bash
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

The tank services publish Victron D-Bus volume values in cubic metres while the
text formatter presents litres. Signal K/NMEA 2000 guidance remains in
[`../docs/SIGNALK_NMEA2000.md`](../docs/SIGNALK_NMEA2000.md).
