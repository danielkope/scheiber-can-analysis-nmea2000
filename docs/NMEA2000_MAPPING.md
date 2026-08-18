# Scheiber-to-NMEA 2000 mapping

Scheiber CAN and NMEA 2000 are separate CAN segments. Do not electrically join them even though both may operate at 250 kbit/s.

## Production architecture

The tested Cerbo path is:

```text
Scheiber CAN (can2)
  -> cerbo/bridge.py
  -> Victron D-Bus
  -> Venus OS native NMEA 2000-out
  -> VE.Can / NMEA 2000
  -> B&G Zeus3
```

Signal K runs alongside this path for observability:

```text
Victron D-Bus
  -> Victron Venus Plugin
  -> Signal K .90/.91/.92 tank paths

VE.Can / NMEA 2000
  -> n2k-on-ve.can-socket
  -> Signal K .6/.7/.8 PGN 127505 loopback
```

For the three tanks, do **not** add a second Signal K -> NMEA 2000 publisher. Native Venus OS output is already working.

## Current mapping register

| Scheiber / Victron signal | NMEA 2000 PGN | Instance plan | Status |
|---|---:|---|---|
| Fresh water level + 600 L capacity | 127505 Fluid Level | Venus-assigned instance **6**, Water | live on Zeus3 |
| Diesel tank 1 level + 500 L capacity | 127505 Fluid Level | Venus-assigned instance **7**, Fuel | live on Zeus3 |
| Diesel tank 2 level + 500 L capacity | 127505 Fluid Level | Venus-assigned instance **8**, Fuel | live on Zeus3 |
| Generator starter battery voltage | 127508 Battery Status | assign unused battery instance if intentionally exported | recommended next; source field strong |
| Six house battery voltages | 127508 Battery Status | deliberate unique instances | voltage confirmed; optional |
| Six house battery SoC values | 127506 DC Detailed Status | same house-battery instances | SoC confirmed for this installation; optional |
| Six house battery currents | 127508 Battery Status | same instances | **defer**; x0.1 A scale remains candidate |
| Engine start battery A/B voltage | 127508 Battery Status | assign after port/starboard validation | **defer**; identity/scale experimental |
| Charger status | 127507 Charger Status | charger instances TBD | candidate; state bits incomplete |
| Generator / AC input voltage and frequency | 127503 AC Input Status | intentional source/line model required | defer until standard topology mapping is defined |
| AC output voltage/frequency | 127504 AC Output Status | intentional output model required | defer |
| Source selector state | standard AC/source model or binary status | TBD | receive-side mapping known; do not force into unrelated PGNs |
| Source selector control | — | — | disabled; do not transmit Scheiber source-request frames |
| Generator START/STOP control | — | — | keep in Victron connected-genset manager; do not expose as generic NMEA control |

## Live tank validation

### Venus / Signal K source paths

```text
tanks.freshWater.90
tanks.fuel.91
tanks.fuel.92
```

These are the Signal K paths created from the native Victron D-Bus tank services. The numbers `90/91/92` are **not** the NMEA 2000 fluid instances.

### NMEA 2000 loopback

The live vessel network carries PGN 127505 and Signal K receives it back as:

```text
tanks.freshWater.6  source n2k-on-ve.can-socket.209 (127505)
tanks.fuel.7        source n2k-on-ve.can-socket.210 (127505)
tanks.fuel.8        source n2k-on-ve.can-socket.211 (127505)
```

The looped-back values match the Venus values and corrected SI capacities:

```text
Fresh:    71-74% during validation, 0.600 m3 capacity
Diesel 1: 62-63% during validation, 0.500 m3 capacity
Diesel 2: 79%,                    0.500 m3 capacity
```

The observed NMEA source addresses `209/210/211` are not tank instances and are not stable identifiers.

### B&G Zeus3 result

The Zeus3 successfully displayed the native Venus instances `6/7/8`. No renumbering to `0/1/2` was needed.

The critical final setup step was selecting the appropriate incoming fluid-level sources in the Zeus3 Network/Sources advanced data-source selection UI. Once PGN 127505 loopback is visible on the Cerbo, a blank Zeus tank field should be treated first as a source-selection problem, not as a reason to create another gateway or republish the tanks.

See [`SIGNALK_NMEA2000.md`](SIGNALK_NMEA2000.md) for the complete verification and troubleshooting runbook and [`INTEGRATION_RESULTS.md`](INTEGRATION_RESULTS.md) for field screenshots.

## Safety defaults

- Keep the proprietary Scheiber bus isolated on its own CAN interface.
- Never forward proprietary CAN IDs unchanged onto NMEA 2000.
- The production bridge transmits only the live-tested Scheiber generator START/STOP command.
- Keep source-selector transmission disabled.
- Do not publish candidate battery current or experimental engine-battery data as authoritative NMEA 2000 values.
