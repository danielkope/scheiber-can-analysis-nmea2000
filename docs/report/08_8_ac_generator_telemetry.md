# 8. AC/generator telemetry and commands

## 8.1 Confirmed direct generator command

CAN ID `0x02460B88` carries a one-byte `uint8 enum` command:

| Payload | Meaning | Capture line | Relative time |
|---:|---|---:|---:|
| `0x01` | START | 885 | 49.658548 s |
| `0x02` | STOP | 3427 | 177.378315 s |

```text
02460B88#01  -> Generator START
02460B88#02  -> Generator STOP
```

This is a confirmed semantic mapping. It is not yet a safe replay recipe: adjacent frames `0x02160B88` and `0x02440B88` change around both commands and may be acknowledgements, companion state, sequencing, or interlock traffic. Transmission therefore remains disabled by design.

## 8.2 Generator/AC module 0x0898

```text
02040898#00E60032 -> 230 V, 50 Hz
02040898#00EB0032 -> 235 V, 50 Hz
02040898#00000000 ->   0 V,  0 Hz
```

The payload is two big-endian `uint16` values. Four event markers on `0x02140898` correlate with clean voltage ramp directions: value `0x02` precedes ramp-down and `0x03` precedes ramp-up. These markers are distinct from the direct START/STOP command.

| Marker line | t (s) | Marker | Observed voltage sequence |
|---:|---:|---:|---|
| 1169 | 61.229 | `0x02` | 235 -> 205 -> 175 -> 145 -> 115 -> 85 -> 0 V |
| 2988 | 156.802 | `0x03` | 0 -> 80 -> 110 -> 140 -> 170 -> 200 -> 230 -> 235 V |
| 3318 | 171.523 | `0x02` | 235 -> 210 -> 180 -> 150 -> 120 -> 90 -> 0 V |
| 3680 | 189.600 | `0x03` | 0 -> 80 -> 110 -> 140 -> 170 -> 195 -> 225 -> 230 -> 235 V |

## 8.3 Panel AC telemetry

IDs `0x02040B90` and `0x02040B88` contain AC-panel and House-panel voltage in bytes 4-5 as big-endian `uint16`. Bytes 0-3 are zero throughout this capture. Bytes 6-7 are usually 50 while energized and 0 while off, but some transition values indicate additional status encoding; label this word frequency/status until validated.
