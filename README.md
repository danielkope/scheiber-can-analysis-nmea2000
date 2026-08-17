# Scheiber CAN Analysis for NMEA 2000

Reverse-engineering notes, evidence, tools, and a reproducible Raspberry Pi capture workflow for a Scheiber marine CAN installation observed through a DSD TECH SH-C30A (CANable-derived) USB-CAN adapter.

> **Project status:** engineering reverse-engineering report, not an OEM protocol specification. Every field is labelled `confirmed`, `candidate`, `guess`, or `unresolved`. The default workflow is passive/read-only.

## What is included

- A complete, hash-identified 228.962 s candump capture, stored as one `.xz` file, with 4,401 valid extended-CAN frames and 45 CAN IDs.
- A pure-Python decoder and CSV/JSON report generator.
- A context-aware generator lifecycle state machine.
- A detailed engineering report in Markdown, PDF, and DOCX form; PDF/DOCX can be rebuilt with `scripts/build_report.sh`.
- Wiring and Raspberry Pi setup instructions for the SH-C30A.
- A mapping register with datatypes, endianness, scales, offsets, units, observed ranges, confidence, and proposed NMEA 2000 PGNs.
- A validation plan for the nine batteries, three chargers, two power panels, generator, and three tanks.
- Dry-run NMEA 2000 translation examples. No control frames are transmitted.

## Known installation inventory

| Item | Count / capacity | Current identification status |
|---|---:|---|
| House batteries | 6 | Six individual CAN streams identified; physical battery 1-6 assignment pending |
| Engine start batteries | 2 | Port and starboard physical CAN sources unresolved |
| Generator start battery | 1 | Battery source unresolved; 25 A charger family is the best charging-system candidate |
| Battery chargers | 3 | Device families with credible 12 V / 60 A, 12 V / 40 A, and 12 V / 25 A signatures |
| Water tank | 600 L | 84% median, approximately 504 L |
| Diesel tank 1 | 500 L | 63% median, approximately 315 L |
| Diesel tank 2 | 500 L | 79%, approximately 395 L |
| Power source panels | 2 | AC panel and House panel request/applied states decoded |

The capacities and inventory are centrally defined in [`config/system_config.json`](config/system_config.json).

## Key findings

### Tanks — confirmed

CAN ID `0x02040580` is four big-endian unsigned 16-bit words:

```text
02040580#0054003F004F0001
            |   |   |   +-- raw state/quality/sequence candidate = 1
            |   |   +------ diesel 2 = 0x004F = 79%
            |   +---------- diesel 1 = 0x003F = 63%
            +-------------- water    = 0x0054 = 84%
```

### Source selectors — confirmed

The source enum is:

- `0x01` = OFF
- `0x02` = SHORE
- `0x04` = GENERATOR

Request and applied-state frames are distinct:

| Panel | Request | Applied |
|---|---|---|
| AC | `0x02420B90` | `0x02400B90` |
| House | `0x02420B88` | `0x02400B88` |

Transfers from shore to generator include an applied intermediate OFF state, consistent with break-before-make behavior.

## Generator lifecycle — confirmed receive-side sequence

The generator is represented by three complementary signal families:

| CAN ID | Datatype | Scale / enum | Role |
|---|---|---|---|
| `0x02460B88` | `uint8 enum` | `01=START`, `02=STOP` | External command / transaction trigger |
| `0x02440B88` | `uint8 enum` | `00=OFF_IDLE`, `01=RUNNING_SETTLED`, `02/03=STARTING`, `04/05=STOPPING` | Generator lifecycle/status confirmation |
| `0x005A1020` bytes 0-1 | `uint16 little-endian` | x0.1 Hz | Physical AC-frequency milestone |

### External START

```text
02460B88#01                 -> STARTING
02440B88#02 or #03          -> STARTING confirmed
005A1020 first word = 500   -> 50.0 Hz -> RUNNING
02440B88#01                 -> RUNNING_SETTLED
```

### External STOP

