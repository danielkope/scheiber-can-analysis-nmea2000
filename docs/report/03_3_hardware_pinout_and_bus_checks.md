# 3. Hardware, pinout, and bus checks

## 3.1 DSD TECH SH-C30A

The SH-C30A is a CANable-derived USB-CAN adapter with a three-pin CAN_H/CAN_L/GND terminal, default Candlelight firmware, a switchable 120-ohm termination resistor, and a programming switch. Candlelight normally exposes a native SocketCAN interface through the Linux gs_usb driver. The SH-C30A has no galvanic isolation; its USB and CAN grounds are referenced.

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th><strong>Recommended switch settings</strong><br />
Programming/boot switch in normal RUN mode. Termination OFF when passively tapping an already correctly terminated network. Enable termination only if the adapter is at a physical bus end and replaces a missing terminator. Determine switch direction from board labels or resistance measurement, not an assumed left/right position.</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

## 3.2 Scheiber six-pin to SH-C30A

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>SCHEIBER 6-pin DSD TECH SH-C30A<br />
<br />
Pin 5 CAN-H ------------------ CAN_H<br />
Pin 6 CAN-L ------------------ CAN_L<br />
Pin 2 GND ------------------ GND<br />
(or Scheiber pin 3, harness-dependent)<br />
<br />
Pin 1 Recovery X not connected<br />
Pin 4 +12 V X NOT connected</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

The SH-C30A is powered from USB. Scheiber pin 4 (+12 V) must not be connected to the adapter. The ground pin discrepancy is preserved from the user-supplied harness note and must be verified on the actual connector before energizing.

## 3.3 Scheiber six-pin to Cerbo GX VE.Can RJ45

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>SCHEIBER 6-pin CERBO GX VE.Can RJ45<br />
<br />
Pin 5 CAN-H ------------------ Pin 7 CAN-H<br />
Pin 6 CAN-L ------------------ Pin 8 CAN-L<br />
Pin 2 GND ------------------ Pin 3 GND / NET-C<br />
(or Scheiber pin 3)<br />
<br />
Pin 1 Recovery X not connected<br />
Pin 4 +12 V X NOT connected</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th><strong>Protocol boundary</strong><br />
This pinout does not make Scheiber traffic NMEA 2000. Scheiber and NMEA 2000 must remain separate CAN segments connected by a gateway with two CAN interfaces.</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

## 3.4 Termination and electrical checks

| **Power-off CAN-H to CAN-L** | **Interpretation**                                       |
|------------------------------|----------------------------------------------------------|
| approximately 60 ohms        | two correct 120-ohm end terminators                      |
| approximately 120 ohms       | one terminator missing                                   |
| approximately 40 ohms        | likely three terminators; disable the adapter terminator |
| near 0 ohms                  | short or wrong measurement point                         |

After bringing the interface up, inspect SocketCAN statistics. A trustworthy capture should remain ERROR-ACTIVE, with no steadily increasing error counters, dropped frames, or bus-off events.

