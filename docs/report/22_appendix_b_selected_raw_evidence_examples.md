# Appendix B. Selected raw evidence examples

| **Line** | **t (s)** | **Raw frame**             | **Interpretation**                                                                |
|----------|-----------|---------------------------|-----------------------------------------------------------------------------------|
| 72       | 4.212     | 02040580#0054003F004F0001 | Tank frame: 0x0054=84% water, 0x003F=63% diesel 1, 0x004F=79% diesel 2.           |
| 93       | 5.252     | 06020580#35050A4E4800     | House-battery candidate: 0x0535 LE=1333 -> 13.33 V; current code +10; field3=72. |
| 1        | 0.000     | 00561010#84000A000C282CFF | Charger 1010 signature: dynamic words plus 0x0C=12 and 0x28=40 candidate rating.  |
| 25       | 1.464     | 00561008#850080000C3C2CFF | Charger 1008 signature: 0x0C=12 and 0x3C=60 candidate rating.                     |
| 928      | 52.062    | 00561020#000006000C19FAFF | Charger 1020 signature: 0x0C=12 and 0x19=25 candidate rating.                     |
| 1113     | 59.382    | 005A1008#F401FFFFFFFFFFFF | Charger 1008 frequency: 0x01F4 LE=500 -> 50.0 Hz.                                |
| 885      | 49.659    | 02460B88#01               | Confirmed direct generator START command (`uint8 enum` value 1).                  |
| 3427     | 177.378   | 02460B88#02               | Confirmed direct generator STOP command (`uint8 enum` value 2).                   |
| 1276     | 66.076    | 02420B90#01               | AC panel source request OFF (0x01).                                               |
| 1311     | 67.591    | 02400B90#01               | AC panel applied OFF (0x01).                                                      |
| 2028     | 106.121   | 02420B90#02               | AC panel source request SHORE (0x02).                                             |
| 2055     | 107.488   | 02400B90#02               | AC panel applied SHORE (0x02).                                                    |
| 2318     | 121.217   | 02420B90#04               | AC panel source request GENERATOR (0x04).                                         |
| 2353     | 122.773   | 02400B90#01               | AC panel safe intermediate applied OFF.                                           |
| 2365     | 123.375   | 02400B90#04               | AC panel applied GENERATOR.                                                       |
| 2702     | 142.947   | 02420B88#01               | House panel source request OFF.                                                   |
| 2731     | 144.488   | 02400B88#01               | House panel applied OFF.                                                          |
| 2965     | 155.523   | 02420B88#02               | House panel source request SHORE.                                                 |
| 2988     | 156.802   | 02140898#03               | AC/generator module ramp-up marker (0x03).                                        |
| 2992     | 156.877   | 02400B88#02               | House panel applied SHORE.                                                        |
| 3147     | 163.989   | 02420B88#04               | House panel source request GENERATOR.                                             |
| 3181     | 165.549   | 02400B88#01               | House panel safe intermediate applied OFF.                                        |
| 3195     | 166.121   | 02400B88#04               | House panel applied GENERATOR.                                                    |
| 3318     | 171.523   | 02140898#02               | AC/generator module ramp-down marker (0x02).                                      |
| 3680     | 189.600   | 02140898#03               | AC/generator module ramp-up marker (0x03).                                        |
| 1797     | 93.648    | 00501008#8700D1003809FFFF | Charger telemetry hypothesis: 13.5 V DC, 20.9 A, 236.0 V AC, 0xFFFF unavailable.  |

The full raw log is included in data/raw. Selected frames are copied to data/examples/selected_frames.log. Derived CSVs retain source line numbers so every conclusion can be traced back to the original capture.

