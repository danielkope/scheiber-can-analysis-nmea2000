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

The current vessel capacities are:

```text
Fresh water    600 L = 0.600 m3
Diesel tank 1  500 L = 0.500 m3
Diesel tank 2  500 L = 0.500 m3
```

Signal K base units are SI: tank capacity and remaining volume are in cubic metres and tank level is a ratio internally. The current bridge publishes Victron `/Capacity` and `/Remaining` in cubic metres so the Venus -> Signal K conversion is dimensionally correct.

### Current live Signal K -> NMEA 2000 mapping

The tested `signalk-to-nmea2000` configuration maps the three Venus-derived paths to PGN 127505 Fluid Level as follows:

| Signal K source path | Fluid type | NMEA 2000 tank instance | Capacity |
|---|---|---:|---:|
| `tanks.freshWater.90` | Water | 6 | 600 L |
| `tanks.fuel.91` | Fuel | 7 | 500 L |
| `tanks.fuel.92` | Fuel | 8 | 500 L |

Observed live loopback through the Cerbo NMEA 2000 connection:

```text
tanks.freshWater.6.capacity      0.6 m3   n2k-on-ve.can-socket.209 (127505)
tanks.freshWater.6.currentLevel  74%      n2k-on-ve.can-socket.209 (127505)

tanks.fuel.7.capacity            0.5 m3   n2k-on-ve.can-socket.210 (127505)
tanks.fuel.7.currentLevel        63%      n2k-on-ve.can-socket.210 (127505)

tanks.fuel.8.capacity            0.5 m3   n2k-on-ve.can-socket.211 (127505)
tanks.fuel.8.currentLevel        79%      n2k-on-ve.can-socket.211 (127505)
```

This loopback is important: it proves that the values have left the Venus/Signal K source side, were encoded as PGN 127505 on the NMEA 2000 connection, and were decoded back by Signal K from the bus.

`209`, `210`, and `211` above are observed NMEA 2000 source addresses. They are **not** tank instances and should not be used as stable configuration identifiers. NMEA 2000 source addresses can change after address claiming; the PGN 127505 tank instances are `6`, `7`, and `8`.

## Configure Signal K

Use the standard **Signal K to NMEA 2000** plugin.

In the Signal K Admin UI:

1. Confirm the NMEA 2000 data connection is the existing VE.Can/NMEA 2000 connection (on the tested Cerbo it appears as `n2k-on-ve.can-socket`).
2. Enable **Signal K to NMEA 2000**.
3. Enable **Tank Levels (127505)**.
4. Add these mappings:

```text
tanks.freshWater.90 -> instance 6
tanks.fuel.91       -> instance 7
tanks.fuel.92       -> instance 8
```

The upstream `signalk-to-nmea2000` tank converter uses each selected `tanks.<type>.<id>.currentLevel` and `.capacity` value, converts the Signal K level ratio to percent, converts capacity from m3 to litres, and emits PGN 127505 with the configured tank instance.

### Instance conflicts

Before changing the current instance numbers, check **Data -> Source Discovery** in Signal K for existing NMEA 2000 tank devices and instance conflicts.

The current 6/7/8 mapping is live and conflict-free on the tested installation. Keep it unless the chartplotter or another device requires a different assignment.

If an older display does not expose these tanks despite receiving PGN 127505, a compatibility test with lower unused instances such as 0/1/2 is reasonable, but only after confirming those instances are not already used elsewhere on the NMEA 2000 network.

## B&G Zeus3 compatibility

B&G's published Zeus3 specifications list **PGN 127505 Fluid Level** as a supported receive PGN. They also list **127506 DC Detailed Status** and **127508 Battery Status**, which is useful for later battery integration.

Therefore the current tank output uses the correct standard PGN family for Zeus3. The remaining work on the plotter is display/source configuration rather than a proprietary B&G translation.

### What to configure on the Zeus3

Exact menu labels vary with Zeus3 software revision, but the expected setup is:

- verify the NMEA 2000 network/device list sees the incoming tank/fluid-level sources;
- add Fluid Level / Water and Fuel tank data to an Instruments page or instrument bar;
- for the Zeus fuel utility, configure the vessel for **two fuel tanks** with **1000 L total fuel capacity** and use tank-level sensor data when that option is available;
- keep fresh water separate from the fuel utility and display it as a water/fluid-level instrument;
- if automatic source selection chooses the wrong source, use the Zeus advanced data-source selection for the relevant fuel/fluid-level item.

Do not key any Zeus setup to the observed CAN source addresses 209/210/211. Use the fluid type and tank instance/data source presented by the NMEA 2000 data model.

### Expected Zeus3 values from the current live data

At the time of the live validation:

```text
Fresh Water     74% of 600 L = 444 L remaining
Diesel Tank 1   63% of 500 L = 315 L remaining
Diesel Tank 2   79% of 500 L = 395 L remaining
```

PGN 127505 carries level and capacity. A Zeus3 can therefore display level and can derive/display the corresponding volume if its instrument presentation supports it.

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

In **Data -> Data Browser**, search for `tanks` and confirm the Venus-derived paths:

```text
tanks.freshWater.90.*
tanks.fuel.91.*
tanks.fuel.92.*
```

### 3. Verify NMEA 2000 loopback

With the tank output plugin enabled, the same Data Browser search should also show NMEA 2000-derived paths such as:

```text
tanks.freshWater.6.*  ... (127505)
tanks.fuel.7.*        ... (127505)
tanks.fuel.8.*        ... (127505)
```

The NMEA-derived values should match the Venus-derived values within normal update timing.

### 4. Verify on Zeus3

Add the three fluid-level values to an Instruments page. Compare the displayed percentages/capacities against Signal K before relying on the plotter presentation.

## Recommended next NMEA 2000 data

### Generator starter battery: recommended next

`0x00501020` bytes 0-1 LE x0.1 V is a strong generator-starter-voltage mapping and is already published by the Cerbo bridge as a Victron battery service. Zeus3 supports PGN 127508 Battery Status, so this is the best next battery value to expose after assigning an unused NMEA 2000 battery instance.

### Six house batteries: optional

House battery voltage and SoC are established for this installation. If individual-cell/battery visibility on the chartplotter is useful, publish voltage using PGN 127508 and SoC using PGN 127506 with a deliberate instance plan.

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
