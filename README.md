# Scheiber CAN Analysis for NMEA 2000

Reverse-engineering notes, evidence, tools, and reproducible integration work for a Scheiber marine CAN installation observed through a DSD TECH SH-C30A (CANable/Candlelight-compatible) USB-CAN adapter.

> **Project status:** engineering reverse-engineering project, not an OEM protocol specification. Passive analysis remains the default workflow. An optional, isolated Cerbo GX bridge under [`cerbo/`](cerbo/) implements the two generator commands that were live-validated on this installation; AC/House source-selection control remains disabled.

## What is included

- A complete, hash-identified 228.962 s candump capture, stored as one `.xz` file, with 4,401 valid extended-CAN frames and 45 CAN IDs.
- A pure-Python decoder and CSV/JSON report generator.
- A context-aware passive generator lifecycle state machine.
- A tested Victron Cerbo GX connected-genset bridge with runit installer, rollback path, D-Bus integration, tanks, batteries, and diagnostics.
- A native Cerbo GX **Smart Anchor Watch & Alarm Service** with geodesic projection, multi-hour Cairo vector chart & wind strip plot rendering, multi-sensor marine alarms, Scheiber deck light automation, and interactive Telegram control ([`docs/ANCHOR_WATCH.md`](docs/ANCHOR_WATCH.md)).
- A live-validated Signal K -> NMEA 2000 tank path using PGN 127505, including B&G Zeus3 compatibility guidance.
- Wiring/setup instructions for the SH-C30A on Raspberry Pi and Cerbo GX.
- A mapping register with datatypes, endianness, scales, offsets, units, observed ranges, confidence, and proposed NMEA 2000 PGNs.
- A validation plan for the batteries, chargers, source panels, generator, and tanks.
- Dry-run NMEA 2000 translation examples for mappings that are not yet live-enabled.

The historical analyzer does not transmit Scheiber control frames. The optional Cerbo bridge transmits only the live-tested generator `START`/`STOP` frame (`0x02460B88`) and explicitly does not transmit source-selector requests.

## Known installation inventory

| Item | Count / capacity | Current identification status |
|---|---:|---|
| House batteries | 6 | Six individual CAN streams identified; voltage and SoC semantics established, physical battery 1-6 assignment pending |
| Engine start batteries | 2 | Two experimental streams (`0x06140580`, `0x06180580`); port/starboard identity and voltage scale still require crank validation |
| Generator start battery | 1 | Starter voltage published from `0x00501020` bytes 0-1 LE x0.1 V |
| Battery chargers | 3 | Device families with credible 12 V / 60 A, 12 V / 40 A, and 12 V / 25 A signatures |
| Water tank | 600 L | Confirmed level mapping |
| Diesel tank 1 | 500 L | Confirmed level mapping |
| Diesel tank 2 | 500 L | Confirmed level mapping |
| Power source panels | 2 | AC panel and House panel request/applied states decoded; bridge uses applied state receive-only |

The capacities and inventory are centrally defined in [`config/system_config.json`](config/system_config.json).

## Victron Cerbo GX integration

The tested bridge is documented in [`docs/CERBO_GX_INTEGRATION.md`](docs/CERBO_GX_INTEGRATION.md).

It publishes:

```text
com.victronenergy.genset.scheiber
com.victronenergy.grid.scheiber_shore
com.victronenergy.inverter.scheiber_mastervolt
com.victronenergy.switch.scheiber
```

which Victron's normal `dbus-generator` service matches to a connected-genset manager (`com.victronenergy.generator.startstop1`). Native Victron manual starts, automatic conditions, timed runs, runtime accounting, and stop commands therefore remain manager-owned rather than being reimplemented in the bridge.

The complete canonical runtime source is checked in directly as [`cerbo/bridge.py`](cerbo/bridge.py). It is not generated or patched during installation.

Current bridge:

```text
version 5.9.0
SHA-256 f3fecabfb42530c2fc9dc3007fbd0036092a33e4e10a57adc2242a0efd45f3bc
```

### Fresh install or update

The same repository installer is used for both a new installation and an update. Re-download it before running so an old local copy cannot retain obsolete deployment logic:

```bash
mkdir -p /data/scheiber-gx-installer
cd /data/scheiber-gx-installer
wget -O install.sh \
  https://raw.githubusercontent.com/danielkope/scheiber-can-analysis-nmea2000/main/cerbo/install.sh
chmod +x install.sh
CAN_IF=can2 CAN_BITRATE=250000 ./install.sh
```

