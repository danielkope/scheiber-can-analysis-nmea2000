# Wiring and Raspberry Pi setup

## Scheiber six-pin to SH-C30A

```text
SCHEIBER 6-pin                    DSD TECH SH-C30A

Pin 5  CAN-H  ------------------  CAN_H
Pin 6  CAN-L  ------------------  CAN_L
Pin 2  GND    ------------------  GND
(or Scheiber pin 3, depending on the installed harness)

Pin 1  Recovery  X                not connected
Pin 4  +12 V     X                NOT connected
```

The user-provided ground note is preserved because some harness variants may expose the reference on pin 2 or pin 3. Verify against the actual connector/harness before energizing.

## Scheiber six-pin to Cerbo GX VE.Can RJ45

```text
SCHEIBER 6-pin                    CERBO GX VE.Can RJ45

Pin 5  CAN-H  ------------------  Pin 7  CAN-H
Pin 6  CAN-L  ------------------  Pin 8  CAN-L
Pin 2  GND    ------------------  Pin 3  GND / NET-C
(or Scheiber pin 3)

Pin 1  Recovery  X                not connected
Pin 4  +12 V     X                NOT connected
```

This pinout is electrically useful for a CAN transceiver connection, but a direct wire does **not** translate the proprietary Scheiber protocol into NMEA 2000. Use a protocol gateway and separate bus segments.

## SH-C30A switch guidance

The official SH-C30A description identifies a built-in 120-ohm termination switch and a programming switch. Use:

- **Programming switch:** normal run/Candlelight firmware position.
- **Termination:** OFF for a middle-of-bus passive tap into a correctly terminated network.
- **Termination:** ON only when the SH-C30A is located at a physical end and replaces a missing 120-ohm terminator.

Do not assume a physical left/right switch direction across board revisions. Confirm with markings or by measuring CAN-H to CAN-L with power removed.

## Resistance and voltage checks

With the entire CAN installation powered off:

| CAN-H to CAN-L resistance | Likely condition |
|---:|---|
| about 60 ohms | two correct 120-ohm end terminators |
| about 120 ohms | one terminator missing |
| about 40 ohms | likely three terminators, including an unnecessary adapter terminator |
| near 0 ohms | short circuit or incorrect measurement point |

Powered-bus voltage checks are diagnostic only. Classical high-speed CAN is commonly near 2.5 V on both lines while recessive; during dominant bits CAN-H rises and CAN-L falls. Use an oscilloscope for definitive signal-integrity checks.

## SocketCAN commands

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

A Candlelight/gs_usb adapter should normally appear as a native SocketCAN interface. Check the actual name (`can0`, `can1`, and so on).

## Passive capture

```bash
candump can1
candump -L can1 > scheiber_$(date +%Y%m%d_%H%M%S).log
```

Recommended experiment discipline:

1. Start the logfile and verbally or electronically note the exact start time.
2. Leave all systems unchanged for at least 30 seconds.
3. Change only one physical state.
4. Wait for the network and meters to settle.
5. Record the action and exact timestamp.
6. Return to baseline before the next test.
7. Stop the capture and calculate a SHA-256 hash.

```bash
sha256sum scheiber_*.log
```

## Troubleshooting

### No CAN interface

```bash
lsusb
lsmod | grep -E 'gs_usb|can'
sudo modprobe can
sudo modprobe can_raw
sudo modprobe gs_usb
```

### Interface exists but no traffic

- Confirm 250,000 bit/s.
- Confirm CAN-H and CAN-L have not been swapped.
- Confirm the CAN reference ground.
- Confirm the vessel network is awake.
- Confirm the adapter is not in boot/programming mode.

### Error counters or bus-off

- Stop and disconnect the adapter.
- Check for a third termination resistor.
- Check polarity, common ground, shorts, and loose conductors.
- Reconnect in passive mode only.

### Safety

Do not use `cansend` on a live vessel control bus during discovery. Generator and shore-power commands can bypass expected user-interface safeguards if replayed incorrectly.
