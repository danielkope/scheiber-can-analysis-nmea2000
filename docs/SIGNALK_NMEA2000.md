# Signal K, Venus OS and B&G Zeus3 integration

This document describes the **live-tested** path from the Scheiber CAN bridge on a Victron Cerbo GX to the vessel NMEA 2000 / VE.Can network and a B&G Zeus3.

The key finding is that the three Scheiber tank services are already exported to NMEA 2000 by **Venus OS native NMEA 2000-out**. Signal K is useful for inspection and loopback verification, but the `Signal K to NMEA 2000` tank converter is **not** required for these tanks and should not be enabled in parallel.

## Tested architecture

```text
Scheiber proprietary CAN
        |
        | SH-C30A / gs_usb
        v
can0 @ 250 kbit/s
        |
        v
cerbo/bridge.py
        |
        v
Victron D-Bus tank services
        |
        +------------------------------+
        |                              |
        v                              v
Victron Venus Plugin             Venus OS native
(D-Bus -> Signal K)              NMEA 2000-out (can1)
        |                              |
        v                              v
tanks.freshWater.90              PGN 127505
tanks.fuel.91                    tank instance 6/7/8
tanks.fuel.92                         |
        |                              v
        |                        VE.Can / NMEA 2000 (can1)
        |                              |
        |                              +--> B&G Zeus3
        |                              |
        +<-- n2k-on-ve.can-socket -----+
             loopback decode (can1)
```

Do **not** electrically join `can0` (Scheiber) to `can1` (NMEA 2000). They are separate CAN networks even though both run at 250 kbit/s. In `/data/conf/signalk/settings.json`, the provider `n2k-on-ve.can-socket` must be set to `can1`.

## Live-tested tank services

The bridge publishes:

```text
com.victronenergy.tank.scheiber_fresh
com.victronenergy.tank.scheiber_diesel1
com.victronenergy.tank.scheiber_diesel2
```

The Venus Signal K integration exposes them as:

```text
tanks.freshWater.90
tanks.fuel.91
tanks.fuel.92
```

The vessel capacities are:

```text
Fresh water    600 L = 0.600 m3
Diesel tank 1  500 L = 0.500 m3
Diesel tank 2  500 L = 0.500 m3
```

Victron D-Bus `/Capacity` and `/Remaining` are cubic metres. Signal K tank level is a ratio internally.

## The three different sets of numbers

Do not confuse these identifiers:

| Numbers | Meaning |
|---|---|
| `90 / 91 / 92` | Venus/Signal K tank-path instances created from the three D-Bus services |
| `6 / 7 / 8` | NMEA 2000 tank instances observed in PGN 127505 |
| `209 / 210 / 211` | NMEA 2000 source addresses observed during address claim |

The NMEA source addresses are not stable configuration identifiers and can change after address claiming.

## Live NMEA 2000 loopback evidence

On the tested Cerbo the native Venus NMEA 2000-out path produced PGN 127505, which Signal K decoded back through `n2k-on-ve.can-socket` as:

```text
tanks.freshWater.6.capacity      0.600 m3   n2k-on-ve.can-socket.209 (127505)
tanks.freshWater.6.currentLevel  0.71       n2k-on-ve.can-socket.209 (127505)

tanks.fuel.7.capacity            0.500 m3   n2k-on-ve.can-socket.210 (127505)
tanks.fuel.7.currentLevel        ~0.63      n2k-on-ve.can-socket.210 (127505)

tanks.fuel.8.capacity            0.500 m3   n2k-on-ve.can-socket.211 (127505)
tanks.fuel.8.currentLevel        0.79       n2k-on-ve.can-socket.211 (127505)
```

The matching Venus-side sources were:

```text
tanks.freshWater.90.currentLevel  0.71
tanks.freshWater.90.capacity      0.600

tanks.fuel.91.currentLevel        0.63
tanks.fuel.91.capacity            0.500

tanks.fuel.92.currentLevel        0.79
tanks.fuel.92.capacity            0.500
```

## Native NMEA 2000 Gateway (`cerbo/nmea2000_bridge.py`)

In addition to native Venus OS tank export, the dedicated **Scheiber NMEA 2000 Gateway** (`/service/scheiber-n2k`) operates directly on **`can1`** to publish starter battery voltages and provide bi-directional digital switching for the B&G Zeus3 chartplotter:

### 1. Starter Battery Status (`PGN 127508 - 0x1F214`)

Broadcast at 1.0 Hz with 0.01 V resolution:

