# ESP32 fan interface: proposed replacement of the standalone controller

Date: 2026-09-06
Status: Rev A schematic skeleton entered in JLCEDA Pro; PCB and firmware remain unverified. The online project is [GB10 Fan Interface RevA](https://pro.lceda.cn/editor#id=b0cc5f3bf7aa4af2a6af240ee5b11885).

The concrete Rev A design package is in `electronics/fan-interface-revA/`. It fixes the board target at 40 x 25 mm and keeps the fan power path separate from the GB10 USB-C power path.

The current online checkpoint contains J1-J4, Q1, R1-R6, C1-C2, D1 and F1. C1 has been replaced with LCSC C970685, a 100 uF/25 V SMD electrolytic, but the PCB update still reports a footprint fatal for its component ID; the DRC-reported net-label and footprint errors must be cleared before PCB placement or manufacturing.

## Topology

Reuse the ESP32 on the existing 1.47-M display instead of adding another MCU.
GB10-1 sends its own and GB10-2 telemetry over USB CDC; Wi-Fi is optional fallback.
The side pod houses the display MCU and a small fan-interface daughterboard.
There is no independent temperature controller in the rear connector corridor.

```text
GB10-2 --LAN--> GB10-1 --USB data + 5 V--> ESP32 + display
                                             |
                                25 kHz PWM + heartbeat
                                             |
12 V PD adapter --> protection --> fan-interface daughterboard
                                      |           |
                                 front fan     rear fan
                                      |           |
                                   TACH1        TACH2
                                      +--> protected ESP32 inputs
```

The daughterboard is more than a generic bidirectional level converter:

- One suitably rated NMOS open-drain PWM driver, provisionally a 2N7002-class
  component with guaranteed sink capability at 3.3 V gate drive. Drain connects
  to both fans' PWM pins; source to signal ground. Choose the exact MPN from its
  datasheet before PCB layout. Suggested starting values: 1 kOhm gate resistor
  and 100 kOhm gate-source pull-down. Validate waveform and rise time at 25 kHz.
- Treat GPIO duty as inverted with respect to fan duty: gate-high sinks the PWM
  wire low. Full-speed fallback requires releasing that wire, not driving it high.
  Do not connect a 5 V fan PWM pull-up directly to a bare ESP32 pin.
- Motors receive 12 V in PARALLEL. Daisy-chain connectors do not put motors in
  electrical series. Fan PWM inputs can share one driver only after checking
  both fan pinouts, internal pull-up voltages and summed sink current.
- Two separate tachometer inputs. Never tie tach outputs together. If the actual
  outputs are verified open-collector without incompatible internal pull-ups,
  pull up each to 3.3 V independently and add input protection/series resistance.
  Otherwise use a proven input translation circuit matched to the measured level.
  A divider-only design must not be assumed correct for an unspecified fan.
- Keyed 4-pin fan outputs, fused/current-limited 12 V input, reverse-polarity
  protection, decoupling and strain relief. Signal ground must now be common
  between ESP32 and the fan interface; the old isolated-subsystem ground advice
  does not apply to this new signal-sharing topology.
- No daughterboard 5 V connection back into USB VBUS, no two supplies in parallel,
  no tap into the GB10 48 V / 240 W PD input, and no implied 12 V USB host output.

## Power

Retain the external verified 12 V source for the fans; GB10 USB powers only the
ESP32/display. The prior 0.22 A + 0.10 A fan ratings imply 3.84 W running power,
not peak startup demand. A 12 V / 1 A supply is a starting floor; 2 A provides
more headroom, subject to measured startup current and wiring ratings.
Eliminate the SATA adapter if the selected protected daughterboard accepts the
existing center-positive DC5521 12 V lead directly. Confirm polarity by meter.

## Fail-safe behavior required before this replaces the purchased controller

- Both device temperatures and their freshness are required. Control to the
  higher normalized demand of both devices, using sensor-specific thresholds.
- Stale, missing, invalid or over-temperature telemetry releases PWM for full
  speed. Start with a 10 s maximum age. Do not reuse a 35-50 C ambient/NTC curve
  for GPU junction temperature; they represent different measurements.
- Boot/reset/ESP32 USB power loss must leave the driver off. Verify both exact
  fan models actually default to full speed with PWM open and 12 V present.
- Firmware watchdogs alone are insufficient: a hung CPU can leave LEDC toggling.
  Include a hardware timeout that disables the sink driver unless it receives
  a changing heartbeat from the live control task. It must itself default to
  disabled on power-up/loss and must not be kept alive by autonomous PWM/DMA.
  Exact supervisor/monostable circuit remains to be selected and bench tested.
- Tach stall on either fan raises an alarm and requests full speed for both.
  When 12 V fails, neither MCU nor logic can maintain cooling; report the fault
  if USB power survives. This is auxiliary cooling, not a replacement for GB10's
  native fans or thermal protections.

## Mechanical integration and remaining decisions

Provisional daughterboard envelope: 32 x 24 mm PCB / components up to 10 mm
total stack. It sits below the display inside the existing side pod, not behind
the GB10 ports. Side moves mirror the whole pod, daughterboard and harness.
No unsupported mounting-hole coordinates have been added to production CAD.

Before PCB/CAD freeze: inspect Waveshare's exact **1.47-M** schematic and exposed
connectors; confirm a usable PWM pin, two tach inputs and heartbeat output not
shared with USB/LCD/touch/boot strapping. Avoid substituting a similarly named
board's pin map. If these are not exposed, this reuse is not yet implementable.
Also confirm exact fan electrical interfaces, connector body/mating direction,
USB cable service path, probe policy and power-up/fault test results.

The old Mini Tornado solution remains a documented fallback until these tests
pass. No controller purchase removal or fan rewiring has been performed here.

Source check, 2026-09-06: the exact-name official page
<https://www.waveshare.com/wiki/ESP32-S3-Touch-LCD-1.47-M> returned a missing-article
placeholder ("Our Wiki resources are under urgent production"), not a schematic
or pin table. That response does not establish which GPIO are exposed. Do not
borrow a 1.47 non-M board's pin numbers as verified information.
