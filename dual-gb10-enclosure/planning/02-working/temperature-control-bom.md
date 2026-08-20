# Temperature-Control BOM

Status: recommended module-based prototype, pending seller confirmation and bench measurements.

Retrieved: 2026-08-19

## Recommended purchase list

| Item | Qty | Candidate | Known size/specification | Indicative price | Source |
| --- | ---: | --- | --- | ---: | --- |
| Display/controller | 1 | ESP32-S3-Touch-LCD-2.4, N16R8, 240 x 320 | PCB outline and free GPIO still require seller confirmation | CNY 85 | <https://item.taobao.com/item.htm?id=1063356175511> |
| Compact controller alternative | 1 | Waveshare ESP32-C6-Zero | 18 x 23.5 mm; USB-C, 4 MB flash, Wi-Fi 6, Bluetooth 5, IEEE 802.15.4/Thread; requires a separate display and fan interface | CNY 30 | <https://detail.tmall.com/item.htm?id=778015195293> |
| Rear fan | 1 | Delta AFB0612LB, 4-wire PWM | 60 x 60 x 15 mm, 12 V, 0.10 A; verify 50 mm holes and pinout | CNY 9.5 | <https://item.taobao.com/item.htm?id=620387103341> |
| 5 V to 12 V converter | 1 | TPS61088 boost module, fixed 12 V option | Claimed current ratings are not accepted without load testing | CNY 12.8 | <https://item.taobao.com/item.htm?id=949779246496> |
| NTC probes | 2 | 10K B3950 wired probes | One front inlet, one rear exhaust | CNY 5-15 total | Purchase with suitable lead length |
| Fan interface parts | 1 set | Small carrier/perfboard, 4-pin fan headers/adapters, open-drain PWM transistor, tach pull-ups/protection, fuse/polyfuse | One fail-full-speed PWM output, two independent tach inputs | CNY 15-30 | Generic parts |
| Alternate power input | 1 | Protected 5 V USB-C input module/cable | Temporary prototype input until GB10 USB-C source current is measured | CNY 10-25 | Select a board with reverse-current protection |

Estimated electronics subtotal excluding the supplied 140 mm fan: approximately CNY 137-177 before shipping.

Choose either the integrated ESP32-S3 display/controller or the compact ESP32-C6-Zero, not both, for the final build. The ESP32-C6-Zero is useful when minimum PCB size matters; OpenThread is not required for this enclosure and should not be part of the safety-critical fan-control path.

The ESP32-S3 listing photos confirm USB-C and ample exposed GPIO, but not the PCB dimensions or native-USB implementation. The TPS61088 listing price is CNY 12.8 for selectable fixed 5/9/12 V variants; its advertised "10 A" is not a usable engineering rating.

## Standalone thermal-test shortcut

For the first airflow test only, the CNY 18 Jiqu "Mini Tornado" board can replace the ESP32-S3, separate boost module, PWM transistor, and probe interface:

- Taobao: <https://item.taobao.com/item.htm?id=1059310994163>
- 5 V Type-C input, internal 12 V boost, one temperature-controlled PWM command, NTC probe, and numeric display.
- Listing claims 8 W maximum load versus approximately 3.84 W combined fan rated load.
- No USB, Wi-Fi, telemetry API, or integration with the final side display.
- Treat the 8 W rating as unverified until both fans start simultaneously from a 5 V source without output collapse or overheating.

## Wiring decision

- One 25 kHz open-drain PWM output is split to both fan PWM pins.
- Use an external open-drain transistor so an ESP32 reset releases the PWM line and the fans default to full speed; do not drive the fan PWM pins push-pull from a GPIO.
- Both fans receive 12 V and ground in parallel, optionally through the supplied daisy-chain connector.
- Front and rear tachometer lines go to separate ESP32-S3 GPIO inputs. Do not connect tachometer wires together.
- If GPIO is constrained, retain the front tachometer and leave the rear tachometer disconnected; this does not change the one-channel PWM design.

## Purchase gates

Do not freeze the controller pod or order a custom carrier PCB until these points are confirmed:

1. ESP32-S3 module outer dimensions, mounting-hole pattern, native USB data support, and free GPIO count.
2. TPS61088 module dimensions and stable 12 V output during simultaneous fan startup.
3. Rear fan mounting-hole spacing, connector pinout, tach pulses per revolution, and minimum stable PWM duty.
4. GB10 USB-C host-port continuous 5 V source capability. Never connect the controller to the 48 V / 5 A EPR power input.