The installer downloads the complete `bridge.py`, compiles it, verifies the pinned SHA-256, backs up the previous installed script when present, and restarts the runit service. See [`cerbo/README.md`](cerbo/README.md) for separate fresh-install/update explanations and the integration guide for the system-battery requirement and post-stop `OFF_IDLE` restart caveat.

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

The Cerbo bridge publishes these as native Victron tank services with configured vessel capacities of 600 L / 500 L / 500 L. Victron `/Capacity` and `/Remaining` use cubic metres, so those values are published as `0.600 / 0.500 / 0.500 m3` and the corresponding remaining volume in m3. `/Level` remains percent.

### Tanks on Signal K / NMEA 2000 — live

Signal K receives the Victron tank services as:

```text
tanks.freshWater.90
tanks.fuel.91
tanks.fuel.92
```

The standard `signalk-to-nmea2000` plugin has been live-tested forwarding them as PGN 127505 Fluid Level using NMEA tank instances 6, 7, and 8. Signal K then received those PGNs back from the VE.Can/NMEA 2000 connection with matching level and capacity values, proving the output was present on the NMEA 2000 bus.

The live mapping and B&G Zeus3 display/setup guidance are in [`docs/SIGNALK_NMEA2000.md`](docs/SIGNALK_NMEA2000.md). The consolidated standard-PGN register is in [`docs/NMEA2000_MAPPING.md`](docs/NMEA2000_MAPPING.md).

### Source selectors — confirmed, receive-only in bridge

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

The Cerbo bridge only consumes the **applied** IDs and associated panel-voltage telemetry. It never transmits `0x02420B90` or `0x02420B88`.

## Generator lifecycle and control

The generator is represented by three complementary signal families:

| CAN ID | Datatype | Scale / enum | Role |
|---|---|---|---|
| `0x02460B88` | `uint8 enum` | `01=START`, `02=STOP` | External command / transaction trigger; live-tested transmit |
| `0x02440B88` | `uint8 enum` | `00=OFF_IDLE`, `01=RUNNING_SETTLED`, `02/03=STARTING`, `04/05=STOPPING` | Generator lifecycle/status confirmation |
| `0x005A1020` bytes 0-1 | `uint16 little-endian` | x0.1 Hz | Generator-specific AC-frequency milestone |

### START

```text
02460B88#01                 -> STARTING
02440B88#02 or #03          -> STARTING confirmed
005A1020 ~= 50.0 Hz         -> RUNNING after confirmation hold
02440B88#01                 -> RUNNING_SETTLED
```

### STOP

```text
02460B88#02                 -> STOPPING
02440B88#05 or #04          -> STOPPING confirmed
005A1020 = 0.0 Hz           -> STOPPED
02440B88#00                 -> OFF_IDLE
```

The baseline capture contains START, STARTING confirmation, 50 Hz, RUNNING_SETTLED, STOP, STOPPING confirmation, frequency decay, and 0 Hz. It does **not** contain `02440B88#00`; `OFF_IDLE` was confirmed in later live work.

### Live generator-command validation

The exact one-byte commands were successfully transmitted on the installation:

```bash
cansend can2 02460B88#01   # START
cansend can2 02460B88#02   # STOP
```

The production bridge sends those commands only in response to the Victron connected-genset `/Start` command (or observes/adopts an externally generated Scheiber command). It sends no automatic CAN retry.

A key live finding is that `STOPPED` and `OFF_IDLE` are not equivalent for immediate restart. The engine can reach 0 Hz quickly while the Scheiber controller takes roughly another minute to emit `02440B88#00`. A START sent in that settling interval was ignored; a START sent after `OFF_IDLE` worked. Bridge v5.4.2 documents this but does not yet queue an early start.

See [`docs/GENERATOR_LIFECYCLE.md`](docs/GENERATOR_LIFECYCLE.md) and [`docs/CERBO_GX_INTEGRATION.md`](docs/CERBO_GX_INTEGRATION.md).

### Why generator frequency is no longer treated as shared AC

Live testing separated the generator-specific `0x005A1020` signal from the shared `0x02040898` AC telemetry. With the generator off and shore power present, `0x005A1020` stayed at 0 Hz while `0x02040898` still reported approximately 235 V / 50 Hz. The Cerbo bridge therefore uses `0x005A1020` as generator-specific frequency and treats `0x02040898` as shared/fallback AC telemetry only.

### Six house batteries

The six IDs are:

```text
0x06020580  0x06060580  0x060A0580
0x060E0580  0x06120580  0x06160580
```

Each six-byte payload is decoded as:

| Bytes | Type | Interpretation |
|---|---|---|
| 0-1 | `uint16` little-endian, x0.01 | Voltage in volts — confirmed |
| 2-3 | offset `uint16` little-endian, raw - `0x4E00` | Signed current code — zero/sign strong; x0.1 A remains a working scale candidate |
| 4-5 | `uint16` little-endian | SoC percent for this installation — confirmed by follow-on validation |

