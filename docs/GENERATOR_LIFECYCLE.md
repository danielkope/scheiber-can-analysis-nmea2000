# Generator lifecycle, control, and Victron ownership

## Scope

This document combines the original passive lifecycle evidence with follow-on live validation of the exact generator START/STOP commands and the Victron connected-genset integration. The baseline capture remains reproducible and should not be rewritten to imply observations it did not contain.

## Signal definitions

| CAN ID | DLC | Meaning | Decode / enum | Status |
|---|---:|---|---|---|
| `0x02460B88` | 1 | generator command | `01=START`, `02=STOP` | semantics confirmed in capture; both payloads live-tested TX |
| `0x02440B88` | 1 | generator lifecycle/status | `00=OFF_IDLE`, `01=RUNNING_SETTLED`, `02/03=STARTING`, `04/05=STOPPING` | confirmed grouping |
| `0x005A1020` | 8 | generator-specific frequency | bytes 0-1 `uint16LE * 0.1 Hz` | confirmed field; generator-specific in follow-on test |
| `0x02040898` | 8 | shared/common AC telemetry | bytes 0-1 BE V, 2-3 BE Hz | not sufficient for generator state |

`02440B88#06/#07` remain abort/error candidates.

## Exact live-tested commands

```bash
cansend can2 02460B88#01   # START
cansend can2 02460B88#02   # STOP
```

The production bridge emits these only for an accepted Victron `/Start` transition. It sends one command and no automatic retry.

## START progression

```text
Victron or physical START
    |
    +-- 02460B88#01 ------------------------------> STARTING
    +-- 02440B88#02/#03 --------------------------> STARTING confirmed
    +-- 005A1020 ~= 50 Hz, held 3 s --------------> RUNNING
    +-- 02440B88#01 ------------------------------> RUNNING_SETTLED
```

The baseline capture shows the same receive-side progression. A late `#02/#03` after nominal frequency must not regress RUNNING back to STARTING.

## STOP progression

```text
Victron or physical STOP
    |
    +-- 02460B88#02 ------------------------------> STOPPING
    +-- 02440B88#05/#04 --------------------------> STOPPING confirmed
    +-- 005A1020 = 0.0 Hz ------------------------> STOPPED
    +-- 02440B88#00 ------------------------------> OFF_IDLE
```

The baseline capture ends at 0 Hz / `STOPPED`; `#00` was confirmed in later live work.

## Generator-specific frequency finding

The original capture required context gating because AC source switching also changed 0x1020-related telemetry. Follow-on live testing separated the signals more clearly: while the generator was OFF and shore remained present, `005A1020` stayed at 0.0 Hz while `02040898` still reported approximately 235 V / 50 Hz. Bridge v5.4.1 therefore treats `005A1020` as the generator-specific running milestone and `02040898` as shared/fallback AC telemetry.

## Physical state to Victron `/StatusCode`

| Bridge physical state | StatusCode |
|---|---:|
| `UNKNOWN` / stopped idle | 0 once settled evidence is available |
| `STARTING` | 1 |
| `RUNNING` | 8 |
| `RUNNING_SETTLED` | 8 |
| `STOPPING` | 9 |
| `STOPPED` | 0 |
| `OFF_IDLE` | 0 |
| actual error | 10 only when genuinely known |

## D-Bus ownership rule

The connected-genset service is:

```text
com.victronenergy.genset.scheiber
```

Victron `dbus-generator` discovers it and creates the normal connected-genset manager, typically:

```text
com.victronenergy.generator.startstop1
```

The key ownership rule is:

- genset `/Start` is **command state owned by Victron**;
- physical CAN feedback never assigns `/Start` locally;
- genset `/StatusCode` is **actual physical feedback**;
- an externally observed Scheiber START is adopted by setting manager `/ManualStart=1`;
- the manager's resulting `/Start=1` write is accepted but its duplicate CAN START is suppressed;
- an externally observed STOP clears `/ManualStart` only when the manager is manually owning the run, preserving automatic conditions.

This is what allows native Victron autostart logic, manual runs, timed runs, runtime accounting, and physical feedback to coexist.

## Timed-run validation

A native Victron timed run was exercised end-to-end. During the run:

```text
/ManualStart = 1
/ManualStartTimer > 0 and counting down
/RunningByCondition = 'manual'
/RunningByConditionCode = 1
/Runtime increasing
com.victronenergy.genset.scheiber /Start = 1
/StatusCode = 8
```

At timer expiry, Victron changed `/Start` to 0; the bridge transmitted exactly one `02460B88#02`; Scheiber reported `#05/#04`, then `005A1020=0.0 Hz`, and the bridge confirmed STOPPED.

Current gui-v2 may display only the timer icon/elapsed runtime and no longer exposes the older live +/- duration controls. That is a UI change, not a missing bridge capability. `/ManualStartTimer` remains a writable manager path.

### CLI type warning

Do not write a timer as a string. With the Venus `dbus` CLI, a plain `12000` can be interpreted as a string; `%12000` is an integer variant. A string timer can crash `dbus-generator` when it decrements the value. Prefer the UI.

## Manager restart recovery

A `dbus-generator` restart recreates `startstop1` and can initialize the remote `/Start` to zero. Without guarding, that initialization can look like a real STOP while the physical engine is already running.

Bridge v5.4.1 therefore caches manager manual/timer/condition state and, when the manager disappears while STARTING/RUNNING:

1. arms a 30 s recovery guard;
2. suppresses replacement-manager initialization `/Start=0` from CAN;
3. restores a numeric `/ManualStartTimer` first when appropriate;
4. restores `/ManualStart=1`;
5. waits for the manager to synchronize `/Start=1` and suppresses the duplicate CAN command;
6. then returns to normal command handling.

This recovery path was observed working in live logs.

## Post-stop `OFF_IDLE` caveat

`STOPPED` at 0 Hz means the engine/frequency has stopped, but the Scheiber controller may still be settling. In live testing, `02440B88#00` arrived roughly a minute later. A START sent about 15 s after STOP, before `#00`, was transmitted but ignored. A later START from `OFF_IDLE` succeeded normally.

Bridge v5.4.1 does **not** queue such an early START. The current operational rule is: after a stop, wait for `OFF_IDLE` before requesting another start. A future version can queue one Victron START until `#00` without changing the manager timer semantics.

## Startup resynchronization

If the bridge restarts while the generator is already running, it attempts to recover physical state instead of assuming OFF. Generator-specific nominal `005A1020` is the strongest evidence. Two high-AC samples from `00501020` are also used as a fast startup hint during a limited resync window; they are not treated as the sole steady-state generator proof.

## Safety boundary

The live-tested production transmit surface is intentionally narrow:

```text
02460B88#01
02460B88#02
```

The bridge does not transmit source-selection requests, does not replay unresolved companion frames, and does not retry START/STOP automatically. Existing generator hardware protections remain authoritative. Live success on one installation is not an OEM protocol specification.
