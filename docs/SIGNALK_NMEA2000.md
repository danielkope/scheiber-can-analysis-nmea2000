# Signal K to NMEA 2000 integration

This document describes the live-tested path from the Scheiber CAN bridge on the Cerbo GX into Signal K and then onto the vessel NMEA 2000 / VE.Can network.

The Scheiber and NMEA 2000 CAN segments remain electrically separate. The Scheiber bus is connected through the SH-C30A on `can2`; NMEA 2000 output goes through the existing Venus OS / Signal K NMEA 2000 connection, not through `can2`.

## Architecture

```text
Scheiber CAN (can2)
        |
        v
cerbo/bridge.py
        |
        v
Victron D-Bus services
        |
        v
Signal K Venus integration
        |
        v
Signal K paths
        |
        v
signalk-to-nmea2000
        |
        v
NMEA 2000 / VE.Can
        |
        +--> B&G Zeus3 and other NMEA 2000 displays
```

The production Scheiber bridge does not need to encode NMEA 2000 directly. It publishes native Victron services; Signal K already converts those services into standard Signal K paths, and the standard `signalk-to-nmea2000` plugin performs the NMEA 2000 encoding.

## Live-validated tank path

The three Scheiber tank services are:

```text
com.victronenergy.tank.scheiber_fresh
com.victronenergy.tank.scheiber_diesel1
com.victronenergy.tank.scheiber_diesel2
```

Signal K receives them from the Venus integration as:

```text
tanks.freshWater.90
tanks.fuel.91
tanks.fuel.92
```

The vessel capacities are:

```text
Fresh water    600 L = 0.600 m3
Diesel tank 1  500 L = 0.500 m3
Diesel tank 2  500 L = 0.500 m3
```

Signal K base units are SI: tank capacity and remaining volume are in cubic metres and tank level is a ratio internally. The current bridge publishes Victron `/Capacity` and `/Remaining` in cubic metres so the Venus -> Signal K conversion is dimensionally correct.

### First live NMEA 2000 loopback

The first successful `signalk-to-nmea2000` test used PGN 127505 instances 6/7/8:

| Signal K source path | Fluid type | Tested instance | Capacity |
|---|---|---:|---:|
| `tanks.freshWater.90` | Water | 6 | 600 L |
| `tanks.fuel.91` | Fuel | 7 | 500 L |
| `tanks.fuel.92` | Fuel | 8 | 500 L |

Signal K then decoded the transmitted PGNs back from the Cerbo NMEA 2000 connection:

```text
tanks.freshWater.6.capacity      0.6 m3   n2k-on-ve.can-socket.209 (127505)
tanks.freshWater.6.currentLevel  74%      n2k-on-ve.can-socket.209 (127505)

tanks.fuel.7.capacity            0.5 m3   n2k-on-ve.can-socket.210 (127505)
tanks.fuel.7.currentLevel        63%      n2k-on-ve.can-socket.210 (127505)

tanks.fuel.8.capacity            0.5 m3   n2k-on-ve.can-socket.211 (127505)
tanks.fuel.8.currentLevel        79%      n2k-on-ve.can-socket.211 (127505)
```

This proves the values left the Venus/Signal K source side, were encoded as PGN 127505 on the NMEA 2000 connection, and were decoded back by Signal K from that bus.

`209`, `210`, and `211` are observed NMEA 2000 source addresses. They are **not** tank instances and must not be used as stable tank identifiers. Source addresses can change through NMEA 2000 address claiming.

## Zeus3-compatible instance plan

NMEA 2000 PGN 127505 defines a fluid instance field, but B&G's Zeus3 installation documentation states that the Zeus3 supports a maximum of five Fluid Level tanks. It does not explicitly guarantee that arbitrary high fluid-instance numbers will participate in all of its fuel/tank UI functions.

For maximum Zeus3 compatibility, use the lowest three unused instances:

```text
tanks.freshWater.90 -> instance 0
tanks.fuel.91       -> instance 1
tanks.fuel.92       -> instance 2
```

The earlier 6/7/8 mapping remains useful evidence that PGN 127505 transmission and loopback work, but 0/1/2 is the preferred final mapping for this vessel unless an existing NMEA 2000 tank already occupies one of those instances.

Before changing instances, check Signal K **Data -> Source Discovery** and the Data Browser for any existing NMEA 2000 tank sources. In the live tank listing used for this project, no other NMEA 2000 fluid-level instances were present, so 0/1/2 are the intended Zeus3 mapping.

## Configure Signal K

Use the standard **Signal K to NMEA 2000** plugin.

In the Signal K Admin UI:

1. Confirm the NMEA 2000 data connection is the existing VE.Can/NMEA 2000 connection (on the tested Cerbo it appears as `n2k-on-ve.can-socket`).
2. Enable **Signal K to NMEA 2000**.
3. Enable **Tank Levels (127505)**.
4. Add the Zeus3-compatible mappings:

```text
tanks.freshWater.90 -> instance 0
tanks.fuel.91       -> instance 1
tanks.fuel.92       -> instance 2
```

The upstream `signalk-to-nmea2000` tank converter consumes each selected `tanks.<type>.<id>.currentLevel` and `.capacity`, converts the Signal K level ratio to percent, converts capacity from m3 to litres, and emits PGN 127505 with the configured tank instance and standard Water/Fuel type.