| Battery Instance | Channel / Battery | D-Bus Source Service | NMEA 2000 Destination |
|:---:|---|---|---|
| **Instance 0** | **Port Engine Starter** | `com.victronenergy.battery.scheiber_engine_port` | B&G Engine 1 Gauge & Battery Bar |
| **Instance 1** | **Starboard Engine Starter** | `com.victronenergy.battery.scheiber_engine_starboard` | B&G Engine 2 Gauge & Battery Bar |
| **Instance 2** | **Generator Starter** | `com.victronenergy.battery.scheiber_generator_starter` | B&G Generator Gauge & Battery Bar |

### 2. Binary Switch Bank Status & Control (`PGN 127501` & `PGN 127502`)

Provides native digital switching on the B&G Zeus3 touch screen for all 15 vessel circuits:

* **`PGN 127501` (Binary Switch Bank Status)**: Broadcast at 1.0 Hz and instantly on any D-Bus state change.
* **`PGN 127502` (Binary Switch Bank Control)**: Listens for commands from B&G Zeus3 to toggle physical Scheiber Multibloc V8 relays.

| Channel | Function / Name | Default State | B&G Switch Tile |
|:---:|---|:---:|---|
| **0** | **Anchor Light** | 0 (OFF) | Toggle Switch / Auto Rule |
| **1** | **Navigation Lights** | 0 (OFF) | Toggle Switch |
| **2** | **Steaming / Engine Light** | 0 (OFF) | Toggle Switch |
| **3** | **Deck Floodlight** | 0 (OFF) | Toggle Switch |
| **4** | **Cockpit Lights** | 0 (OFF) | Toggle Switch |
| **5** | **Saloon Lights** | 0 (OFF) | Toggle Switch |
| **6** | **Cabin Lights** | 0 (OFF) | Toggle Switch |
| **7** | **Fresh Water Pump** | 1 (ON) | Toggle Switch |
| **8** | **Refrigeration** | 1 (ON) | Toggle Switch |
| **9** | **Auxiliary / 12V Sockets** | 1 (ON) | Toggle Switch |
| **10** | **Port Bilge Auto** | 1 (ON) | Status Indicator |
| **11** | **Port Bilge Manual** | 0 (OFF) | Momentary / Toggle |
| **12** | **Starboard Bilge Auto** | 1 (ON) | Status Indicator |
| **13** | **Starboard Bilge Manual** | 0 (OFF) | Momentary / Toggle |
| **14** | **Shower / Sump Pump** | 0 (OFF) | Toggle Switch |

---

## Signal K configuration

### Keep the Victron Venus Plugin enabled

The Victron Venus Plugin is the D-Bus -> Signal K side of the integration. It is why the original services appear as:

```text
tanks.freshWater.90
tanks.fuel.91
tanks.fuel.92
```

Leave it enabled.

### Leave `n2k-on-ve.can-socket` alone

This is the working NMEA 2000 / VE.Can input connection on the tested Cerbo. It is also what makes the useful PGN 127505 loopback visible in Signal K.

Do not create a new NMEA 2000 connection on `can2`; `can2` belongs to the proprietary Scheiber network.

### Do not duplicate the tank output in `Signal K to NMEA 2000`

For these three tanks:

```text
Server -> Plugin Config -> Signal K to NMEA 2000 -> Tank Levels (127505)
```

should remain **disabled**.

Do not add mappings such as:

```text
tanks.freshWater.90 -> 0
tanks.fuel.91       -> 1
tanks.fuel.92       -> 2
```

and do not re-publish the loopback paths `.6/.7/.8`.

Venus OS is already publishing the tanks. Enabling a second tank publisher can create duplicate PGN 127505 sources and confusing source selection on the MFD.

## Reproducible verification on the Cerbo

### 1. Verify the bridge D-Bus services

```bash
for s in \
  com.victronenergy.tank.scheiber_fresh \
  com.victronenergy.tank.scheiber_diesel1 \
  com.victronenergy.tank.scheiber_diesel2
do
    echo "===== $s ====="
    for p in Level Capacity Remaining FluidType CustomName; do
        printf '%-12s ' "$p:"
        dbus -y "$s" "/$p" GetValue
    done
done
```

Expected capacities:

```text
fresh   0.600 m3
diesel1 0.500 m3
diesel2 0.500 m3
```

### 2. Verify Signal K's Venus-side tank tree

```bash
curl -s http://127.0.0.1:3000/signalk/v1/api/vessels/self/tanks
printf '\n'
```

