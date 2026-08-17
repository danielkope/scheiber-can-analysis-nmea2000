# Scheiber CAN mapping register

> Status labels are intentional: `confirmed`, `candidate`, `guess`, and `unresolved` are not interchangeable. Generator receive-side lifecycle semantics are confirmed; generator transmission remains disabled.

The separate `data/derived/can_id_inventory.csv` lists every observed CAN ID and frame count. The analyzer emits machine-readable datatype, endian, scale, offset, unit, confidence, and status columns in `decoded_fields_long.csv`.

## Confirmed and high-confidence fields

| CAN ID | Bytes | Signal | Type / endian | Scale / unit | Status | Confidence |
|---|---|---|---|---|---|---|
| `0x02040580` | 0-1 | Water tank level | `uint16` / big | x1 % | confirmed | high |
| `0x02040580` | 2-3 | Diesel tank 1 level | `uint16` / big | x1 % | confirmed | high |
| `0x02040580` | 4-5 | Diesel tank 2 level | `uint16` / big | x1 % | confirmed | high |
| derived | n/a | Water volume | derived float | 600 L capacity x level/100 | derived from confirmed input | high |
| derived | n/a | Diesel tank 1 volume | derived float | 500 L capacity x level/100 | derived from confirmed input | high |
| derived | n/a | Diesel tank 2 volume | derived float | 500 L capacity x level/100 | derived from confirmed input | high |
| `0x02420B90` | 0 | AC panel requested source | `uint8 enum` | `1=OFF, 2=SHORE, 4=GENERATOR` | confirmed | high |
| `0x02400B90` | 0 | AC panel applied source | `uint8 enum` | `1=OFF, 2=SHORE, 4=GENERATOR` | confirmed | high |
| `0x02420B88` | 0 | House panel requested source | `uint8 enum` | `1=OFF, 2=SHORE, 4=GENERATOR` | confirmed | high |
| `0x02400B88` | 0 | House panel applied source | `uint8 enum` | `1=OFF, 2=SHORE, 4=GENERATOR` | confirmed | high |
| `0x02460B88` | 0 | Generator external command | `uint8 enum` | `1=START, 2=STOP` | confirmed semantics; transmit disabled | high |
| `0x02440B88` | 0 | Generator lifecycle/status | `uint8 enum` | `00=OFF_IDLE, 01=RUNNING_SETTLED, 02/03=STARTING, 04/05=STOPPING` | confirmed receive-side semantics | high |
| `0x005A1020` | 0-1 | Generator-associated AC frequency | `uint16` / little | x0.1 Hz | confirmed physical field | high |
| derived state machine | n/a | Generator lifecycle | enum | context-gated command + status + frequency | confirmed receive-side logic | high |
| `0x02040B90` | 0-3 | AC panel leading reserved words | 2 x `uint16` / big | raw | confirmed unused in capture | high |
| `0x02040B90` | 4-5 | AC panel AC voltage | `uint16` / big | x1 V | confirmed | high |
| `0x02040B88` | 0-3 | House panel leading reserved words | 2 x `uint16` / big | raw | confirmed unused in capture | high |
| `0x02040B88` | 4-5 | House panel AC voltage | `uint16` / big | x1 V | confirmed | high |
| `0x02060B88` | 2-3 | House DC unavailable/reserved | `uint16` / big | raw `0x7FFF` | confirmed sentinel | high |
| `0x02040898` | 0-1 | Generator/AC module voltage | `uint16` / big | x1 V | confirmed | high |
| `0x02040898` | 2-3 | Generator/AC module frequency | `uint16` / big | x1 Hz | confirmed | high |
| `0x06020580` | 0-1 | House battery candidate 1 voltage | `uint16` / little | x0.01 V | confirmed field / candidate identity | high / medium |
| `0x06060580` | 0-1 | House battery candidate 2 voltage | `uint16` / little | x0.01 V | confirmed field / candidate identity | high / medium |
| `0x060A0580` | 0-1 | House battery candidate 3 voltage | `uint16` / little | x0.01 V | confirmed field / candidate identity | high / medium |
| `0x060E0580` | 0-1 | House battery candidate 4 voltage | `uint16` / little | x0.01 V | confirmed field / candidate identity | high / medium |
| `0x06120580` | 0-1 | House battery candidate 5 voltage | `uint16` / little | x0.01 V | confirmed field / candidate identity | high / medium |
| `0x06160580` | 0-1 | House battery candidate 6 voltage | `uint16` / little | x0.01 V | confirmed field / candidate identity | high / medium |
| `0x00501008` | 6-7 | Charger 1008 unavailable/reserved | `uint16` / little | raw `0xFFFF` | confirmed sentinel | high |
| `0x00501010` | 6-7 | Charger 1010 unavailable/reserved | `uint16` / little | raw `0xFFFF` | confirmed sentinel | high |
| `0x00501020` | 6-7 | Charger 1020 unavailable/reserved | `uint16` / little | raw `0xFFFF` | confirmed sentinel | high |
| `0x005A1008/1010/1020` | 2-7 | Frequency-frame unavailable/reserved words | 3 x `uint16` / little | raw `0xFFFF` | confirmed sentinel | high |

