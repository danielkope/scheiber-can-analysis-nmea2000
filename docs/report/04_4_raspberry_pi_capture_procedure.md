# 4. Raspberry Pi capture procedure

## 4.1 Install and activate SocketCAN

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>sudo apt update<br />
sudo apt install -y can-utils python3 python3-venv python3-pip git<br />
<br />
lsusb<br />
ip -details link show<br />
<br />
sudo ip link set can1 down 2&gt;/dev/null || true<br />
sudo ip link set can1 type can bitrate 250000 restart-ms 100<br />
sudo ip link set can1 up<br />
ip -details -statistics link show can1</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

The working experiment uses 250,000 bit/s. The device may enumerate as can0 rather than can1. The capture contains eight-hex-digit identifiers, consistent with 29-bit extended CAN IDs.

## 4.2 Capture to a file

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>candump can1<br />
<br />
# Absolute timestamps, easy to pipe and analyze<br />
candump -L can1 &gt; scheiber_$(date +%Y%m%d_%H%M%S).log<br />
<br />
# Alternative: candump-managed logfile<br />
candump -l can1<br />
<br />
sha256sum scheiber_*.log</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

## 4.3 Checks when traffic is missing or corrupt

| **Symptom**               | **Checks**                                                                     |
|---------------------------|--------------------------------------------------------------------------------|
| No interface              | lsusb; dmesg; lsmod; modprobe can, can_raw, gs_usb; verify run/program switch  |
| Interface but no frames   | interface name, 250 kbit/s, network awake, CAN-H/CAN-L polarity, common ground |
| Error-passive or bus-off  | disconnect; check third terminator, polarity, ground, shorts, bitrate          |
| Frames but wrong IDs/data | wrong bus segment, wrong bitrate, adapter firmware mode, electrical noise      |
| Dropped frames            | CPU/storage load, USB stability, candump buffering, interface statistics       |

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th><strong>Read-only rule</strong><br />
Do not use cansend while discovering a live vessel control bus. A replayed source-selector or generator frame may bypass normal interface timing and interlocks.</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

