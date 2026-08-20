# Confirmed Constraints

- Enclose two xFusion FusionXpark GB10 units.
- User-stated device size: 150 x 150 x 50.5 mm; official white paper rounds height to 51 mm.
- Device mass: 1.2 kg each.
- Each device is powered independently by its original 240 W USB-C PD adapter.
- The two devices stand on edge, side by side.
- Locate both GB10 units with rounded hard-PETG guide ribs and 0.6-0.8 mm side clearance. Do not use foam or mandatory TPU contact parts; allow optional silicone dots at non-vent edges only if physical testing reveals rattle.
- Preserve each device's native front-to-rear airflow direction.
- Use one 140 x 140 x 25 mm 12 V four-pin PWM fan at the front.
- Mount the 140 mm fan directly to the inner face of the snap-on front bezel with four silicone pins; the fan and bezel remove as one module.
- The supplied front fan is rated 0.22 A, 500-2000 RPM, 96.19 CFM, and 2.87 mm H2O; its connector pinout and minimum stable PWM duty still require bench verification.
- Keep rear connectors exposed; rear assist options must not place a 120/140 mm fan across the connector and cable zones.
- Use one mostly open full-perimeter rear frame with a central 60 x 60 x 15 mm PWM exhaust fan and passive upper/lower bypass.
- Mount the 60 mm fan directly to the rear frame with four silicone pins; do not use an independently sliding fan cassette.
- Attach the complete rear frame to the four-sided main body with two integral rigid upper hooks and two integral lower PETG cantilever latches. Each lower latch releases separately into a 3-4 mm anti-relock opening; rear-fan service may require disconnecting the GB10 rear cables first.
- For A+, provide a fold-down top handle whose fasteners transfer the carrying load into fixed structural crossmembers, not the removable PETG lid alone.
- R2 changes the main enclosure split to a one-piece rounded top-and-side U cover plus a front-loading ribbed bottom plate. Continuous chamfered base tongues engage three self-supporting 45-degree capture-rail segments per side, each approximately 30-35 mm long with lead-in chamfers and debris-relief gaps.
- R2 uses a snap-on front fan bezel with two integral upper hooks and two integral lower PETG cantilever latches. Each lower latch releases separately into a 3-4 mm anti-relock opening; the bezel locks axial base movement but does not carry the vertical device load.
- Both removable fan panels must open 30-40 mm before cable disconnection and use a short service loop plus a keyed fan quick connector.
- Retain exactly two structural M4 bolts for the commercial top handle. Do not add body-panel screws; use silicone fan pins where practical.
- Target 10-12 mm outer U-cover radii, 3-5 mm exposed-edge radii, 3.2-3.6 mm shell walls with local ribs, and at least 75% projected front-grille open area.
- Make the display pod installable on either side with two short hooks, 6-8 mm of downward locking travel, and one bottom release latch; do not use a long side rail. Cover the unused mirrored interface with a thin snap-on blank, and route the harness from a protected base channel into the bottom of the pod. Default presentation remains on the left.
- Use color scheme C (deep-graphite U cover, matte-black front bezel/base/rear frame, and titanium-gray display pod) as the default release presentation. Retain schemes A and B as approved color-only manufacturing alternatives in the print/finishing instructions; all three schemes use identical geometry.
- Add temperature-aware fan control and a local information display.
- Prefer the selected display module's capacitive touch over a separate rotary encoder to reduce parts and enclosure openings.
- Use one shared 25 kHz open-drain PWM output for the front and rear fans. Their 12 V power and PWM wiring may use a daisy-chain connector, but the fan motors remain electrically in parallel.
- Never parallel fan tachometer outputs. Monitor the front tachometer at minimum; retain a separate rear tachometer input for per-fan stall detection.
- Prefer controller power from a GB10 USB-C port and direct USB communication; Wi-Fi is the fallback.
- NVIDIA specifies a 5-30 degrees C ideal operating ambient range but does not publish the source-current capability of each GB10 USB-C host port.
- The enclosure must be printable as multiple parts on a consumer 3D printer and mechanically assembled.
- Generated concept images are for layout confirmation only. Final printable geometry must be parametric and dimension-driven.

## Current layout hypothesis

- Rotate each GB10 90 degrees around its front-to-rear axis.
- Place both units side by side, with their 51 mm thicknesses adding across enclosure width.
- Keep both front grilles facing the intake fan and both rear port panels facing the exhaust fan.
- Use a front plenum to spread a 140 mm square fan across the roughly 102 mm combined device width.
- Fan size, wall thickness, and fastener clearance imply an external enclosure width of approximately 148-154 mm, not 115-125 mm.
- Reserve cable bend space and a split rear exhaust path so cables do not block the upper rear grilles.
