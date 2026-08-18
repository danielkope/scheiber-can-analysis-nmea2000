# Wiring and SocketCAN setup

## Scheiber six-pin to DSD TECH SH-C30A

```text
SCHEIBER 6-pin                    DSD TECH SH-C30A

Pin 5  CAN-H  ------------------  CAN_H
Pin 6  CAN-L  ------------------  CAN_L
Pin 2  GND    ------------------  GND
(or installation-specific pin 3)

Pin 1  Recovery  X                leave open
Pin 4  +12 V     X                NEVER connect to SH-C30A
```

The SH-C30A is USB-powered.

## Termination

For a passive tap into an existing correctly terminated Scheiber bus, leave the SH-C30A 120-ohm termination OFF. With the installation powered down, CAN-H to CAN-L should normally measure about 60 ohms when two 120-ohm end terminators are present.

Approximate diagnosis:

| H-L resistance | Likely condition |
|---:|---|
| ~60 ohms | normal two-end termination |
| ~120 ohms | one terminator missing |
| ~40 ohms | likely third terminator added |
| near 0 | short / incorrect wiring |

Do not assume a physical switch direction across SH-C30A board revisions; use its markings and the resistance measurement.

## Raspberry Pi / Linux passive capture

```bash
sudo apt update
sudo apt install -y can-utils python3 python3-venv python3-pip git

lsusb
sudo dmesg | tail -n 100
ip -details link show

sudo ip link set can1 down 2>/dev/null || true
sudo ip link set can1 type can bitrate 250000 restart-ms 100
sudo ip link set can1 up
ip -details -statistics link show can1
```

The interface may be `can0`, `can1`, etc.

Capture:

```bash
candump can1
candump -L can1 > scheiber_$(date +%Y%m%d_%H%M%S).log
sha256sum scheiber_*.log
```

During reverse engineering, change one physical condition at a time and record exact action timestamps.

## Cerbo GX

The tested production integration uses the same SH-C30A as a USB SocketCAN adapter. On the tested Cerbo it enumerated as `can2` with the kernel `gs_usb` driver.

Basic inspection:

```bash
lsusb
lsmod | grep -E 'gs_usb|can'
ip -details link show
```

The runit wrapper in `cerbo/service/run` configures the selected interface for 250 kbit/s and brings it up. Installation is documented in `CERBO_GX_INTEGRATION.md`.

Do not wire the proprietary Scheiber bus directly to the Cerbo VE.Can/NMEA 2000 bus as though the protocols were interchangeable. The Cerbo integration described here terminates Scheiber CAN at the USB adapter and translates selected data/control through software and D-Bus.

## Troubleshooting

### No CAN interface

On Raspberry Pi:

```bash
lsusb
lsmod | grep -E 'gs_usb|can'
sudo modprobe can
sudo modprobe can_raw
sudo modprobe gs_usb
```

On Venus OS the same modules may already be present; `modprobe` is attempted by the runit wrapper.

### Interface exists but no traffic

- confirm 250,000 bit/s;
- confirm CAN-H/CAN-L polarity;
- confirm common ground;
- confirm the Scheiber network is awake;
- confirm adapter is not in firmware-programming mode;
- confirm termination has not been accidentally added at a mid-bus tap.

### Error counters or bus-off

Stop/disconnect the adapter and correct wiring/termination before continuing. Check:

```bash
ip -details -statistics link show can2
```

for increasing RX/TX errors, drops, or bus-off.

## Safety boundary

Passive discovery should remain read-only. The optional `cerbo/` integration is different: it contains two generator command payloads that were explicitly live-tested on this installation (`02460B88#01` START and `#02` STOP). That validation does not authorize arbitrary replay of other Scheiber frames.

The Cerbo bridge deliberately does not transmit AC/House source-selector requests, unresolved companion frames, or automatic START/STOP retries. Preserve the vessel's generator interlocks and existing safety systems.