```text
02460B88#02                 -> STOPPING
02440B88#05 or #04          -> STOPPING confirmed
005A1020 first word = 0     -> 0.0 Hz -> STOPPED
02440B88#00                 -> OFF_IDLE
```

The baseline capture contains START, STARTING confirmation, 50 Hz, RUNNING_SETTLED, STOP, STOPPING confirmation, frequency decay, and 0 Hz. It does **not** contain `02440B88#00`; `OFF_IDLE` was confirmed in later work and is documented as follow-on evidence.

### Why frequency is context-gated

`0x005A1020` also changes when the associated AC path is switched between generator, OFF, and shore. Therefore:

- 50 Hz promotes the lifecycle to `RUNNING` only while a START transaction is active.
- 0 Hz promotes the lifecycle to `STOPPED` only while a STOP transaction is active.
- Outside those contexts, the decoder records AC present/absent but does not infer engine state.

This prevents panel source switching from generating false generator starts or stops. See [`docs/GENERATOR_LIFECYCLE.md`](docs/GENERATOR_LIFECYCLE.md).

The repository remains receive-only. The lifecycle mapping is not a safe transmission recipe; command repetition, companion frames, acknowledgements, interlocks, abort handling, timeouts, and fail-safe behavior remain unvalidated.

### Six house-battery candidates

The six IDs are:

```text
0x06020580  0x06060580  0x060A0580
0x060E0580  0x06120580  0x06160580
```

Each six-byte payload is provisionally decoded as:

| Bytes | Type | Interpretation |
|---|---|---|
| 0-1 | `uint16` little-endian, x0.01 | Voltage in volts — high confidence |
| 2-3 | offset `uint16` little-endian, raw - `0x4E00` | Signed charge/discharge code — sign high confidence; x0.1 A is a working guess |
| 4-5 | `uint16` little-endian | 72-74; SoC percent is the primary guess, temperature in degF remains possible |

### Three charger families

The repeated device suffixes `0x1008`, `0x1010`, and `0x1020` each have heartbeat, telemetry, configuration, rating, and frequency messages. Their `0x005610xx` payload signatures contain:

| Device family | Constant bytes | Rating interpretation | Role hypothesis |
|---|---|---|---|
| `0x1008` | `0C 3C` | 12 V / 60 A | House/engine charging candidate |
| `0x1010` | `0C 28` | 12 V / 40 A | House/engine charging candidate |
| `0x1020` | `0C 19` | 12 V / 25 A | Best generator-start charger candidate |

For `0x005010xx`, four little-endian `uint16` values plausibly decode as DC voltage x0.1 V, DC current x0.1 A, AC input voltage x0.1 V, and `0xFFFF` unavailable. Example:

```text
00501008#8700D1003809FFFF
          135  209   2360  65535  (little-endian words)
         13.5V 20.9A 236.0V   NA  (candidate engineering units)
```

For `0x005A10xx`, the first little-endian word is a strong AC-frequency field: `0x01F4 = 500 -> 50.0 Hz`, `0x0190 = 400 -> 40.0 Hz`, and zero when off.

## Analyze a capture

```bash
python3 scripts/scheiber_can_analyze.py \
  your_capture.log \
  --config config/system_config.json \
  --output analysis-output
```

Important outputs include:

- `decoded_fields_long.csv`
- `event_candidates.csv`
- `generator_state_timeline.csv`
- `tank_samples.csv`
- `house_battery_candidates.csv`
- `charger_candidates.csv`
- `capture_metadata.json`
- `summary.md`

The live monitor also prints context-aware lifecycle transitions:

```bash
python3 scripts/live_monitor.py --channel can1
```

## Engineering report

The source report is [`docs/ENGINEERING_REPORT.md`](docs/ENGINEERING_REPORT.md). Rebuild the human-friendly PDF and DOCX with:

```bash
./scripts/build_report.sh
```

## Reproduce the capture

### 1. Wire the Scheiber six-pin connector to the SH-C30A

