# 12.1 Mapping register — Confirmed

| **CAN ID** | **Bytes** | **Signal** | **Type / endian** | **Scale / unit** | **Confidence** | **Interpretation** |
|---|---|---|---|---|---|---|
| `0x02040580` | 0-1 | Water tank level | `uint16` / big | x1 % | high | Water tank level |
| `0x02040580` | 2-3 | Diesel tank 1 level | `uint16` / big | x1 % | high | Diesel tank 1 level |
| `0x02040580` | 4-5 | Diesel tank 2 level | `uint16` / big | x1 % | high | Diesel tank 2 level |
| `0x02420B90` | 0 | AC panel requested source | `uint8 enum` | `1=OFF, 2=SHORE, 4=GENERATOR` | high | Requested source selector state |
| `0x02400B90` | 0 | AC panel applied source | `uint8 enum` | `1=OFF, 2=SHORE, 4=GENERATOR` | high | Applied source selector state |
| `0x02420B88` | 0 | House panel requested source | `uint8 enum` | `1=OFF, 2=SHORE, 4=GENERATOR` | high | Requested source selector state |
| `0x02400B88` | 0 | House panel applied source | `uint8 enum` | `1=OFF, 2=SHORE, 4=GENERATOR` | high | Applied source selector state |
| `0x02460B88` | 0 | Generator external command | `uint8 enum` | `1=START, 2=STOP` | high | Semantic mapping confirmed; transmit disabled |
| `0x02440B88` | 0 | Generator lifecycle/status | `uint8 enum` | `00=OFF_IDLE, 01=RUNNING_SETTLED, 02/03=STARTING, 04/05=STOPPING` | high | Confirmed receive-side state enum; exact paired substages unresolved |
| `0x005A1020` | 0-1 | Generator-associated AC frequency | `uint16` / little | x0.1 Hz | high | 50 Hz marks RUNNING during START; 0 Hz marks STOPPED during STOP; context-gated |
| derived | n/a | Generator lifecycle state machine | enum | command + status + context-gated frequency | high | `STARTING -> RUNNING -> RUNNING_SETTLED`; `STOPPING -> STOPPED -> OFF_IDLE` |
| `0x02040B90` | 0-3 | AC panel leading reserved words | 2 x `uint16` / big | raw | high | Reserved/unused in this capture |
| `0x02040B90` | 4-5 | AC panel AC voltage | `uint16` / big | x1 V | high | AC panel AC voltage telemetry |
| `0x02040B88` | 0-3 | House panel leading reserved words | 2 x `uint16` / big | raw | high | Reserved/unused in this capture |
| `0x02040B88` | 4-5 | House panel AC voltage | `uint16` / big | x1 V | high | House panel AC voltage telemetry |
| `0x02060B88` | 2-3 | House DC unavailable/reserved | `uint16` / big | raw `0x7FFF` | high | Unavailable sentinel |
| `0x02040898` | 0-1 | Generator/AC module voltage | `uint16` / big | x1 V | high | Clean AC voltage ramps |
| `0x02040898` | 2-3 | Generator/AC module frequency | `uint16` / big | x1 Hz | high | AC frequency |
| `0x00501008` | 6-7 | Charger 1008 unavailable/reserved | `uint16` / little | raw `0xFFFF` | high | Unavailable/reserved |
| `0x005A1008` | 2-7 | Charger 1008 unavailable/reserved | 3 x `uint16` / little | raw `0xFFFF` | high | Unavailable/reserved |
| `0x00501010` | 6-7 | Charger 1010 unavailable/reserved | `uint16` / little | raw `0xFFFF` | high | Unavailable/reserved |
| `0x005A1010` | 2-7 | Charger 1010 unavailable/reserved | 3 x `uint16` / little | raw `0xFFFF` | high | Unavailable/reserved |
| `0x00501020` | 6-7 | Charger 1020 unavailable/reserved | `uint16` / little | raw `0xFFFF` | high | Unavailable/reserved |
| `0x005A1020` | 2-7 | `0x1020` frequency-frame unavailable/reserved | 3 x `uint16` / little | raw `0xFFFF` | high | Unavailable/reserved |

`02440B88#00` was confirmed in follow-on work but is absent from the baseline capture. The baseline lifecycle output therefore ends at `STOPPED` after the zero-frequency milestone.
