# Scheiber CAN analysis summary

- Source: `d5175281-0a41-493a-ae0d-fb84baba6d2f.log`
- SHA-256: `47296d01c77acc01bc32621e8b0bbdb7c6f7e4837da1c207342baba30a281641`
- Frames: 4401
- Unique CAN IDs: 45
- Duration: 228.962155 s
- Start UTC: 2026-08-17T15:13:45.028287+00:00
- End UTC: 2026-08-17T15:17:33.990442+00:00

## Latest tank readings in capture

- water_level: 84 %
- diesel_1_level: 63 %
- diesel_2_level: 79 %

## Confirmed generator command mapping

- `0x02460B88#01` = START
- `0x02460B88#02` = STOP
- Semantic decoding is confirmed; transmission/replay remains disabled pending safety validation.

## Most frequent IDs

| CAN ID | Frames | DLC | Unique payloads |
|---|---:|---:|---:|
| `0x02060580` | 775 | 6 | 153 |
| `0x02040580` | 569 | 8 | 16 |
| `0x00000580` | 229 | 5 | 1 |
| `0x00000898` | 229 | 5 | 1 |
| `0x00000B90` | 228 | 5 | 1 |
| `0x00001008` | 227 | 5 | 1 |
| `0x00001010` | 227 | 5 | 1 |
| `0x00001020` | 227 | 5 | 1 |
| `0x00000B88` | 227 | 5 | 1 |
| `0x00000F80` | 222 | 5 | 1 |
| `0x00501010` | 151 | 8 | 63 |
| `0x00501020` | 148 | 8 | 66 |
| `0x00561010` | 94 | 8 | 29 |
| `0x00561008` | 84 | 8 | 11 |
| `0x00501008` | 84 | 8 | 55 |
| `0x02040898` | 61 | 4 | 22 |
| `0x02040B88` | 59 | 8 | 27 |
| `0x02060B88` | 52 | 4 | 20 |
| `0x06120580` | 51 | 6 | 36 |
| `0x02040B90` | 50 | 8 | 27 |

## Interpretation policy

- `confirmed`: directly correlated with known operator state or an unambiguous physical scale.
- `candidate`: strong engineering inference but needs one controlled validation run.
- `guess`: useful working hypothesis only.
- `unresolved`: preserved as raw data without invented semantics.