After saving/restarting the plugin, Signal K loopback should change to paths such as:

```text
tanks.freshWater.0.*  ... (127505)
tanks.fuel.1.*        ... (127505)
tanks.fuel.2.*        ... (127505)
```

The looped-back levels and capacities should continue to match the Venus-derived 90/91/92 paths.

## B&G Zeus3 compatibility

B&G's published Zeus3 specifications list **PGN 127505 Fluid Level** as a supported receive PGN. They also list **127506 DC Detailed Status** and **127508 Battery Status**, which is useful for later battery integration.

The Zeus3 installation manual's fuel-level section describes using Fluid Level devices, configuring the vessel's number of tanks, and setting tank location/fluid type/tank size for configurable Navico sensors. It notes a maximum of five Fluid Level tanks. Third-party/engine-gateway tank data can still be displayed even when the Zeus cannot configure that source itself.

Therefore our standard PGN 127505 representation is the correct protocol family for Zeus3; the 0/1/2 instance plan is chosen to stay within the most conservative interpretation of the Zeus3 tank implementation.

### Zeus3 setup

Exact labels can vary with Zeus3 software revision, but the setup should be along these lines:

- open the NMEA 2000 / Network device and data-source pages and verify incoming fluid-level data is present;
- in **Vessel Setup / Fuel**, configure **2 fuel tanks** and **1000 L total fuel capacity**;
- use tank-level sensor data for fuel remaining where the software offers that choice;
- add Fuel Level / Fluid Level data to an Instruments page or instrument bar;
- display fresh water separately as Water / Fluid Level rather than including it in the fuel calculation;
- if automatic source selection chooses another tank source, select the desired NMEA 2000 data source manually in the advanced source-selection UI.

Do not key any Zeus setup to observed CAN source addresses such as 209/210/211. Use the fluid type, tank instance, and data source presented by the NMEA 2000 model.

### Expected Zeus3 values from the current live data

At the time of validation:

```text
Fresh Water     74% of 600 L = 444 L remaining
Diesel Tank 1   63% of 500 L = 315 L remaining
Diesel Tank 2   79% of 500 L = 395 L remaining
```

PGN 127505 carries level and capacity, so the Zeus3 has the standard data needed to display percentage and, where its instrument presentation supports it, tank volume.

## Verification

### 1. Verify Victron D-Bus

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

Expected capacities are `0.6`, `0.5`, and `0.5` m3.

### 2. Verify Signal K Venus paths

In **Data -> Data Browser**, search for `tanks` and confirm:

```text
tanks.freshWater.90.*
tanks.fuel.91.*
tanks.fuel.92.*
```

### 3. Verify NMEA 2000 loopback

With the Zeus3-compatible instance mapping enabled, the same search should also show:

```text
tanks.freshWater.0.*  ... (127505)
tanks.fuel.1.*        ... (127505)
tanks.fuel.2.*        ... (127505)
```

The NMEA-derived values should match the Venus-derived values within normal update timing.

### 4. Verify on Zeus3

Add the three fluid-level values to an Instruments page and compare them with Signal K before relying on the plotter display or fuel calculations.

If PGN 127505 is visible in Signal K loopback at instances 0/1/2 but the Zeus3 does not expose the tanks, inspect Zeus Network/Data Sources and Vessel Setup before changing the gateway. At that point the remaining problem is Zeus configuration or source selection, not Scheiber decoding or NMEA 2000 encoding.

## Recommended next NMEA 2000 data

### Generator starter battery: recommended next

`0x00501020` bytes 0-1 LE x0.1 V is a strong generator-starter-voltage mapping and is already published by the Cerbo bridge as a Victron battery service. Zeus3 supports PGN 127508 Battery Status, so this is the best next battery value to expose after assigning an unused NMEA 2000 battery instance.

### Six house batteries: optional

House battery voltage and SoC are established for this installation. If individual-battery visibility on the chartplotter is useful, publish voltage using PGN 127508 and SoC using PGN 127506 with a deliberate instance plan.

Do not publish the house current field onto NMEA 2000 yet; its sign/offset are strong but the x0.1 A scale remains a candidate.

### Engine start batteries: defer

The two engine-battery CAN channels remain experimental for physical identity and voltage scale. Validate port/starboard identity and scale with one-engine-at-a-time crank tests before putting them on NMEA 2000.

### Generator AC / source state: defer

Zeus3 supports standard AC PGNs including 127503/127504, but the project should not publish those until the Scheiber AC-source topology and field semantics are intentionally mapped to the standard model. Source-selector control remains disabled.

## References

- B&G Zeus3 product specifications: <https://www.bandg.com/bg/type/chartplotter/bg-zeus3-9-mfdinsight/>
- B&G Zeus3 manuals index: <https://ww2.bandg.com/downloads-category/zeus3-chartplotters-manuals/>
- Signal K server NMEA 2000 configuration / Source Discovery: <https://github.com/SignalK/signalk-server/blob/master/docs/setup/configuration.md>
- Signal K to NMEA 2000 tank converter: <https://github.com/SignalK/signalk-to-nmea2000/blob/master/conversions/tanks.js>