## Generator lifecycle state machine

| Trigger | Datatype / scale | Context | Result |
|---|---|---|---|
| `02460B88#01` | `uint8 enum` | any | `STARTING` and begin START transaction |
| `02440B88#02/#03` | `uint8 enum` | startup | `STARTING` confirmed |
| `005A1020` word 0 = 500 | `uint16LE` x0.1 Hz = 50.0 Hz | active START | `RUNNING` |
| `02440B88#01` | `uint8 enum` | startup/running | `RUNNING_SETTLED` |
| `02460B88#02` | `uint8 enum` | any | `STOPPING` and begin STOP transaction |
| `02440B88#05/#04` | `uint8 enum` | shutdown | `STOPPING` confirmed |
| `005A1020` word 0 = 0 | `uint16LE` x0.1 Hz = 0.0 Hz | active STOP | `STOPPED` |
| `02440B88#00` | `uint8 enum` | stopped | `OFF_IDLE` |

The frequency field is context-gated. Source-panel switching also produces `0x005A1020` 0/50 Hz changes; outside an active START/STOP transaction those are logged as AC-path observations and do not change engine lifecycle state.

`02440B88#00` is follow-on confirmed evidence and does not occur in the supplied baseline capture. Therefore the baseline-generated timeline ends at `STOPPED`.

## Candidate and guessed fields

| CAN ID | Bytes | Signal | Type / endian | Scale / unit | Status | Confidence |
|---|---|---|---|---|---|---|
| `0x02060580` | 4-5 | Central DC voltage candidate | `uint16` / big | x0.1 candidate V | candidate | medium |
| `0x02040B90` | 6-7 | AC panel frequency/status word | `uint16` / big | usually x1 Hz-like/raw | candidate | medium |
| `0x02040B88` | 6-7 | House panel frequency/status word | `uint16` / big | usually x1 Hz-like/raw | candidate | medium |
| `0x02060B88` | 0-1 | House DC voltage candidate | `uint16` / big | x0.1 V | candidate | medium-high |
| `0x02140898` | 0 | Generator/AC transition marker | `uint8 enum` | `02=ramp-down`, `03=ramp-up` | candidate | medium |
| each `0x060x0580` | 2-3 | House battery signed current code | offset `uint16` / little | raw - `0x4E00`; x0.1 A guessed | candidate | medium sign; low-medium A scale |
| each `0x060x0580` | 4-5 | House battery field 3 | `uint16` / little | x1 % SoC guess or degF alternative | guess | low-medium |
| `0x00501008` | 0-1 | Charger 1008 DC output voltage | `uint16` / little | x0.1 V | candidate | medium-high |
| `0x00501008` | 2-3 | Charger 1008 DC output current | `uint16` / little | x0.1 A | candidate | medium |
| `0x00501008` | 4-5 | Charger 1008 AC input voltage | `uint16` / little | x0.1 V | candidate | high |
| `0x00501010` | 0-1 | Charger 1010 DC output voltage | `uint16` / little | x0.1 V | candidate | medium-high |
| `0x00501010` | 2-3 | Charger 1010 DC output current | `uint16` / little | x0.1 A | candidate | medium |
| `0x00501010` | 4-5 | Charger 1010 AC input voltage | `uint16` / little | x0.1 V | candidate | high |
| `0x00501020` | 0-1 | Charger 1020 DC output voltage | `uint16` / little | x0.1 V | candidate | medium-high |
| `0x00501020` | 2-3 | Charger 1020 DC output current | `uint16` / little | x0.1 A | candidate | medium |
| `0x00501020` | 4-5 | Charger 1020 AC input voltage | `uint16` / little | x0.1 V | candidate | high |
| each `0x005610xx` | 0-1 | Dynamic channel A | `uint16` / little | x0.1 V/A candidate | candidate | low-medium |
| each `0x005610xx` | 2-3 | Dynamic channel B | `uint16` / little | x0.1 V/A candidate | candidate | low-medium |
| each `0x005610xx` | 4 | Nominal voltage signature | `uint8` | x1 V candidate; observed 12 | candidate | medium-high |
| `0x00561008` | 5 | Charger rating signature | `uint8` | 60 A candidate | candidate | medium-high |
| `0x00561010` | 5 | Charger rating signature | `uint8` | 40 A candidate | candidate | medium-high |
| `0x00561020` | 5 | Charger rating signature | `uint8` | 25 A candidate | candidate | medium-high |
| `0x005A1008` | 0-1 | Charger 1008 AC frequency | `uint16` / little | x0.1 Hz | candidate device role / high physical field | high |
| `0x005A1010` | 0-1 | Charger 1010 AC frequency | `uint16` / little | x0.1 Hz | candidate device role / high physical field | high |

