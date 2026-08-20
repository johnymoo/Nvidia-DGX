# Temperature-Control Research

Retrieved: 2026-08-19

## OpenThread article assessment

Source:

- <https://mp.weixin.qq.com/s/4zI2G6FQ6X8-VVAKxrv7Rg>

The article describes OpenThread on ESP32-C6/H2 rather than a temperature-control design. ESP32-C6 is suitable as a compact controller platform, but Thread Mesh adds no value to the current single-enclosure topology. USB serial or Wi-Fi should carry GB10 telemetry; the fan safety loop must remain controller-local and must not depend on Thread, Wi-Fi, or a border router.

Compact controller candidate:

- Waveshare ESP32-C6-Zero, 18 x 23.5 mm, USB Type-C, 4 MB flash, Wi-Fi 6, Bluetooth 5, and IEEE 802.15.4/Thread.
- Taobao: <https://detail.tmall.com/item.htm?id=778015195293>
- Indicative price verified on 2026-08-19: CNY 30.
- It has enough exposed GPIO in principle for one PWM command, two separate tachometer inputs, two analog probes, and a small external display. The final carrier still needs an open-drain PWM transistor, tachometer protection, sensor dividers, and a separately load-tested 12 V fan supply.

## NVIDIA DGX Spark documentation

Sources:

- <https://docs.nvidia.com/dgx/dgx-spark/hardware.html>
- <https://docs.nvidia.com/dgx/dgx-spark/known-issues.html>

Verified facts:

- NVIDIA specifies an ideal operating ambient range of 5-30 degrees C and 10-90% relative humidity, non-condensing.
- The system has four USB Type-C connectors, one of which is the power-delivery input.
- The supplied power budget is 240 W: 140 W GB10 SoC TDP and 100 W for the other system components, including USB-C. The documentation does not state the source-current capability of an individual USB-C host port.
- `nvidia-smi` is present on DGX Spark. NVIDIA documents that some iGPU fields, including dedicated framebuffer memory usage, report `Not Supported`.

Design implications:

- The host telemetry agent must probe fields independently and publish per-field validity; one unsupported field must not invalidate temperature data.
- Controller power from a GB10 host port remains conditional on a USB-C current-capability measurement. A protected alternate 5 V input is required.
- Local inlet/exhaust sensors are required so fan safety does not depend on Linux, USB, LAN, or a particular `nvidia-smi` field.

## Supplied 140 mm fan

Source: user-supplied product specification images in the local ignored research cache.

- 140 x 140 x 25 mm
- 12 V DC, 0.22 A rated
- 500-2000 RPM, plus or minus 10%
- 96.19 CFM maximum
- 2.87 mm H2O maximum static pressure
- 35.7 dB(A) maximum
- Four-pin PWM cable with a daisy-chain connector

Design implications:

- Share one 25 kHz open-drain PWM command between the front and rear fans. The daisy-chain carries 12 V, ground, and PWM; both motors are electrically in parallel, not series.
- Keep front and rear tachometer outputs separate. The front tachometer is mandatory; a second ESP32-S3 input for the rear tachometer is recommended so the controller can identify either stalled fan.
- Verify connector pinout and minimum stable PWM duty on the physical fan before connecting it to the controller PCB.
- Size the 12 V rail for both fans' startup current rather than only the 0.22 A front-fan rated current.

## One-channel control decision

Decision: 2026-08-18, confirmed by user.

- One PWM channel controls both enclosure fans at the same duty cycle.
- Independent front/rear temperature curves are out of scope.
- The shared minimum duty is determined by whichever fan has the higher stable minimum.
- A startup boost is applied to both fans together.
- Tachometer sensing is not a PWM channel: use one mandatory front tach input and one optional-but-recommended rear tach input.

## Bare display reference

Sources:

- <https://www.waveshare.com/2.4inch-lcd-module.htm>
- <https://www.waveshare.com/wiki/2.4inch_LCD_Module>

Fallback module: Waveshare 2.4inch LCD Module, SKU 18366.

- 240 x 320 pixels, used as a 320 x 240 landscape display
- ILI9341 controller over four-wire SPI
- 3.3 V or 5 V operation
- 70.5 x 43.3 mm module outline
- 48.96 x 36.72 mm active display area
- No touch layer required

This is no longer the preferred final controller because it requires a separate ESP32 board. Its dimensions remain a useful lower-bound reference for the side pod.

Packaging implication for the bare-display fallback:

- Increase the reversible side pod from 78 to approximately 84 mm along the enclosure depth so the module fits inside real walls and clearances.
- Increase pod projection from 12 to approximately 20 mm for a low-profile controller/power PCB behind the display. With the opposite blank plate, the estimated assembled width remains approximately 176 mm.
- Do not apply the 70.5 x 43.3 mm outline to the integrated ESP32-S3 display board. Freeze the final pod only after obtaining that board's actual dimensions and mounting pattern.

## Taobao module verification

Sources:

- <https://detail.tmall.com/item.htm?id=778015195293>
- <https://item.taobao.com/item.htm?id=1063356175511>
- <https://item.taobao.com/item.htm?id=1059310994163>
- <https://item.taobao.com/item.htm?id=620387103341>
- <https://item.taobao.com/item.htm?id=949779246496>

Verified from the signed-in listing text and product images on 2026-08-18:

- The Waveshare ESP32-C6-Zero listing is CNY 30. The manufacturer dimension drawing confirms an 18 x 23.5 mm PCB and the documentation confirms USB, Wi-Fi, Bluetooth, and IEEE 802.15.4/Thread support. It is the smallest verified controller candidate, but it has no integrated display or fan-power stage.
- The ESP32-S3-Touch-LCD-2.4 listing is CNY 85 and identifies a 240 x 320 N16R8 board. Product images show USB-C and many exposed GPIO headers, sufficient in principle for one PWM output, two tachometer inputs, and two analog probes. The listing still provides no board outline, mounting-hole drawing, or explicit native-USB statement.
- The Jiqu ("Mini Tornado") one-channel board is CNY 18, takes 5 V through Type-C, boosts internally for a four-wire fan, claims a maximum 8 W load, includes an NTC probe and numeric display, and supports automatic/manual speed control. It provides no host communication.
- The Delta AFB0612LB listing is CNY 9.5. The photographed label confirms 12 V and 0.10 A, and the listing offers a four-wire B3 connector option. Nominal 6015 dimensions and the mounting-hole pattern still need physical verification.
- The TPS61088 listing is CNY 12.8 and offers fixed 5 V, 9 V, or 12 V variants. Product photos expose VIN/GND and VOUT/GND pads, but no credible continuous-current or thermal-derating data; ignore the title's "10 A" claim until load-tested.

Design decision:

- Use the CNY 18 integrated board only for an early standalone airflow/temperature test. Its 8 W claim exceeds the fans' approximately 3.84 W combined rated running load, but simultaneous startup may still overload it.
- Use the ESP32-S3 display board plus a separately load-tested 12 V boost stage for the final communicating controller.
- Order the rear fan with the four-wire B3 option, but expect to make or buy an adapter to the supplied front fan's daisy-chain connector after both pinouts are verified.
