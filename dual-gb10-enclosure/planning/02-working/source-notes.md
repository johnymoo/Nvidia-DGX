# Source Notes

Retrieved: 2026-08-17

## xFusion FusionXpark GB10

- Official product page: https://www.xfusion.com/en/product/fusionxpark
- Official technical white paper: https://www.xfusion.com/en/resource/fusionxpark-gb10-white-paper
- Local raw capture: `planning/01-raw/xfusion-fusionxpark-gb10-white-paper.pdf`
- Relevant PDF pages: 4-6 and 11 (document page numbering); rendered PDF pages 9-11 and 16.
- Verified observations:
  - Physical size is 51 x 150 x 150 mm in the official white paper.
  - Net weight is 1.2 kg.
  - The front face is a full-width ventilation grille.
  - The rear face has an upper ventilation grille and a lower port panel.
  - Rear connections include one USB-C power input, three USB-C/DisplayPort ports, HDMI, 10GbE RJ45, and two QSFP ports.
  - The supplied power adapter is rated at 240 W; the power input is USB-C PD at 48 V / 5 A.
  - The internal exploded view shows two internal fans and a heatsink.

## External 140 mm fans

- User-provided captures:
  - `planning/01-raw/fan-140mm-product.jpg`
  - `planning/01-raw/fan-140mm-specs.jpg`
- Claimed size: 140 x 140 x 25 mm.
- Claimed electrical rating: 12 V, 0.22 A each.
- Claimed speed range: 500-2000 RPM +/-10%.
- Claimed maximum airflow: 96.19 CFM.
- Claimed maximum static pressure: 2.87 mmH2O.
- Connector: daisy-chain 4-pin PWM.
- Mounting-hole spacing is not shown and must be measured or confirmed from the exact fan model before final CAD.

## Open questions

- Exact external corner radii, rubber-foot geometry, and tolerance of each GB10 unit.
- Exact 140 mm fan mounting-hole spacing and corner-hole diameter.
- Whether the display/controller should be integrated into the front fan bezel, top panel, or a detachable side pod.
- Which GB10 USB-C port may be allocated to fan/controller power and data.
