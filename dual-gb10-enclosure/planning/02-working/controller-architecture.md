# Controller Architecture

Status: telemetry topology and dual-input power strategy approved; GB10 host-port output remains pending physical validation.

## Approved telemetry topology

- Install a lightweight Linux telemetry service on both GB10 units.
- GB10-1 is the controller host and connects to an ESP32-S3 over USB serial.
- GB10-1 reads its local temperatures and obtains GB10-2 telemetry over the local network.
- GB10-1 sends combined telemetry and control policy updates to the ESP32-S3.
- The ESP32-S3 drives the local 2.8-inch display and both four-pin PWM fan control signals.
- Loss of USB, network telemetry, or either service triggers a controller-local conservative fallback fan speed.

## Preliminary power budget

- Two fans at 12 V x 0.22 A: 5.28 W maximum claimed load.
- ESP32-S3, display, sensors, and conversion losses add approximately 1.5-2.0 W.
- A 5 V source would need approximately 1.5-1.8 A under worst-case operation.
- The official GB10 white paper does not specify the source-current capability of the three USB-C/DisplayPort host ports.
- Do not tap or split the GB10 48 V / 5 A PD input without a separately validated EPR-rated power design.

## Required safety behavior

- Hardware PWM fallback independent of host software.
- Fan tachometer monitoring and stalled-fan alarm.
- Power input protection against reverse current and accidental dual-source backfeed.
- Optional alternate USB-C power input is recommended until GB10 host-port output capability is measured.

## Approved power-input strategy

- Primary input: one GB10-1 USB-C host port for 5 V power plus USB serial communication, subject to measured current capability.
- Alternate input: a dedicated external USB-C 5 V or 9 V supply connection.
- Use a protected power multiplexer or ideal-diode arrangement so the two inputs are mutually isolated and cannot backfeed each other.
- The enclosure and controller PCB remain unchanged if testing requires operation from the alternate input.