## Candidate roles / heartbeats

| CAN ID | Signal | Datatype | Status |
|---|---|---|---|
| `0x00000580` | `0x0580` controller heartbeat | fixed byte array | candidate role |
| `0x00000898` | AC/generator module heartbeat | fixed byte array | candidate role |
| `0x00000B88` | House panel heartbeat | fixed byte array | candidate role |
| `0x00000B90` | AC panel heartbeat | fixed byte array | candidate role |
| `0x00000F80` | Unknown-node heartbeat | fixed byte array | candidate role |
| `0x00001008` | Charger 1008 heartbeat | fixed byte array | candidate role |
| `0x00001010` | Charger 1010 heartbeat | fixed byte array | candidate role |
| `0x00001020` | Charger 1020 heartbeat | fixed byte array | candidate role |

## Unresolved fields

| CAN ID | Bytes | Signal | Type / endian | Notes |
|---|---|---|---|---|
| `0x02040580` | 6-7 | Tank frame state / quality / sequence | `uint16` / big | Observed 0, 1, 2 |
| `0x02060580` | 0-1 | Central sensor value A | `uint16` / big | Current/load/temperature candidate |
| `0x02060580` | 2-3 | Central sensor flags/counter | `uint16` / big | Small state/counter field |
| each `0x005610xx` | 6-7 | Charger config/status bytes | 2 x `uint8` | Unknown configuration/status |
| `0x00521008/1010` | 2-3 | Temperature or counter candidate | `uint16` / little | Monotonic while active; Kelvin is plausible but unproven |
| `0x00541008/1010/1020` | 0-7 | Sparse configuration/status | byte array / mixed | Field meanings unknown |
| `0x02140B88` | all | House-panel / generator companion mode-state | byte array | Some values correlate with transitions; exact semantics unresolved |
| `0x02140B90` | all | AC-panel mode/state | byte array | Preserved raw |
| `0x02160B88` | all | House-panel / generator companion bitfield | byte array | Changes adjacent to START/STOP; exact acknowledgement/interlock role unresolved |
| `0x00080000` | all | Global/time/status frame | byte array | Preserved raw |

## Missing physical assignments

- House-battery CAN candidates 1-6 are not yet assigned to physical battery positions.
- Port and starboard engine-start battery streams are unresolved.
- Generator starter-battery stream is unresolved.
- The exact charger-to-house/port/starboard/generator wiring remains unconfirmed.
- The distinction between STARTING `0x02` and `0x03`, and STOPPING `0x05` and `0x04`, remains an open substate question.
- Companion-frame requirements for safe control remain unresolved.