A healthy result should contain both the Venus paths and the NMEA loopback paths, for example:

```text
freshWater.90  source venus.com.victronenergy.tank.scheiber_fresh
fuel.91        source venus.com.victronenergy.tank.scheiber_diesel1
fuel.92        source venus.com.victronenergy.tank.scheiber_diesel2

freshWater.6   source n2k-on-ve.can-socket.<src>, pgn 127505
fuel.7         source n2k-on-ve.can-socket.<src>, pgn 127505
fuel.8         source n2k-on-ve.can-socket.<src>, pgn 127505
```

If the `.90/.91/.92` paths are absent, troubleshoot D-Bus -> Venus Plugin first.

If `.90/.91/.92` exist but there is no PGN 127505 loopback, troubleshoot Venus NMEA 2000-out / VE.Can before touching the Zeus3.

If PGN 127505 loopback is present and the Zeus3 is blank, the gateway is already working: troubleshoot **B&G source selection**.

## B&G Zeus3 setup: the live-tested fix

The successful fix on the Zeus3 was to manually select the correct fluid-level sources in the B&G network/source configuration.

Menu labels vary slightly by Zeus3 software revision, but navigate to the network data-source selection area, approximately:

```text
Settings
  -> Network
  -> Sources
  -> Advanced
  -> Data source selection
```

Find the incoming Fluid Level / tank sources created by the Cerbo/Venus gateway and assign/select them for the corresponding data items.

The live installation uses the NMEA tank instances already assigned by Venus:

```text
instance 6  = Fresh Water
instance 7  = Diesel Tank 1 / Fuel Port
instance 8  = Diesel Tank 2 / Fuel Starboard
```

Do not key the setup to CAN source addresses such as `209/210/211`; those may change.

After the sources are selected, configure meaningful labels/locations on the Zeus3 as available, for example:

```text
Fresh Water
Fuel Port
Fuel STBD
```

The tested Zeus3 then displayed the tank values correctly without renumbering the tanks to 0/1/2.

## What success looks like

Field photographs and Cerbo screenshots are kept in [`INTEGRATION_RESULTS.md`](INTEGRATION_RESULTS.md). They show:

- the Zeus3 displaying fresh-water percentage and both fuel volumes;
- the Cerbo GX showing all three tanks;
- native Victron generator control backed by the Scheiber bridge;
- the individual Scheiber house-battery services in the Cerbo UI.

## Troubleshooting Decision Tree & Runbook Checklist

### Incident Post-Mortem: Core NMEA 2000 & B&G Zeus3 Integration Discoveries

During engineering and testing, three critical root causes were identified and resolved:

#### 1. The "Unknown Tank" Root Cause (Tank Instance Mismatch)
* **Symptom**: The B&G Zeus3 displayed `Scheiber Tank Sensor 501.7 Unknown Tank` and `501.8 Unknown Tank`.
* **Root Cause**: 
  - Venus OS's `vecan-dbus` assigned arbitrary high instance numbers (`6`, `7`, `8`) in `/Settings/Vecan/can1/Forward/tank/{N}/FluidInstance0`.
  - Navico NOS (B&G Zeus3 / Simrad) firmware strictly expects:
    - **Fresh Water**: `FluidType = 1` (Water), **`FluidInstance = 0`** &rarr; Mapped to standard Water Gauge.
    - **Port / Main Fuel**: `FluidType = 0` (Fuel), **`FluidInstance = 0`** &rarr; Mapped to Port Fuel Gauge.
    - **Starboard / Aux Fuel**: `FluidType = 0` (Fuel), **`FluidInstance = 1`** &rarr; Mapped to Starboard Fuel Gauge.
  - When the Zeus3 received Fluid Instance `7` or `8`, it fell back to unassigned `"Unknown Tank"`.
* **Resolution**: Configured `/Settings/Vecan/can1/Forward/tank/` with `FluidInstance0 = 0` (Fresh Water), `FluidInstance0 = 0` (Port Diesel), and `FluidInstance0 = 1` (Starboard Diesel), plus explicit `Description2` installation strings (`Fresh Water`, `Port Diesel`, `Starboard Diesel`).

#### 2. The Digital Switching Visibility Root Cause (CAN Priority 3 Filter)
* **Symptom**: The Zeus3 Digital Switching menu showed internal Autopilot and SmartShunt relays but failed to discover the Scheiber 15-channel switch bank.
* **Root Cause**:
  - The NMEA 2000 standard defines default priority **`3`** (`0x0DF20Dxx`) for **`PGN 127501` (Binary Status Report)**.
  - The bridge was initially transmitting with priority `6` (`0x19F20Dxx`).
  - Navico B&G Zeus3 hardware CAN reception filters specifically accept only Priority 3 frames for binary switch banks, silently discarding lower-priority broadcasts.