| Scheiber six-pin | Function | SH-C30A terminal |
|---:|---|---|
| 5 | CAN-H | CAN_H |
| 6 | CAN-L | CAN_L |
| 2, or installation-specific pin 3 | GND | GND |
| 1 | Recovery | **Not connected** |
| 4 | +12 V | **Not connected** |

The SH-C30A is USB-powered. Do not connect Scheiber +12 V to it.

### 2. SH-C30A switches

- Programming/boot switch: normal RUN/Candlelight position, not firmware-programming mode.
- 120-ohm termination: normally **OFF** for a passive tap into an already terminated bus. Enable only if the adapter is physically replacing an end terminator.
- With all power off, CAN-H to CAN-L should normally measure about 60 ohms for two 120-ohm end terminators.

Physical switch direction depends on the exact board revision; use the label and resistance measurement rather than assuming left/right orientation.

### 3. Raspberry Pi and SocketCAN

```bash
sudo apt update
sudo apt install -y can-utils python3 python3-venv python3-pip git

lsusb
ip -details link show

sudo ip link set can1 down 2>/dev/null || true
sudo ip link set can1 type can bitrate 250000 restart-ms 100
sudo ip link set can1 up
ip -details -statistics link show can1
```

The interface may enumerate as `can0` instead of `can1`; substitute the actual name.

### 4. Capture to screen and file

```bash
candump can1
candump -L can1 > scheiber_$(date +%Y%m%d_%H%M%S).log
```

The `-L` format includes absolute timestamps and is accepted by the analyzer. `candump -l can1` is also useful for automatic logfile naming.

## Bus checks before trusting a capture

```bash
ip -details -statistics link show can1
```

Look for:

- `bitrate 250000`
- state `ERROR-ACTIVE`
- no increasing RX/TX error counters
- no dropped frames or repeated bus-off events

If there are no frames, verify CAN-H/CAN-L polarity, the common ground, interface name, bitrate, termination, and the `gs_usb` driver. If errors rise quickly or the interface goes bus-off, disconnect and correct wiring/termination before continuing.

## NMEA 2000 gateway architecture

Scheiber CAN and NMEA 2000 are separate protocols. Do not join the wires as one bus merely because both can operate at 250 kbit/s.

Use two independent CAN interfaces:

```text
Scheiber bus <-> CAN interface A <-> Raspberry Pi gateway <-> CAN interface B <-> NMEA 2000 / VE.Can
```

The proposed translation is documented in [`docs/NMEA2000_MAPPING.md`](docs/NMEA2000_MAPPING.md). The initial implementation should be read-only on Scheiber and dry-run/log-only on the NMEA side. Source-selection and generator control must remain disabled until safety interlocks and acknowledgements are independently validated.

## Repository layout

```text
config/                 capacities, inventory, mappings
data/raw/               original candump capture (single .xz file)
data/examples/          selected evidence frames
data/derived/           generated CSV/JSON results
scripts/                analyzer, lifecycle tracker, and helper tools
docs/                   engineering report and handoff documentation
tests/                  decoder and lifecycle regression tests
```

## Source references

- DSD TECH SH-C30A official product page: https://www.deshide.com/product-details_SH-C30A.html
- CANable: https://www.canable.io/
- Linux CAN utilities: https://github.com/linux-can/can-utils
- Victron VE.Can pinout documentation: https://www.victronenergy.com/media/pg/Venus_GX/en/connecting-supported-non-victron-products.html
- Scheiber CAN/NMEA gateway: https://www.scheiber.com/can-nmea?lang=en
- canboat NMEA 2000 PGN database: https://canboat.github.io/canboat/canboat.html

## License and disclaimer

Code and original documentation in this repository are provided under the MIT License. The CAN capture remains experimental data from the user's installation. This project is not affiliated with or endorsed by Scheiber, Victron Energy, DSD TECH, or the NMEA organization. Generator and AC source control can create hazardous conditions; use qualified marine-electrical practices and begin with passive monitoring only.
