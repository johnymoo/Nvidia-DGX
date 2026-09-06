# Rev A named netlist

## Power path

| Net | Connections |
| --- | --- |
| `VIN12_RAW` | J1.1 -> F1.1 |
| `VIN12_PROT` | F1.2 -> D1.K |
| `FAN12` | D1.A -> J2.2, J3.2, C1.1, C2.1 |
| `GND` | J1.2, J2.1, J3.1, C1.2, C2.2, Q1.S, J4.2, R3.2, R5.2 |

D1 is a series Schottky diode. With the stated fan current, its voltage drop is acceptable; confirm temperature during startup testing.

## PWM path

| Net | Connections |
| --- | --- |
| `ESP_PWM` | J4.3 -> R1.1 |
| `PWM_GATE` | R1.2 -> Q1.G, R2.1 |
| `PWM_BUS` | Q1.D -> J2.4, J3.4 |
| `GND` | Q1.S -> ground |

Q1 is 2N7002 in SOT-23. R1 is 1 kOhm gate series resistance. R2 is 100 kOhm gate-source pulldown. The fan's internal pull-up must pull `PWM_BUS` high when Q1 is off; ESP32 firmware uses an inverted command because Q1 sinks the line.

## Tachometer paths

| Net | Connections |
| --- | --- |
| `TACH1_FAN` | J2.3 -> R3.1 |
| `ESP_TACH1` | R3.2 -> J4.4, R4.1 |
| `TACH2_FAN` | J3.3 -> R5.1 |
| `ESP_TACH2` | R5.2 -> J4.5, R6.1 |
| `3V3` | J4.1 -> R4.2, R6.2 |

R3/R5 are 220 Ohm series resistors. R4/R6 are 4.7 kOhm pull-ups to the ESP32 3.3 V rail. Do not join the two tach nets.

## Decoupling

- C1: 100 uF, 25 V electrolytic across `FAN12` and `GND` near J2/J3.
- C2: 100 nF ceramic across `FAN12` and `GND` near J2/J3.
