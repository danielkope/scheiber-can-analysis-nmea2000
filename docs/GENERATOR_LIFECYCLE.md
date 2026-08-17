# Generator lifecycle state machine

## Purpose

This document defines the confirmed receive-side interpretation of the generator START and STOP progression. It separates three concepts that must not be conflated:

1. **External command:** an operator or controller requests START or STOP.
2. **Lifecycle/status confirmation:** the generator controller reports STARTING, STOPPING, settled running, or idle.
3. **Physical AC milestone:** the associated `0x1020` device reports generator-side AC frequency.

The implementation is in `scripts/generator_state_machine.py`. It is passive and never transmits CAN frames.

## Signal definitions

| CAN ID | DLC | Bytes | Datatype | Endian / scale | Confirmed meaning |
|---|---:|---|---|---|---|
| `0x02460B88` | 1 | 0 | `uint8 enum` | n/a | `0x01=START`, `0x02=STOP` external command |
| `0x02440B88` | 1 | 0 | `uint8 enum` | n/a | Generator lifecycle/status enum |
| `0x005A1020` | 8 | 0-1 | `uint16` | little-endian, x0.1 Hz | Generator-associated AC-frequency signal; remaining words are `0xFFFF` in the capture |

### `0x02440B88` status enum

| Payload | State | Interpretation |
|---:|---|---|
| `0x00` | `OFF_IDLE` | Final idle terminal state after stop |
| `0x01` | `RUNNING_SETTLED` | Stable terminal state after successful startup |
| `0x02` | `STARTING` | Startup sequence status |
| `0x03` | `STARTING` | Startup sequence status / later startup phase |
| `0x04` | `STOPPING` | Shutdown sequence status |
| `0x05` | `STOPPING` | Shutdown sequence status / earlier shutdown phase |

The semantic grouping is confirmed. Whether `0x02` versus `0x03`, and `0x05` versus `0x04`, encode exact substages, acknowledgements, or actuator phases remains unresolved.

## Confirmed START progression

```text
External START
    |
    +-- 02460B88#01 ------------------------------> STARTING
    |
    +-- 02440B88#02 / 02440B88#03 ----------------> STARTING confirmed
    |
    +-- 005A1020 first LE word = 500 = 50.0 Hz ---> RUNNING
    |
    +-- 02440B88#01 ------------------------------> RUNNING_SETTLED
```

Baseline evidence:

| Capture line | Relative time | Frame | Interpretation |
|---:|---:|---|---|
| 885 | 49.658548 s | `02460B88#01` | External START command; transaction begins |
| 887 | 49.667? s | `02440B88#02` | STARTING confirmed |
| 899 | 50.368585 s | `02440B88#03` | STARTING confirmed / progressed |
| 931 | 52.162626 s | `02440B88#02` | Repeated STARTING status |
| 1086 | 58.540249 s | `005A1020#F401FFFFFFFFFFFF` | `0x01F4=500`, therefore 50.0 Hz; lifecycle becomes RUNNING |
| 1102 | 59.092541 s | `02440B88#03` | Lingering STARTING status; implementation does not regress RUNNING to STARTING |
| 1544 | 79.600994 s | `02440B88#01` | RUNNING_SETTLED |

The state machine deliberately keeps `RUNNING` when a late `#03` follows the 50 Hz milestone. The later `#01` is the settled terminal confirmation.

## Confirmed STOP progression

```text
External STOP
    |
    +-- 02460B88#02 ------------------------------> STOPPING
    |
    +-- 02440B88#05 / 02440B88#04 ----------------> STOPPING confirmed
    |
    +-- 005A1020 first LE word = 0 = 0.0 Hz ------> STOPPED
    |
    +-- 02440B88#00 ------------------------------> OFF_IDLE
```

Baseline evidence:

