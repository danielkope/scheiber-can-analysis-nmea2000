# Signal K visibility and NMEA 2000 / Zeus3 integration

This document describes the live-tested path from the Scheiber CAN bridge on the Cerbo GX to the vessel NMEA 2000 / VE.Can network and to Signal K.

The important correction is that the three tank PGN 127505 messages are produced by the **native Victron NMEA2000-out feature**, not by the Signal K to NMEA 2000 plugin. Signal K is useful here as an observer on both sides of the bridge.

The Scheiber and NMEA 2000 CAN segments remain electrically separate. The proprietary Scheiber bus is connected through the SH-C30A on `can2`; VE.Can/NMEA 2000 remains on the Cerbo's normal marine CAN connection.

## Tank architecture

```text
Scheiber CAN (can2)
        |
        v
cerbo/bridge.py
        |
        v
native com.victronenergy.tank.* D-Bus services
        |
        +----------------------------+
        |                            |
        v                            v
Victron NMEA2000-out           Signal K Venus plugin
        |                            |
        v                            v
VE.Can / NMEA 2000             Signal K Venus paths
        |                            |
        +----> B&G Zeus3             +----> tanks.*.90/91/92
        |
        +----> Signal K n2k-on-ve.can-socket
                    |
                    +----> tanks.*.6/7/8 loopback
```

The Signal K **Victron Venus Plugin** should remain enabled because it makes the D-Bus services visible as Signal K paths. The standard **Signal K to NMEA 2000** plugin is not required for these tanks and should not also transmit PGN 127505 for the same values.

## Native Victron NMEA2000-out

Victron GX devices have an NMEA2000-out feature. When enabled on the VE.Can port, it represents suitable D-Bus devices as NMEA 2000 virtual devices. For tanks Victron uses PGN 127505 Fluid Level and automatically assigns each tank a unique Device instance and Tank instance. Victron intentionally makes those two instance values the same to simplify MFD compatibility.

Do not try to force the tank instances to 0/1/2 in Signal K. Leave the Victron-assigned instances in place unless there is a proven collision or an MFD-specific reason to change the GX configuration.

The current live instances are:

```text
Fresh Water    PGN 127505 instance 6
Diesel Tank 1  PGN 127505 instance 7
Diesel Tank 2  PGN 127505 instance 8
```

The corresponding observed NMEA 2000 source addresses were 209, 210 and 211. Those source addresses are **not** tank instances and are not stable configuration identifiers; NMEA 2000 address claiming can change them.

## Live tank data

The bridge publishes these native Victron services:

```text
com.victronenergy.tank.scheiber_fresh
com.victronenergy.tank.scheiber_diesel1
com.victronenergy.tank.scheiber_diesel2
```

The vessel capacities are:

```text
Fresh water    600 L = 0.600 m3
Diesel tank 1  500 L = 0.500 m3
Diesel tank 2  500 L = 0.500 m3
```

Signal K sees the D-Bus side through the Venus plugin as:

```text
tanks.freshWater.90
tanks.fuel.91
tanks.fuel.92
```

Current validated values:

```text
Fresh Water     74%   0.600 m3 capacity   0.444 m3 remaining
Diesel Tank 1   63%   0.500 m3 capacity   0.315 m3 remaining
Diesel Tank 2   79%   0.500 m3 capacity   0.395 m3 remaining
```

Signal K also sees the native NMEA 2000 output after it comes back from the VE.Can connection:

```text
tanks.freshWater.6.capacity      0.6 m3   n2k-on-ve.can-socket.209 (127505)
tanks.freshWater.6.currentLevel  74%      n2k-on-ve.can-socket.209 (127505)

tanks.fuel.7.capacity            0.5 m3   n2k-on-ve.can-socket.210 (127505)
tanks.fuel.7.currentLevel        63%      n2k-on-ve.can-socket.210 (127505)

tanks.fuel.8.capacity            0.5 m3   n2k-on-ve.can-socket.211 (127505)
tanks.fuel.8.currentLevel        79%      n2k-on-ve.can-socket.211 (127505)
```

This is the expected pattern for native GX NMEA2000-out: one Venus-derived path family and one NMEA-derived loopback path family.

## Cerbo configuration

On the GX device, make sure the VE.Can port uses a 250 kbit/s profile that includes VE.Can/NMEA 2000 and that **NMEA2000-out** is enabled.

