# Scheiber-to-NMEA 2000 mapping

Scheiber CAN and NMEA 2000 are separate CAN segments. Do not electrically join them even though both may operate at 250 kbit/s.

The preferred Cerbo architecture is now:

```text
Scheiber CAN (can2)
  -> cerbo/bridge.py
  -> Victron D-Bus
  -> Signal K Venus integration
  -> Signal K paths
  -> signalk-to-nmea2000
  -> NMEA 2000 / VE.Can
```

This avoids duplicating protocol decoding in two gateways and keeps the standard NMEA 2000 encoding in Signal K.

## Current mapping register

| Scheiber / Victron signal | NMEA 2000 PGN | Instance plan | Status |
|---|---:|---|---|
| Fresh water level + 600 L capacity | 127505 Fluid Level | **0**, Water | preferred Zeus3 mapping; PGN live-tested |
| Diesel tank 1 level + 500 L capacity | 127505 Fluid Level | **1**, Fuel | preferred Zeus3 mapping; PGN live-tested |
| Diesel tank 2 level + 500 L capacity | 127505 Fluid Level | **2**, Fuel | preferred Zeus3 mapping; PGN live-tested |
| Generator starter battery voltage | 127508 Battery Status | assign unused battery instance | recommended next; source field strong |
| Six house battery voltages | 127508 Battery Status | deliberate unique instances | voltage confirmed; optional |
| Six house battery SoC values | 127506 DC Detailed Status | same house-battery instances | SoC confirmed for this installation; optional |
| Six house battery currents | 127508 Battery Status | same instances | **defer**; x0.1 A scale remains candidate |
| Engine start battery A/B voltage | 127508 Battery Status | assign after port/starboard validation | **defer**; identity/scale experimental |
| Charger status | 127507 Charger Status | charger instances 0-2 | candidate; state bits incomplete |
| Generator / AC input voltage and frequency | 127503 AC Input Status | intentional source/line model required | defer until standard topology mapping is defined |
| AC output voltage/frequency | 127504 AC Output Status | intentional output model required | defer |
| Source selector state | standard AC/source model or binary status | TBD | receive-side mapping known; do not force into an unrelated PGN |
| Source selector control | — | — | disabled; do not transmit Scheiber source-request frames |
| Generator START/STOP control | — | — | keep in Victron connected-genset manager; do not expose as generic NMEA control |

## Live tank validation

The Venus-derived Signal K sources are:

```text
tanks.freshWater.90
tanks.fuel.91
tanks.fuel.92
```

The first successful NMEA 2000 test used instances 6/7/8:

```text
tanks.freshWater.90 -> PGN 127505, instance 6, Water
tanks.fuel.91       -> PGN 127505, instance 7, Fuel
tanks.fuel.92       -> PGN 127505, instance 8, Fuel
```

Live loopback on the Cerbo NMEA 2000 connection was observed as:

```text
tanks.freshWater.6  source n2k-on-ve.can-socket.209 (127505)
tanks.fuel.7        source n2k-on-ve.can-socket.210 (127505)
tanks.fuel.8        source n2k-on-ve.can-socket.211 (127505)
```

The looped-back values matched the Venus values, including the corrected SI capacities:

```text
Fresh:    74%, 0.600 m3
Diesel 1: 63%, 0.500 m3
Diesel 2: 79%, 0.500 m3
```

That proves PGN 127505 output and VE.Can/NMEA 2000 loopback. The observed source addresses `209/210/211` are not tank instances and must not be treated as stable identifiers.

### Preferred Zeus3 instances

B&G Zeus3 receives PGN 127505 and its installation documentation states a maximum of five Fluid Level tanks. To maximize compatibility with the Zeus fuel/tank UI, use low unused instances 0/1/2 for the final configuration:

```text
tanks.freshWater.90 -> PGN 127505, instance 0, Water
tanks.fuel.91       -> PGN 127505, instance 1, Fuel
tanks.fuel.92       -> PGN 127505, instance 2, Fuel
```

Check Signal K Source Discovery first if other NMEA 2000 tank sources are later added to the vessel.

See [`SIGNALK_NMEA2000.md`](SIGNALK_NMEA2000.md) for Signal K configuration, Zeus3 compatibility, verification, and recommended next data.

## Safety defaults

- Keep the proprietary Scheiber bus isolated on its own CAN interface.
- Never forward proprietary CAN IDs unchanged onto NMEA 2000.
- The production bridge transmits only the live-tested Scheiber generator START/STOP command; Signal K/NMEA output is telemetry-only for the mappings documented here.
- Do not enable source-selector transmission.
- Do not publish candidate battery current or experimental engine-battery data as authoritative NMEA 2000 values.