* **Resolution**: Updated `cerbo/nmea2000_bridge.py` to construct CAN IDs using Priority 3: `can_id = (3 << 26) | (0x1F20D << 8) | self.addr` (`0x0DF20D69`).

#### 3. The 64-bit NAME Device Class Requirement
* **Symptom**: The switch gateway was categorized near steering/autopilot devices.
* **Root Cause**: The bridge used Device Class `60` (Propulsion/Navigation).
* **Resolution**: Updated the ISO 64-bit NAME register to official N2K **Device Class `30` (Electrical Distribution)** and **Device Function `140` (Load Controller / Binary Switch Bank)** with full **PGN 126996/126998 Fast-Packet product info** responses.

#### 4. The VE.Can N2K Gateway Port Mapping
* **Symptom**: SmartShunt DC Detailed Status (`PGN 127506`), SoC, Solar MPPT, and Inverter data vanished from the vessel network.
* **Root Cause**: Victron settings had `Vecan/can0/N2kGatewayEnabled = 1` (exporting to the isolated Scheiber bus) and `Vecan/can1/N2kGatewayEnabled = 0` (disabled on the actual vessel N2K backbone).
* **Resolution**: Enforced `Vecan/can1/N2kGatewayEnabled = 1` and `Vecan/can0/N2kGatewayEnabled = 0` in `install.sh` and `/data/rc.local`.

---

### Quick Inspection Runbook (If CAN Ports Remap Again)

Follow these steps in order if NMEA 2000 data disappears or CAN ports remap after a hardware change:

#### Step 1: Identify Physical CAN Bus Roles
Run `candump` on both interfaces to confirm which is Scheiber and which is NMEA 2000:
```bash
# Scheiber bus shows 0x02040580, 0x00001008, 0x00001020, 0x02040898:
candump -n 5 can0

# NMEA 2000 bus shows fast packets from B&G (0x09F8010A, 0x0DF11309, 0x09F11209):
candump -n 5 can1
```

#### Step 2: Verify & Fix Victron VE.Can Gateway Settings
Ensure `can1` is the active N2K gateway in Venus OS:
```bash
dbus -y com.victronenergy.settings /Settings/Vecan/can1/N2kGatewayEnabled SetValue 1
dbus -y com.victronenergy.settings /Settings/Vecan/can0/N2kGatewayEnabled SetValue 0
svc -t /service/vecan-dbus.can1
```

#### Step 3: Verify Signal K Interface
Ensure `/data/conf/signalk/settings.json` points to `can1`:
```bash
jq '.pipedProviders[] | select(.id == "n2k-on-ve.can-socket") | .pipeElements[].options.subOptions.interface' /data/conf/signalk/settings.json
# Should return "can1"
```

#### Step 4: Verify NMEA 2000 Gateway Service (`scheiber-n2k`)
Ensure `/service/scheiber-n2k` is actively broadcasting standard PGNs on `can1`:
```bash
# Check service process
ps | grep -i nmea2000_bridge

# Monitor live PGN broadcasts from address 0x69 (105)
python3 /tmp/monitor_n2k.py
```

Expected output:
* `PGN 127505` (Fluid Level): Fresh Water (Inst 0, 600L), Diesel 1 (Inst 0, 500L), Diesel 2 (Inst 1, 500L)
* `PGN 127508` (Battery Status): Port (Inst 0), Starboard (Inst 1), Generator (Inst 2)
* `PGN 127501` (Binary Switch Bank): Bank 1 (15 Channels - Scheiber Multibloc V8)

#### Step 5: Refresh Chartplotter Data Sources (B&G Zeus3)
On the B&G Zeus3 screen:
1. Navigate to **Settings &rarr; Network &rarr; Sources**.
2. Tap **Auto Select** to re-bind to the newly claimed N2K dynamic source addresses.
3. Under **Fuel** and **Fresh Water**, confirm Port Fuel (Inst 0), Starboard Fuel (Inst 1), and Fresh Water (Inst 0) are acquired.

---

## Digital Switching & CZone Integration Architecture (B&G Zeus3 / Zeus3S)

