# 8. AC/generator telemetry and lifecycle state machine

## 8.1 Three complementary signal families

Generator operation is represented by three separate CAN message families:

| CAN ID | Payload definition | Role |
|---|---|---|
| `0x02460B88` | one-byte `uint8 enum`: `01 START`, `02 STOP` | External command / transaction trigger |
| `0x02440B88` | one-byte `uint8 enum`: `00 OFF_IDLE`, `01 RUNNING_SETTLED`, `02/03 STARTING`, `04/05 STOPPING` | Lifecycle/status confirmation |
| `0x005A1020` | bytes 0-1 `uint16` little-endian, x0.1 Hz | Physical AC-frequency milestone for the `0x1020` device family |

The command and status enums are confirmed. The first frequency word is a confirmed physical frequency field. Its use as a generator lifecycle milestone is conditional on an active START or STOP transaction.

## 8.2 Confirmed external commands

| Payload | Meaning | Capture line | Relative time |
|---:|---|---:|---:|
| `0x01` | START | 885 | 49.658548 s |
| `0x02` | STOP | 3427 | 177.378315 s |

```text
02460B88#01  -> External generator START
02460B88#02  -> External generator STOP
```

These are confirmed semantic mappings, but they are not a safe replay recipe.

## 8.3 Confirmed lifecycle/status enum

| Payload | State | Meaning |
|---:|---|---|
| `0x00` | `OFF_IDLE` | Final idle terminal state after stop |
| `0x01` | `RUNNING_SETTLED` | Stable running terminal state |
| `0x02` | `STARTING` | Startup status / phase |
| `0x03` | `STARTING` | Startup status / later phase |
| `0x04` | `STOPPING` | Shutdown status / later phase |
| `0x05` | `STOPPING` | Shutdown status / phase |

The baseline capture contains `01`, `02`, `03`, `04`, and `05`. It does not contain `00`; `OFF_IDLE` was confirmed in follow-on work. Exact distinctions within the two STARTING and two STOPPING values remain unresolved.

## 8.4 START progression

```text
02460B88#01                 -> STARTING
02440B88#02/#03             -> STARTING confirmed
005A1020 word 0 = 500       -> 50.0 Hz -> RUNNING
02440B88#01                 -> RUNNING_SETTLED
```

| Line | Relative time | Frame | Result |
|---:|---:|---|---|
| 885 | 49.658548 s | `02460B88#01` | START transaction begins; `STARTING` |
| 887 | 49.667? s | `02440B88#02` | STARTING confirmed |
| 899 | 50.368585 s | `02440B88#03` | STARTING confirmed / progressed |
| 931 | 52.162626 s | `02440B88#02` | Repeated STARTING status |
| 1086 | 58.540249 s | `005A1020#F401FFFFFFFFFFFF` | `0x01F4=500` -> 50.0 Hz; `RUNNING` |
| 1102 | 59.092541 s | `02440B88#03` | Lingering STARTING status; state is not regressed |
| 1544 | 79.600994 s | `02440B88#01` | `RUNNING_SETTLED` |

A late `#03` after the 50 Hz milestone is treated as a lingering startup status. The state machine retains `RUNNING` until the settled `#01` arrives.

## 8.5 STOP progression

```text
02460B88#02                 -> STOPPING
02440B88#05/#04             -> STOPPING confirmed
005A1020 word 0 = 0         -> 0.0 Hz -> STOPPED
02440B88#00                 -> OFF_IDLE
```

| Line | Relative time | Frame | Result |
|---:|---:|---|---|
| 3427 | 177.378315 s | `02460B88#02` | STOP transaction begins; `STOPPING` |
| 3429 | 177.386191 s | `02440B88#05` | STOPPING confirmed |
| 3436 | 177.641176 s | `02440B88#04` | STOPPING confirmed / progressed |
| 3451 | 178.151463 s | `005A1020#9001FFFFFFFFFFFF` | `0x0190=400` -> 40.0 Hz decay |
| 3499 | 179.661780 s | `005A1020#0000FFFFFFFFFFFF` | 0.0 Hz; `STOPPED` |

`02440B88#00` was confirmed in later work but is absent from this capture. The baseline timeline therefore correctly terminates at `STOPPED` rather than inventing an `OFF_IDLE` frame.

## 8.6 Context gating of the frequency milestone

The baseline also contains `0x005A1020=0 Hz` before the external STOP command and a later `0x005A1020=50 Hz` without a new START command. These events occur during source-panel switching. Therefore frequency is not a standalone engine-state oracle.

The implemented rules are:

- 50.0 Hz changes state to `RUNNING` only during an active START transaction.
- 0.0 Hz changes state to `STOPPED` only during an active STOP transaction.
- Outside those contexts, frequency is decoded and logged but does not change generator lifecycle state.
- Transitional values are logged as frequency build or decay only when the corresponding transaction is active.

The analyzer writes the result to `generator_state_timeline.csv`, including accepted transitions and context-only observations.

## 8.7 Generator/AC module `0x0898`

```text
02040898#00E60032 -> 230 V, 50 Hz
02040898#00EB0032 -> 235 V, 50 Hz
02040898#00000000 ->   0 V,  0 Hz
```

The payload is two big-endian `uint16` values. Four event markers on `0x02140898` correlate with clean voltage ramp directions: value `0x02` precedes ramp-down and `0x03` precedes ramp-up. These markers are distinct from the direct command, lifecycle/status, and `0x1020` frequency frames.

| Marker line | t (s) | Marker | Observed voltage sequence |
|---:|---:|---:|---|
| 1169 | 61.229 | `0x02` | 235 -> 205 -> 175 -> 145 -> 115 -> 85 -> 0 V |
| 2988 | 156.802 | `0x03` | 0 -> 80 -> 110 -> 140 -> 170 -> 200 -> 230 -> 235 V |
| 3318 | 171.523 | `0x02` | 235 -> 210 -> 180 -> 150 -> 120 -> 90 -> 0 V |
| 3680 | 189.600 | `0x03` | 0 -> 80 -> 110 -> 140 -> 170 -> 195 -> 225 -> 230 -> 235 V |

## 8.8 Panel AC telemetry

IDs `0x02040B90` and `0x02040B88` contain AC-panel and House-panel voltage in bytes 4-5 as big-endian `uint16`. Bytes 0-3 are zero throughout this capture. Bytes 6-7 are usually 50 while energized and 0 while off, but some transition values indicate additional status encoding; label this word frequency/status until validated.

## 8.9 Transmission safety boundary

Receive-side lifecycle reconstruction is confirmed. Transmission remains disabled because the following are still unknown:

- required repetitions and intervals;
- purpose of adjacent companion frames, including `0x02160B88` and `0x02140B88`;
- positive/negative acknowledgement behavior;
- crank timeout and retry limits;
- low-voltage, fire, oil-pressure, temperature, exhaust, transfer-switch, and shore-power interlocks;
- abort, watchdog, CAN-loss, and fail-safe STOP behavior.
