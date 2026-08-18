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

## Fresh installation on a Cerbo GX

SSH to the Cerbo as `root` and run:

```bash
mkdir -p /data/scheiber-gx-installer
cd /data/scheiber-gx-installer

wget -O install.sh \
  https://raw.githubusercontent.com/danielkope/scheiber-can-analysis-nmea2000/main/cerbo/install.sh
chmod +x install.sh

CAN_IF=can2 CAN_BITRATE=250000 ./install.sh
```

The installer downloads the complete canonical `cerbo/bridge.py` and `cerbo/service/run` from the repository, validates the Python source and pinned checksum, installs them under `/data/scheiber-gx`, creates/persists the runit service link, and starts the service.

## Update an existing installation

Use the **same installer**. Re-download `install.sh` first so an older local installer cannot retain obsolete packaging logic:

```bash
cd /data/scheiber-gx-installer

wget -O install.sh \
  https://raw.githubusercontent.com/danielkope/scheiber-can-analysis-nmea2000/main/cerbo/install.sh
chmod +x install.sh

CAN_IF=can2 CAN_BITRATE=250000 ./install.sh
```

For an update, the installer:

1. downloads the entire current `cerbo/bridge.py` to a temporary file;
2. compiles it with `python3 -m py_compile`;
3. verifies the pinned SHA-256;
4. downloads the runit `service/run` wrapper;
5. backs up the installed runtime as `/data/scheiber-gx/bridge.py.previous`;
6. replaces `/data/scheiber-gx/bridge.py` with the complete verified repository script;
7. restarts `/service/scheiber-gx` using `svc`.

A failed download, compile, or checksum occurs before the installed bridge is replaced.

## Install from a checked-out repository

If the repository has already been cloned/copied to the Cerbo:

```bash
cd /path/to/scheiber-can-analysis-nmea2000
CAN_IF=can2 CAN_BITRATE=250000 ./cerbo/install.sh
```

The installer uses the local `cerbo/bridge.py` and `cerbo/service/run` when they are present.

## Verify the installed runtime

```bash
sha256sum /data/scheiber-gx/bridge.py
head -n 10 /data/scheiber-gx/bridge.py

tail -n 80 /data/scheiber-gx/bridge.log

dbus -y com.victronenergy.genset.scheiber /Connected GetValue
```

For bridge 5.4.2, the expected SHA-256 is:

```text
6c25ce4b095385217564fc6bf6fdc843dfefd835993d643843811e7f0f737097
```

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

Example live values after the unit fix:

```text
Fresh:    Level 74  Capacity 0.600  Remaining 0.444
Diesel 1: Level 63  Capacity 0.500  Remaining 0.315
Diesel 2: Level 79  Capacity 0.500  Remaining 0.395
```

## Signal K / NMEA 2000

When Signal K is installed on the Cerbo, the native Victron tank services are visible through the Venus integration and can be forwarded to the vessel NMEA 2000 network using the standard `signalk-to-nmea2000` plugin.

The three tanks have been live-validated as PGN 127505 Fluid Level on the Cerbo VE.Can/NMEA 2000 connection. See [`../docs/SIGNALK_NMEA2000.md`](../docs/SIGNALK_NMEA2000.md) for the current instance mapping, loopback verification, and B&G Zeus3 display guidance.

Read [`../docs/CERBO_GX_INTEGRATION.md`](../docs/CERBO_GX_INTEGRATION.md) for wiring, D-Bus architecture, generator lifecycle, diagnostics, rollback, and the post-stop `OFF_IDLE` restart caveat.
