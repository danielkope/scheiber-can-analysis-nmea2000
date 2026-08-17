# Appendix C. References and external technical sources

| **Ref** | **Source**                                                                 | **Location**                                                                                      | **Use in this report**                                                                                 |
|---------|----------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------|
| R1      | DSD TECH, SH-C30A USB to CAN Bus Adapter, official product page.           | https://www.deshide.com/product-details_SH-C30A.html                                              | CANable-derived hardware, Candlelight firmware, CAN_H/CAN_L/GND, termination and programming switches. |
| R2      | CANable, open-source USB-CAN adapter.                                      | https://www.canable.io/                                                                           | Candlelight/native SocketCAN and CANable background.                                                   |
| R3      | linux-can/can-utils.                                                       | https://github.com/linux-can/can-utils                                                            | candump, canplayer, cansend and SocketCAN utilities.                                                   |
| R4      | Victron Energy, connecting supported non-Victron products / VE.Can pinout. | https://www.victronenergy.com/media/pg/Venus_GX/en/connecting-supported-non-victron-products.html | VE.Can RJ45 pin 3 NET-C/GND, pin 7 CAN-H, pin 8 CAN-L; termination guidance.                           |
| R5      | Scheiber, CAN/NMEA gateway.                                                | https://www.scheiber.com/can-nmea?lang=en                                                         | Confirms a gateway is used to connect Scheiber CAN and an NMEA 2000 CAN network.                       |
| R6      | canboat PGN database.                                                      | https://canboat.github.io/canboat/canboat.html                                                    | PGNs 127503-127510, 127514, and related NMEA 2000 field definitions.                                   |
| R7      | User-supplied experiment description and raw candump capture.              | Local evidence package                                                                            | Action order, tank capacities, battery/charger inventory, and Scheiber six-pin wiring.                 |

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th><strong>Final engineering position</strong><br />
Tank fields, source-selector enum/request/applied roles, direct generator command semantics, AC voltage/frequency, and six house-battery voltages are strong enough for receive-only integration. Charger ratings and telemetry are credible candidates. Current scale, SoC/temperature, starter-battery assignments, and generator command transmission safety require controlled validation before operational use.</th>
</tr>
</thead>
<tbody>
</tbody>
</table>
