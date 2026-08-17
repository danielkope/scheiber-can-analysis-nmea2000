# 11. Nine-battery assignment status

| **Battery instance plan** | **Physical battery** | **Current source mapping** | **Status / next test** |
|---|---|---|---|
| 0-5 | Six house batteries | Six `0x060x0580` streams | Voltage ready; load each battery to assign physical order and calibrate current |
| 6 | Port engine start | Not isolated | Apply port starter load / start port engine and correlate |
| 7 | Starboard engine start | Not isolated | Apply starboard starter load / start starboard engine and correlate |
| 8 | Generator start | Not isolated; `0x1020`/25 A charger is best candidate | Load/start generator battery and correlate charger/DC fields |

The three charger device families must not be counted as three additional batteries. They may expose one or more starter-battery voltages within their telemetry, but the current capture cannot assign port, starboard, and generator batteries with confidence.

> **Best current architecture hypothesis:** `0x1008` is a 12 V / 60 A charger, `0x1010` is a 12 V / 40 A charger, and `0x1020` is a 12 V / 25 A charger. The 25 A unit is the strongest generator-battery charger candidate; 60 A and 40 A likely participate in house and engine battery charging. Verify against nameplates and controlled isolation.
