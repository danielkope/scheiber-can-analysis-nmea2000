# Proposed Scheiber-to-NMEA 2000 mapping

This is a gateway design, not a direct electrical bridge. Scheiber CAN and NMEA 2000 must remain separate CAN segments with separate interfaces.

| Scheiber signal | Proposed NMEA 2000 PGN | Instance plan | Status |
|---|---:|---|---|
| Water level and 600 L capacity | 127505 Fluid Level | fluid=water, instance 0 | ready after gateway implementation |
| Diesel 1 level and 500 L capacity | 127505 Fluid Level | fluid=fuel, instance 1 | ready after gateway implementation |
| Diesel 2 level and 500 L capacity | 127505 Fluid Level | fluid=fuel, instance 2 | ready after gateway implementation |
| Six house battery voltages | 127508 Battery Status | instances 0-5 | voltage ready; current/temperature/SoC need validation |
| Port engine start battery | 127508 Battery Status | instance 6 | physical source ID unresolved |
| Starboard engine start battery | 127508 Battery Status | instance 7 | physical source ID unresolved |
| Generator start battery | 127508 Battery Status | instance 8 | likely linked to 25 A charger, not proven |
| Battery SoC / remaining capacity | 127506 DC Detailed Status | same instances | only after field-3 validation |
| Charger status/configuration | 127507 / 127510 | charger instances 0-2 | charger families identified; state bits incomplete |
| AC input voltage/frequency | 127503 AC Input Status | source/line instances by panel | voltage/frequency mostly ready |
| AC output voltage/frequency | 127504 AC Output Status | output instances by panel | voltage/frequency mostly ready |
| Source selectors | 127501 Binary Switch Bank Status | three mutually exclusive channels per panel | status mapping possible |
| Source selector control | 127502 Switch Bank Control | same channels | disabled by default; safety validation required |
| Generator START/STOP command (`0x02460B88`, 1/2) | 127514 AGS Status/Command or guarded proprietary gateway action | generator instance 0 | semantic mapping confirmed; outbound control disabled pending safety validation |
| Generator transition/state (`0x02140898`) | 127514 AGS Status or binary status | generator instance 0 | ramp direction only; do not confuse with direct command |

## Safety defaults

- Receive-only on the Scheiber bus.
- Dry-run JSON or log output before any NMEA 2000 transmit.
- Never forward proprietary CAN IDs unchanged onto NMEA 2000.
- Never enable generator or source-selector transmission until interlocks, acknowledgements, timeout behavior, and fail-safe OFF behavior are independently validated.
