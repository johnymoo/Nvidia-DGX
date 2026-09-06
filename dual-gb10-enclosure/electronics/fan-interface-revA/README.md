# GB10 fan interface board Rev A

Status: Rev A schematic skeleton entered in JLCEDA Pro; PCB is not production-ready. The schematic still needs physical capacitor selection, reliable net-label attachment, and a clean DRC pass.

JLCEDA Pro project: https://pro.lceda.cn/editor#id=b0cc5f3bf7aa4af2a6af240ee5b11885

Current online checkpoint: J1-J4, Q1, R1-R6, C1-C2, D1 and F1 are placed. D1 is SS34 (LCSC C8678), Q1 is 2N7002 (LCSC C8545), and the resistor values are 1 kOhm, 100 kOhm, 220 Ohm, 4.7 kOhm, 220 Ohm, 4.7 kOhm. C1 has now been replaced with LCSC C970685, a 100 uF/25 V SMD electrolytic (D6.3 x L7.7 mm).

## Purpose

This board lets the ESP32-S3-Touch-LCD-1.47-M control the existing 12 V four-wire fans while the fan power remains on the separate 12 V USB-C supply. The board carries no GB10 48 V power and does not power the display.

## Board definition

- Nominal outline: 40 x 25 mm, 1.6 mm FR-4, two layers.
- Input: J1, 12 V and GND from the external DC5521 supply through a 2-pin terminal.
- Fan outputs: J2 and J3, standard 2.54 mm 1 x 4 headers, pin order `GND / +12V / TACH / PWM`.
- ESP32 interface: J4, 2.54 mm 1 x 6 header, pin order `3V3 / GND / PWM / TACH1 / TACH2 / NC`.
- One shared 25 kHz open-drain PWM bus drives both fans.
- TACH1 and TACH2 remain separate and each has its own 3.3 V pull-up and series resistor.

## Functional limitation

Rev A has no independent hardware watchdog. Firmware must release the PWM line on stale telemetry, invalid temperature data, tach stall, USB disconnect, or reset. Rev B may add a hardware heartbeat timeout after the fan and display pinout has been bench-tested.

## Assembly gates

1. Verify the front fan and Delta B3 fan pin order with a meter and the product datasheets.
2. Verify that both tach outputs are open-collector and tolerate a 3.3 V pull-up.
3. Verify the 1.47-M GPIO assignments before wiring J4; the board does not assume undocumented Waveshare pin numbers.
4. Power the fan rail from a current-limited 12 V supply and test both fans at 100% duty before connecting the ESP32.
5. Confirm the 12 V supply handles simultaneous startup; the rated running current is only about 0.32 A.

## Files

- `netlist.md`: named nets and point-to-point connections.
- `bom.csv`: JLC/LCSC search targets and footprints.
- `pinout.md`: connector pinout and firmware polarity.
- `schematic.svg`: compact review schematic for transcription into JLCEDA Pro.

## Release blockers

- JLCEDA's latest SCH DRC still reports a footprint fatal for component `$1I12` even after the C1 replacement; this needs a clean reload/update or component-manager reconciliation.
- The current PCB canvas remains blank because the schematic-to-PCB update has not completed cleanly.
- The two GND/12V labels visible in the online checkpoint need to be reattached to explicit wires or pin endpoints; do not rely on the current label placement until DRC confirms it.
