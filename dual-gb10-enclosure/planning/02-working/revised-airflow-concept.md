# Revised Airflow Concept

Status: superseded by `airflow-options-v2.md`; retained as the history of the rejected 140 mm top-exhaust concept.

## Problem with direct rear fan

A 140 mm fan mounted directly behind the two upright GB10 rear panels overlaps the USB-C power, USB-C/DisplayPort, HDMI, Ethernet, and QSFP connectors. The fan frame also consumes the cable bend volume. The previous direct front-to-rear external fan arrangement is therefore not mechanically viable.

## Proposed airflow

1. Keep one 140 mm front intake fan and a sealed front distribution plenum.
2. Rotate the two GB10 units in opposite directions around the front-to-rear axis while keeping both front grilles facing forward.
3. At the rear, arrange the two devices so their connector regions face the outer left and right cable bays while their exhaust-grille regions face inward toward the center.
4. Seal a narrow central rear collector around the two inward-facing exhaust regions.
5. Turn the collected hot air upward through a rear chimney.
6. Use the second 140 mm fan horizontally in a rear top cap, exhausting upward through a flush protective grille.
7. Terminate the outer rear connector bays flush with the enclosure edge so connectors are directly accessible.
8. Route cable bends outside the enclosure and provide a removable open cable-management bridge instead of a closed rear cover.

## Benefits

- Preserves the GB10 native front-to-rear internal airflow.
- Keeps all rear ports physically accessible.
- Prevents the external exhaust fan from recirculating cable-bay air.
- Allows the rear cover, top exhaust module, and cable guides to be printed separately under the 180 mm part-size limit.

## Approved mechanical constraints

- No foam or adhesive gasket around the GB10 exhaust regions.
- Use a non-contact printed labyrinth lip around the central exhaust collector, with approximately 1 mm clearance from each GB10.
- Permit minor leakage; the top exhaust fan maintains negative pressure in the collector.
- Use only small replaceable TPU support points at the lower cradle for scratch and vibration protection.
- Minimize fasteners and avoid perimeter rows of panel screws.
- Prefer sliding dovetails, tongue-and-groove alignment, hooked tabs, and replaceable latches.
- Do not rely on PETG snap fits alone for the 2.4 kg device load or the removable top service module.

## Risks to verify

- Exact vent/port boundary dimensions on the physical devices.
- Pressure drop through the 90-degree collector and top cap.
- Clearance above the devices for the top duct and 25 mm fan.
- Whether QSFP cables require a larger rear bend envelope than ordinary USB-C and Ethernet cables.

## Visual prototype

- Geometry source: `visuals/scene.js`
- Interactive views:
  - `index.html?view=finished`
  - `index.html?view=cutaway`
  - `index.html?view=exploded`
- Geometry-anchored renders:
  - `output/imagegen/gb10-airflow-finished.png`
  - `output/imagegen/gb10-airflow-cutaway.png`
  - `output/imagegen/gb10-airflow-exploded.png`
- Surface-refined beauty render:
  - `output/imagegen/gb10-airflow-beauty.png`
- Revised approximate concept envelope, before physical measurement refinement:
  - Main shell width: 152 mm plus the left display treatment.
  - Main shell height: approximately 195 mm including the concealed top fan layer.
  - Shell depth target: 205-215 mm including the front fan/plenum and central rear collector.
  - Rear connector planes remain flush and exposed; an optional cable bridge does not extend the base shell.
- Status: airflow architecture and exterior direction require user approval before printable CAD begins.