| Capture line | Relative time | Frame | Interpretation |
|---:|---:|---|---|
| 3427 | 177.378315 s | `02460B88#02` | External STOP command; transaction begins |
| 3429 | 177.386191 s | `02440B88#05` | STOPPING confirmed |
| 3436 | 177.641176 s | `02440B88#04` | STOPPING confirmed / progressed |
| 3451 | 178.151463 s | `005A1020#9001FFFFFFFFFFFF` | `0x0190=400`, therefore 40.0 Hz during decay |
| 3499 | 179.661780 s | `005A1020#0000FFFFFFFFFFFF` | 0.0 Hz; lifecycle becomes STOPPED |

`02440B88#00` was confirmed in follow-on work but is not present in the supplied baseline capture. Consequently, the generated lifecycle timeline for that file correctly ends at `STOPPED`, not `OFF_IDLE`.

## Context gating of `0x005A1020`

Frequency is a physical measurement, not a sufficient standalone engine-state signal. The baseline capture also contains:

- `005A1020=0.0 Hz` during panel/source switching before the external STOP command.
- `005A1020=50.0 Hz` during a later source transition without a new external START command.

Those events show that the `0x1020` AC path can be energized or de-energized independently of the generator engine lifecycle. The tracker therefore applies these rules:

| Frequency event | Active transaction | Lifecycle result |
|---|---|---|
| 50.0 Hz | START / STARTING | `RUNNING` |
| 50.0 Hz | none or STOP | Record AC present; do not change generator state |
| 0.0 Hz | STOP / STOPPING | `STOPPED` |
| 0.0 Hz | none or START | Record AC absent; do not change generator state |
| Transitional nonzero frequency | START | Record frequency build; retain current startup state |
| Transitional nonzero frequency | STOP | Record frequency decay; retain `STOPPING` |

This is the main guard against false lifecycle transitions caused by shore/generator source selection.

## State transition table

| Current state | Input | Next state | Notes |
|---|---|---|---|
| any | `02460B88#01` | `STARTING` | Begin START transaction |
| `STARTING` | `02440B88#02/#03` | `STARTING` | Confirm startup |
| `STARTING` | `005A1020=50.0 Hz` | `RUNNING` | Physical running milestone |
| `RUNNING` | late `02440B88#02/#03` | `RUNNING` | Do not regress on lingering startup status |
| `RUNNING` | `02440B88#01` | `RUNNING_SETTLED` | Stable terminal running state |
| any | `02460B88#02` | `STOPPING` | Begin STOP transaction |
| `STOPPING` | `02440B88#05/#04` | `STOPPING` | Confirm shutdown |
| `STOPPING` | `005A1020=0.0 Hz` | `STOPPED` | Physical stopped milestone |
| `STOPPED` | late `02440B88#05/#04` | `STOPPED` | Do not regress on lingering shutdown status |
| `STOPPED` | `02440B88#00` | `OFF_IDLE` | Final idle terminal state |

## Analyzer outputs

`scheiber_can_analyze.py` writes `generator_state_timeline.csv` with:

- source line and timestamp;
- CAN ID and payload;
- decoded signal;
- raw and engineering values;
- state before and after;
- transaction phase;
- whether the event was accepted as a lifecycle transition;
- confidence and engineering notes.

The normal per-frame decoder also emits:

- `generator_command` and `generator_command_raw`;
- `generator_status` and `generator_status_raw`;
- `generator_lifecycle_ac_signal` for `0x005A1020`.

## Safety boundary

This mapping describes observed receive-side behavior. It does **not** establish a safe transmit sequence. Before any control implementation, independently validate:

- whether commands must be repeated;
- the purpose of adjacent `0x02160B88`, `0x02140B88`, and other companion frames;
- acknowledgements and negative acknowledgements;
- command timeout and watchdog behavior;
- starter crank limits and retry policy;
- low-voltage, fire, oil-pressure, temperature, exhaust, transfer-switch, and shore-power interlocks;
- emergency abort and fail-safe STOP behavior;
- behavior after CAN loss, process crash, or gateway restart.

The repository intentionally contains no generator transmission function.
