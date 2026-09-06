# Connector pinout

## Fan connectors J2 and J3

Viewed from the board connector face, use a keyed housing if the selected header supports it.

| Pin | Signal | Meaning |
| ---: | --- | --- |
| 1 | GND | Common signal and motor return |
| 2 | +12V | Fused and reverse-protected fan supply |
| 3 | TACH | Open-collector tach output, kept separate per fan |
| 4 | PWM | Shared open-drain control bus |

The pin order is a design target matching the standard 4-wire PC fan convention. Confirm both physical fan harnesses before inserting them.

## ESP32 connector J4

| Pin | Signal | Firmware role |
| ---: | --- | --- |
| 1 | 3V3 | Pull-up source for tach inputs |
| 2 | GND | Common reference with fan power |
| 3 | PWM | 25 kHz output; duty is inverted at Q1 |
| 4 | TACH1 | Front fan pulse input |
| 5 | TACH2 | Rear fan pulse input |
| 6 | NC | Reserved for Rev B heartbeat; leave unconnected on Rev A |

Firmware defaults:

- GPIO reset or firmware fault: configure PWM pin high impedance so both fans run at their internal default/full-speed state.
- Normal control: 25 kHz, open-drain style; `Q1 ON` means PWM bus low.
- Startup: release PWM for 1 second, then apply the tested minimum duty and ramp up.
- A missing or stale GB10 temperature packet older than 10 seconds releases PWM for full speed.
