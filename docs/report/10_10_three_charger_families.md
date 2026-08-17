# 10. Three charger families

Three suffixes — `0x1008`, `0x1010`, and `0x1020` — each have a one-second fixed heartbeat and several related message types: `0x0050` telemetry, `0x0052` sparse field, `0x0054` configuration/status, `0x0056` rating/dynamic channels, and `0x005A` frequency. This strongly supports three physical charger devices rather than three battery sensors.

## 10.1 Rating signatures

```text
00561008#850080000C3C2CFF -> bytes 4/5 = 0x0C / 0x3C = 12 / 60
00561010#84000A000C282CFF -> bytes 4/5 = 0x0C / 0x28 = 12 / 40
00561020#000006000C19FAFF -> bytes 4/5 = 0x0C / 0x19 = 12 / 25
```

| **Device family** | **Nominal signature** | **Current signature** | **Role hypothesis** | **Confidence** |
|---|---:|---:|---|---|
| 0x1008 | 12 V | 60 A | House/engine charging device | medium-high |
| 0x1010 | 12 V | 40 A | House/engine charging device | medium-high |
| 0x1020 | 12 V | 25 A | Best generator-start charger candidate | medium-high for rating; medium for role |

## 10.2 `0x005010xx` telemetry hypothesis

```text
00501008#8700D1003809FFFF
little-endian uint16 words: 135, 209, 2360, 65535
working engineering decode: 13.5 V DC, 20.9 A DC, 236.0 V AC, unavailable
```

| **Bytes** | **Type / scale** | **Candidate quantity** | **Evidence** | **Confidence** |
|---|---|---|---|---|
| 0-1 | uint16 LE x0.1 | DC output voltage | 13.x while active; device-specific decay when isolated | medium-high |
| 2-3 | uint16 LE x0.1 | DC output current | dynamic 0 to 28.5, physically plausible | medium |
| 4-5 | uint16 LE x0.1 | AC input voltage | 229-240 V active, zero absent | high |
| 6-7 | uint16 LE | 0xFFFF unavailable/reserved | constant 0xFFFF | high |

## 10.3 AC frequency

```text
005A1008#F401FFFFFFFFFFFF -> 0x01F4 LE = 500 -> 50.0 Hz
005A1020#9001FFFFFFFFFFFF -> 0x0190 LE = 400 -> 40.0 Hz
005A10xx#0000FFFFFFFFFFFF -> 0.0 Hz / off
```

This frequency interpretation is one of the strongest charger fields because it matches AC frequency numerically, includes a 40 Hz shutdown transient, and becomes zero when the charger input is de-energized.

## 10.4 Remaining charger fields

- `0x005610xx` words 0 and 1 are dynamic channels scaled plausibly by 0.1, but their per-device roles may be output voltages, currents, setpoints, or secondary outputs.
- `0x00521008` and `0x00521010` contain a monotonic 304-333 field while active. Kelvin temperature is plausible, but the linear behavior also fits a counter; leave unresolved.
- `0x005410xx` carries sparse configuration/status data including recurring values 99 and 100. Change one charger setting at a time to decode it.
- Nameplate verification is the fastest way to confirm the 60 A / 40 A / 25 A rating interpretation.
