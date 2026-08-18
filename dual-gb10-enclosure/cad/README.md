# Dual GB10 A+ Printable CAD Prototype

This package is the parameter-driven A+ enclosure selected during visual review:

- two xFusion FusionXpark GB10 units standing on their 50.5 x 150 mm side faces;
- one front 140 x 140 x 25 mm intake fan;
- one central rear 60 x 60 x 15 mm exhaust-assist fan;
- passive rear bypass windows above and below the 60 mm fan;
- exposed left/right rear connector columns;
- a removable top, two load-bearing handle crossbars, and a fold-down strap;
- a display pod that can be installed on either side.

## Prototype Status

The STL and STEP files are printable engineering prototypes, not a final production release. Four physical measurements are still required:

1. both GB10 units, including corner radii, feet, and real manufacturing spread;
2. the supplied 140 mm fan hole spacing and frame thickness;
3. the selected 60 mm PWM fan hole spacing and frame thickness;
4. the display PCB, screen window, encoder, and connector locations.

Print the three fit gauges before committing to the main shell.

## Approved Envelope

- Body without side display treatment: 152 W x 218 D x 166 H mm.
- Main body plus reversible side rails: 158 mm maximum width.
- Left display plus opposite blank installed: approximately 168 mm total width.
- Raised handle is a carrying state and is not included in the 166 mm body height.
- Largest print part: 158 x 158 x 162 mm.
- Required printer volume: at least 180 x 180 x 180 mm.

The 218 mm depth is split across a 35 mm front fan module, a 158 mm main shell, and a rear module that protrudes 25 mm while overlapping the shell attachment by 2 mm.

## Print These First

Located in `fit-gauges/`:

- `gb10_pair_fit_gauge`: verifies both device thicknesses, center divider, and outside guide clearance.
- `fan140_mount_gauge`: verifies the provisional 124.5 mm front fan hole spacing.
- `fan60_mount_gauge`: verifies the provisional 50 mm rear fan hole spacing.

Do not scale STL files in the slicer. Change dimensions in `Params` and regenerate instead.

## Printable Parts

| File | Qty | Material | Purpose |
| --- | ---: | --- | --- |
| `main_u_shell` | 1 | PETG | Base, side walls, device guides, rear rails, display rails |
| `front_140_module` | 1 | PETG | Front fan frame, mounting web, guard, shell tongue |
| `rear_60_module` | 1 | PETG | Semi-open rear fan bridge and passive bypass |
| `top_lid` | 1 | PETG | Removable top with handle-boss clearances |
| `handle_crossbar` | 2 | PETG | Transfers carrying load into both side walls |
| `handle_strap_tpu` | 1 | TPU 95A | Flat flexible prototype strap |
| `tpu_device_pad` | 4 | TPU 95A | Replaceable lower device contacts |
| `display_pod_left` or `display_pod_right` | 1 | PETG | Selected display side |
| `display_blank_left` or `display_blank_right` | 1 | PETG | Covers the unused side rails |

The flat TPU handle is suitable for fit testing. Use a load-rated commercial webbing or rubber handle for frequent transport.

## Suggested Print Settings

PETG:

- 0.20 mm layers;
- 0.4 or 0.6 mm nozzle;
- at least 4 perimeters;
- 5 top/bottom layers;
- 25-35% gyroid infill for thick bosses and crossbars;
- 8-12 mm brim on `main_u_shell`;
- no PLA for the enclosure;
- inspect fan-guard bridges in the slicer and enable localized support only where required.

TPU 95A:

- 0.20 mm layers;
- 100% infill for the strap and pads;
- slow outer walls;
- print the strap flat and align continuous perimeters along its length.

## Hardware

- 1 x 140 x 140 x 25 mm 12 V four-pin PWM fan;
- 1 x 60 x 60 x 15 mm 12 V four-pin PWM fan;
- 2 x M4 heat-set inserts, nominal 5.6 mm pilot, for the handle crossbars;
- 2 x M4 handle bolts with broad washers or commercial handle end fittings;
- 2 or 4 fan screws per fan after the actual fan frame is verified;
- one display/controller assembly matching the final PCB dimensions;
- optional commercial load-rated strap in place of the printed TPU prototype.

The two M4 handle bolts also retain the top service assembly. The printed lid alone must never carry the enclosure weight.

## Assembly Order

1. Test both GB10 units and both fans with the gauges.
2. Install four TPU pads in the main shell recesses.
3. Install the selected display pod and the opposite blank plate.
4. Insert both GB10 units from the top with front grilles forward, rear connector columns outward, and rear vent columns inward.
5. Slide the rear 60 mm module onto the central rear tongues.
6. Insert the two handle crossbars above the devices.
7. Engage the front 140 mm module tongue.
8. Fit the top lid over the two crossbar bosses.
9. Install the handle strap and two M4 bolts into the crossbar inserts.
10. Install fans, controller wiring, guards, and external cables.

## Regeneration

From the project directory:

```bash
python3 cad/generate_a_plus.py
python3 -m unittest cad/test_generate_a_plus.py
```

Generated output is written to `output/cad-a-plus/`. `manifest.json` lists every file and dimension. `reports/validation.json` records B-Rep validity, STL closure, print envelopes, device collisions, and part-to-part collisions.