### 1. The Subsystem Relationship
On Navico MFDs (B&G Zeus3, Zeus3S, Simrad NSS evo3), the **"Digital Switching"** interface is built directly on top of the **CZone** switching engine. When the Zeus3 prompts for an active switching configuration under **Settings &rarr; Advanced &rarr; Features &rarr; Switching**, it expects a `.zcf` (CZone Configuration File).

### 2. Supported Control Modes on the Zeus3

| Method | Transport | Configuration Required | Description |
|---|:---:|:---:|---|
| **A. Native Instrument Tiles** | NMEA 2000 (`can1`) | **Zero** | Add individual toggle switches or indicators to any chart/gauge page via **Menu &rarr; Edit Layout &rarr; Add Tile &rarr; Electrical &rarr; Switch Bank 1**. |
| **B. CZone Control Bar / Tab** | NMEA 2000 (`can1`) | `Scheiber_Zeus.zcf` on Micro-SD | Generates Navico's dedicated graphical switching tab with icons, group pages (*Lighting*, *Pumps*, *Domestic*), and mode presets. |
| **C. Victron Marine MFD App** | Hardwired Ethernet (`eth0`) | `Services/MqttLocal = 1` | Automatically renders the full-screen Victron MFD app on the Zeus3 carousel with all 15 switch cards, tanks, generator start/stop, and SmartShunt SoC. |

### 3. CZone COI Circuit Mapping Table (for `.zcf` Generation)
To generate the `Scheiber_Zeus.zcf` file using the free **CZone Configuration Tool** (v2.x):
* **Module**: Combination Output Interface (COI) or Output Interface (OI)
* **Dipswitch**: `00000001` (Address `1` / Bank `1`)

| Circuit # | Channel Name | Recommended Icon | Control Type | Scheiber Relays |
|:---:|---|---|---|---|
| **1** | Anchor Light | Anchor / 360° Light | Toggle On/Off | Channel 0 |
| **2** | Navigation Lights | Port/Stbd Bow Lights | Toggle On/Off | Channel 1 |
| **3** | Steaming Light | Mast Light | Toggle On/Off | Channel 2 |
| **4** | Deck Flood Lights | Floodlight | Toggle On/Off | Channel 3 |
| **5** | Cockpit Lights | Cockpit / Exterior | Toggle On/Off | Channel 4 |
| **6** | Saloon Lights | Ceiling Light | Toggle On/Off | Channel 5 |
| **7** | Cabin Lights | Bed / Interior Light | Toggle On/Off | Channel 6 |
| **8** | Fresh Water Pump | Water Faucet / Pump | Toggle On/Off | Channel 7 |
| **9** | Refrigeration | Snowflake / Fridge | Toggle On/Off | Channel 8 |
| **10** | 12V Domestic Sockets | Power Plug | Toggle On/Off | Channel 9 |
| **11** | Port Bilge Pump | Bilge Pump | Toggle On/Off | Channel 10 |
| **12** | Starboard Bilge Pump | Bilge Pump | Toggle On/Off | Channel 11 |
| **13** | Engine Room Light | Lightbulb | Toggle On/Off | Channel 12 |
| **14** | Auxiliary 1 | Generic Switch | Toggle On/Off | Channel 13 |
| **15** | Auxiliary 2 | Generic Switch | Toggle On/Off | Channel 14 |

A Signal K server restart is normally unnecessary when the REST tree is updating and PGN 127505 loopback is fresh.

For diagnostics only, the Venus OS Signal K service is supervised at:

```text
/service/signalk-server
```

Status:

```bash
svstat /service/signalk-server
```

Clean stop/start if genuinely required:

```bash
svc -d /service/signalk-server
sleep 2
svc -u /service/signalk-server
svstat /service/signalk-server
```

Do not reboot the entire Cerbo merely to refresh tank source selection.

## Current integration boundary

Tanks are live and validated on both Cerbo and Zeus3.

Keep other NMEA 2000 publication deliberate and incremental. In particular, candidate house-current scaling and experimental engine-battery identity/scale should not be published as authoritative values until separately validated.

## References

- Victron Cerbo GX marine MFD / NMEA 2000 integration documentation: <https://www.victronenergy.com/media/pg/Cerbo_GX/en/marine-mfd-integration-by-nmea-2000.html>
- Signal K server: <https://github.com/SignalK/signalk-server>
- Signal K to NMEA 2000 plugin: <https://github.com/SignalK/signalk-to-nmea2000>
- B&G Zeus3 manuals: <https://ww2.bandg.com/downloads-category/zeus3-chartplotters-manuals/>
