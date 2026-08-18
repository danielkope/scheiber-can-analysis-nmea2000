# Cerbo GX bridge package

This directory contains the optional active Victron integration. The passive analyzer elsewhere in the repository remains read-only.

## Canonical source

The complete production bridge is checked in directly as:

```text
cerbo/bridge.py
```

There is no generated or encoded runtime source and no install-time patching. Review `bridge.py` directly; the installer copies that exact file to the Cerbo after compiling it and verifying its SHA-256.

Current bridge version:

```text
5.4.2
```

Current `cerbo/bridge.py` SHA-256:

```text
6c25ce4b095385217564fc6bf6fdc843dfefd835993d643843811e7f0f737097
```

Bridge 5.4.2 is the field-tested 5.4.1 generator integration with the tank D-Bus unit correction applied directly in the source. Generator START/STOP CAN semantics and manager-recovery behavior are unchanged.

## Tank D-Bus units

Vessel capacities remain configured in litres for readability:

```text
Fresh water:   600 L
Diesel tank 1: 500 L
Diesel tank 2: 500 L
```

Victron D-Bus uses cubic metres for `/Capacity` and `/Remaining`, so `bridge.py` publishes:

```text
Fresh water capacity:   0.600 m3
Diesel tank 1 capacity: 0.500 m3
Diesel tank 2 capacity: 0.500 m3
```

`/Remaining` is calculated from the cubic-metre capacity and `/Level` percentage. The D-Bus text formatter still presents the volume in litres for a human-readable GX display.

## Install on a Cerbo GX

As root, after the PR is merged:

```bash
mkdir -p /data/scheiber-gx-installer
cd /data/scheiber-gx-installer
wget -O install.sh \
  https://raw.githubusercontent.com/danielkope/scheiber-can-analysis-nmea2000/main/cerbo/install.sh
chmod +x install.sh
CAN_IF=can2 CAN_BITRATE=250000 ./install.sh
```

To test the open branch before merge:

```bash
BRANCH=fix/tank-dbus-units
BASE="https://raw.githubusercontent.com/danielkope/scheiber-can-analysis-nmea2000/$BRANCH/cerbo"
wget -O install.sh "$BASE/install.sh"
chmod +x install.sh
RAW_BASE="$BASE" CAN_IF=can2 CAN_BITRATE=250000 ./install.sh
```

The installer downloads the complete `bridge.py`, compiles it, verifies its SHA-256, backs up the currently installed script as `/data/scheiber-gx/bridge.py.previous`, installs the runit wrapper, persists the `/service/scheiber-gx` link through `/data/rc.local`, and restarts the service with `svc`.

A failed download, compile, or checksum occurs before the installed bridge is replaced.

## Verify the corrected tank units

```bash
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

For levels of 74%, 62%, and 79%, the corresponding volume values should be approximately:

```text
Fresh:    Capacity 0.600  Remaining 0.444
Diesel 1: Capacity 0.500  Remaining 0.310
Diesel 2: Capacity 0.500  Remaining 0.395
```

Read [`../docs/CERBO_GX_INTEGRATION.md`](../docs/CERBO_GX_INTEGRATION.md) for wiring, D-Bus architecture, generator lifecycle, diagnostics, rollback, and the post-stop `OFF_IDLE` restart caveat.