Depending on Venus OS UI revision, the setting is under the VE.Can/CAN-port configuration, for example:

```text
Settings
  -> Connectivity
  -> VE.Can / CAN port
  -> NMEA2000-out = On
```

Do not configure `can2` for NMEA 2000. `can2` is the proprietary Scheiber bus.

## Signal K configuration

### Victron Venus Plugin

Keep **Victron Venus Plugin** enabled. No tank-instance configuration is required there.

It is doing its job when the Data Browser contains:

```text
tanks.freshWater.90.*
tanks.fuel.91.*
tanks.fuel.92.*
```

### NMEA 2000 data connection

Keep the existing VE.Can/NMEA 2000 input connection. On this Cerbo it appears as:

```text
n2k-on-ve.can-socket
```

It is doing its job when the Data Browser also contains the `(127505)` paths for instances 6/7/8.

### Signal K to NMEA 2000 plugin

For these three tanks, **Tank Levels (127505) should be disabled** in the `Signal K to NMEA 2000` plugin.

The upstream converter supports an optional per-tank mapping array, but if your installed UI shows only `Enabled`, `Resend`, and `Resend Duration` with no Tank Mapping fields, there is nothing useful to configure there for this installation. The native GX NMEA2000-out path is already producing the correct tank PGNs and is the preferred path for MFD integration.

Avoid creating a second PGN 127505 transmitter for the same tank values.

## B&G Zeus3

Victron documents Navico-family MFD integration using PGN 127505 for tanks. On the Zeus3, use the NMEA 2000 / Network data-source setup to verify and select the three tank sources.

Typical Navico menu path:

```text
Settings
  -> Network
  -> Sources
  -> Advanced
  -> Data source selection
```

The three tank virtual devices should appear there. Selecting a tank source should expose details such as fluid type and source/device information.

Important points:

- keep the bridge fluid types as generic **Water** and **Fuel** for broad MFD compatibility;
- do not use NMEA source addresses 209/210/211 as permanent identifiers;
- let the GX keep its automatically assigned tank instances 6/7/8;
- label or rename the tanks on the Zeus3 itself if needed; Victron notes that MFDs do not generally use the Victron custom tank name automatically;
- add the three fluid-level values to an Instruments/dashboard page and compare them with Signal K before relying on the plotter's fuel calculations.

Expected current values are:

```text
Fresh Water     74% of 600 L = 444 L
Diesel Tank 1   63% of 500 L = 315 L
Diesel Tank 2   79% of 500 L = 395 L
```

## Verification

### D-Bus

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

### Signal K Venus side

Search `tanks` and confirm:

```text
tanks.freshWater.90.*
tanks.fuel.91.*
tanks.fuel.92.*
```

### NMEA 2000 loopback

Confirm:

```text
tanks.freshWater.6.*  ... (127505)
tanks.fuel.7.*        ... (127505)
tanks.fuel.8.*        ... (127505)
```

The NMEA-derived levels/capacities should match the Venus-derived values within normal update timing.

## Recommended next NMEA 2000 data

Before enabling any Signal K-to-NMEA conversion for batteries, first inspect whether Victron NMEA2000-out is already exporting the bridge's native `com.victronenergy.battery.*` services. Search the Signal K Data Browser for:

```text
electrical.batteries
```

and look specifically for `n2k-on-ve.can-socket` sources using PGN 127508/127506.

The generator starter battery is the best next candidate because `0x00501020` bytes 0-1 LE x0.1 V is a strong mapping. House battery voltage and SoC are also established for this installation, but house current remains a candidate scale. Engine A/B battery identity and scale remain experimental and should not be put on NMEA 2000 yet.

## References

- Victron Cerbo GX manual, Marine MFD integration by NMEA 2000: <https://www.victronenergy.com/media/pg/Cerbo_GX/en/marine-mfd-integration-by-nmea-2000.html>
- Victron Marine Integration Guide: <https://www.victronenergy.com/live/ve.can:nmea-2000:start>
- Signal K server configuration: <https://github.com/SignalK/signalk-server/blob/master/docs/setup/configuration.md>
- Signal K to NMEA 2000 tank converter: <https://github.com/SignalK/signalk-to-nmea2000/blob/master/conversions/tanks.js>