The older temperature alternative is no longer used by the bridge. Physical battery 1-6 ordering still needs direct validation.

### Three charger families

The repeated device suffixes `0x1008`, `0x1010`, and `0x1020` each have heartbeat, telemetry, configuration, rating, and frequency messages. Their `0x005610xx` payload signatures contain:

| Device family | Constant bytes | Rating interpretation | Role hypothesis |
|---|---|---|---|
| `0x1008` | `0C 3C` | 12 V / 60 A | House/engine charging candidate |
| `0x1010` | `0C 28` | 12 V / 40 A | House/engine charging candidate |
| `0x1020` | `0C 19` | 12 V / 25 A | Generator-start charging family |

For `0x005010xx`, four little-endian `uint16` values plausibly decode as DC voltage x0.1 V, DC current x0.1 A, AC input voltage x0.1 V, and `0xFFFF` unavailable. Example:

```text
00501008#8700D1003809FFFF
          135  209   2360  65535  (little-endian words)
         13.5V 20.9A 236.0V   NA  (candidate engineering units)
```

For `0x005A10xx`, the first little-endian word is an AC-frequency field: `0x01F4 = 500 -> 50.0 Hz`, `0x0190 = 400 -> 40.0 Hz`, and zero when off.

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

These analysis scripts remain passive/read-only.

## Engineering report

The source report is [`docs/ENGINEERING_REPORT.md`](docs/ENGINEERING_REPORT.md). It documents the original hash-identified capture and analysis baseline. Live control validation and the production Cerbo integration are maintained separately in the focused integration/lifecycle documents so the evidence provenance of the original report remains clear.

Rebuild the human-friendly PDF and DOCX with:

```bash
./scripts/build_report.sh
```

## Reproduce a passive capture

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

Scheiber CAN and NMEA 2000 remain separate protocols and separate CAN interfaces.

On the current Cerbo installation the preferred gateway path is:

```text
Scheiber bus -> SH-C30A/can2 -> Victron D-Bus -> Signal K -> VE.Can/NMEA 2000
```

The three tank mappings are now live on NMEA 2000 as standard PGN 127505. Other mappings remain staged according to confidence: generator starter voltage is the recommended next battery value; experimental engine-battery identity/scale and candidate house current are not ready for authoritative NMEA 2000 publication.

See [`docs/SIGNALK_NMEA2000.md`](docs/SIGNALK_NMEA2000.md) and [`docs/NMEA2000_MAPPING.md`](docs/NMEA2000_MAPPING.md).

## Repository layout

```text
cerbo/                  canonical bridge.py, installer, and runit service
config/                 capacities, inventory, mappings
data/raw/               original candump capture (single .xz file)
data/examples/          selected evidence frames
data/derived/           generated CSV/JSON results
scripts/                passive analyzer, lifecycle tracker, and helper tools
docs/                   engineering, mapping, integration, and handoff docs
tests/                  decoder, lifecycle, and bridge-source regression tests
```

## Source references

- DSD TECH SH-C30A official product page: https://www.deshide.com/product-details_SH-C30A.html
- CANable: https://www.canable.io/
- Linux CAN utilities: https://github.com/linux-can/can-utils
- Victron Venus OS: https://github.com/victronenergy/venus
- Victron dbus-generator: https://github.com/victronenergy/dbus_generator
- Victron gui-v2: https://github.com/victronenergy/gui-v2
- Victron VE.Can pinout documentation: https://www.victronenergy.com/media/pg/Venus_GX/en/connecting-supported-non-victron-products.html
- Signal K server: https://github.com/SignalK/signalk-server
- Signal K to NMEA 2000: https://github.com/SignalK/signalk-to-nmea2000
- B&G Zeus3 product specifications: https://www.bandg.com/bg/type/chartplotter/bg-zeus3-9-mfdinsight/
- Scheiber CAN/NMEA gateway: https://www.scheiber.com/can-nmea?lang=en
- canboat NMEA 2000 PGN database: https://canboat.github.io/canboat/canboat.html

## License and disclaimer

Code and original documentation in this repository are provided under the MIT License. The CAN capture remains experimental data from one installation. This project is not affiliated with or endorsed by Scheiber, Victron Energy, DSD TECH, Signal K, B&G, or the NMEA organization.

Generator and AC source control can create hazardous conditions. Only `0x02460B88#01/#02` has been live-validated for active use in the Cerbo bridge described here. Do not infer that other observed request/control frames are safe to transmit.
