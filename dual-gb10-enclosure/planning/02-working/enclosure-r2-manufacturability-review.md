# Enclosure R2 Manufacturability Review

Status: R2 structural direction approved by user on 2026-08-18; Three.js visual review implemented, production CAD changes pending visual acceptance.

Reviewed: 2026-08-18

Visual reviews: `site/r2.html` for exterior proportions and `site/r2-assembly.html` for the current authoritative assembly interfaces.

## Reference-image takeaways

Adopt:

- A continuous white outer shell with visibly rounded top/side transitions.
- A separate colored front fan bezel that hides the shell joint and can be removed without opening the whole enclosure.
- A clean perimeter reveal instead of exposed rows of screws.
- A side display treatment that is visually integrated into the shell.

Do not copy directly:

- The reference grille is too dense for this enclosure. The 140 mm intake needs at least 75% free area through the printed guard.
- The reference does not prove its hidden joints can carry approximately 3 kg. The GB10 enclosure needs an explicit handle-to-base load path.
- A cosmetic snap is not sufficient for a frequently removed, load-bearing PETG joint.

## R1 findings

The current `main_u_shell` is not a U-shaped cover. It combines the bottom plate and both side walls, then closes the top with a separate lid. Most outer edges are unions of boxes with no production fillets. The front module has an alignment tongue but no positive, user-releasable snap latch.

R1 does already prove useful constraints:

- The 152 x 158 x 166 mm body envelope fits a 180 x 180 x 180 mm printer.
- Current generated B-Reps and STL meshes are valid and closed.
- Device and printed-part collision checks pass for the provisional dimensions.
- Front and rear fan fit gauges already exist.

## Recommended R2 structure

### 1. One-piece U cover

- Combine the top and both side walls into one PETG part; leave front, rear, and bottom open.
- Target 3.2-3.6 mm nominal walls with local ribs instead of the current uniform 5 mm walls.
- Use an outer top-to-side radius of 10-12 mm and a concentric inner radius of 6.5-8.5 mm.
- Use 3-5 mm radii on exposed longitudinal and bezel edges; no knife edges.
- Print with the exterior top face on the build plate. The side walls and integrated handle ribs then grow vertically without global support.
- Keep the oriented bounding box within approximately 152 x 158 x 166 mm.

### 2. Front-loading sliding base

- Make the bottom plate a separate ribbed part with continuous chamfered side tongues that slide from the front into three interrupted capture-rail segments on each lower edge of the U cover.
- Use self-supporting 45-degree trapezoidal capture geometry, not a horizontal T-slot that requires support. Target three 30-35 mm rail segments per side, each with a lead-in chamfer and debris-relief gap.
- Add a hard rear stop. The removable front bezel blocks forward movement after assembly.
- Put rounded PETG GB10 guide ribs and cable/sensor channels on the base. Use 0.6-0.8 mm side clearance; do not require foam or separate TPU parts. Reserve only shallow, non-vent-edge seats for optional silicone dots if physical testing reveals rattle.
- Assemble the empty cover and base first, then slide both GB10 units in from the front. This avoids flexing a large cover over installed hardware.

The six capture-rail segments carry vertical load when the enclosure is lifted. The hard rear stop sets insertion depth; the front latches only resist axial movement and do not carry the device weight.

### 3. Snap-on front fan bezel

- Use two rigid integral upper hooks and two integral lower PETG cantilever latches with visible finger-release windows. Target 18-22 mm flex length, 1.4-1.6 mm flexure thickness, and a root radius of at least 1.5 mm.
- Make the lower latches sequentially releasable: pressing either latch and pulling its corner out 3-4 mm engages a temporary anti-relock step, so the user never has to hold both latches simultaneously.
- Add a 4-5 mm labyrinth/alignment lip around the perimeter with 0.35-0.45 mm clearance per side after coupon calibration.
- Integrate the 140 mm fan guard into the bezel and print the exterior face down.
- Target a 14-16 mm grille pitch with approximately 2.0 mm rounded bars, yielding at least 75% open area.
- Mount the 140 mm fan directly to the inner face of the bezel with four silicone pull-through pins so the bezel and fan remove as one module. Keep standard fan-screw holes only as a hardware-failure fallback.
- Add 30-40 mm of panel opening travel, a short fan-cable service loop, and one keyed quick connector before the harness enters the fixed body.
- The lower latches and inner bezel stop also lock the sliding base against forward movement.

### 4. Rear frame and display pod

- Use one mostly open, full-perimeter rear frame that registers the four rear edges of the assembled U-cover-and-base body.
- Mount the central 60 mm fan directly to this frame with four silicone pull-through pins; do not add a second sliding fan cassette.
- Retain passive upper/lower bypass and two large, unobstructed rear connector/cable windows.
- Attach the rear frame with the same two integral rigid upper hooks and two integral sequential-release lower latches used by the front interface. No rear body-panel screws and no simultaneous two-latch pinch.
- Give the rear fan cable a short service loop and keyed quick connector so the released frame can open 30-40 mm before disconnection.
- Rear-fan service may require disconnecting the GB10 rear cables and removing the complete rear frame. The user accepted this trade-off on 2026-08-18 in favor of fewer printed parts and tolerance interfaces.
- Reject the independently sliding fan-cassette concept: it adds a second rail fit, a small latch, vibration-clearance risk, and another printed part without sufficient service benefit.
- Make the touch display pod a separate reversible cartridge with two short hooks, 6-8 mm of downward locking travel, and one bottom release latch. Do not use a long side rail; cover the unused mirrored interface with a thin snap-on blank.
- Route the display harness through a protected base channel and into the bottom of the selected pod, avoiding duplicate large side-wall cable openings.
- Remove the rotary-encoder hole.
- Do not freeze the display opening or pod thickness until the selected PCB is measured.

### 5. Handle and screw count

Recommended carrying version:

- Integrate two wide internal cross-ribs and insert bosses into the U cover.
- Retain exactly two M4 bolts for a commercial strap handle. These are the only structural enclosure screws.
- Spread each boss into both the top skin and side walls; use heat-set inserts and broad washers.
- The U cover transfers handle load through the six segmented capture rails into the continuous base tongues. The snap latches are not in the vertical load path.

True screwless alternative:

- Omit the top handle and its inserts.
- Add shaped two-hand grip recesses at the lower sides so the user supports the base directly.
- This is simpler and safer than asking PETG snap tabs alone to support the carried enclosure, but it loses one-hand carrying.

## Color and filament schedule

Scheme C is the selected default for release renders and manufacturing. Schemes A and B remain approved color-only alternatives. All three use the same CAD, STL files, print orientations, tolerances, and assembly BOM; no multi-color toolhead, paint, or additional printed part is required.

| Scheme | Status | U cover and unused-side blank | Front bezel, base, and rear frame | Display pod |
| --- | --- | --- | --- | --- |
| A - Dark-copper industrial | Approved alternative | Mist gray, `#D9DDDA` | Graphite, `#292F31` | Dark copper-orange, `#A94D2D` |
| B - NVIDIA technical | Approved alternative | Cool white, `#ECEFED` | Charcoal, `#1D2224` | NVIDIA green reference, `#76B900` |
| C - Graphite workstation | **Default** | Deep graphite, `#343A3C` | Matte black, `#171B1D` | Titanium gray, `#8B9698` |

Processing requirements:

- Treat the hex values as digital appearance references. Approve the physical filament against a printed sample; supplier color names and monitor rendering are not acceptance evidence.
- Use opaque standard PETG or a mechanically qualified tough PETG. Prefer one manufacturer and product family for the U cover, base, front bezel, and rear frame so mating parts have comparable shrinkage and stiffness.
- Do not use silk, carbon-fiber-filled, glow, wood-filled, or transparent PETG for the U-cover capture rails, base tongues, front bezel, rear frame, hooks, or cantilever latches. A cosmetic filament is acceptable only for the non-load-bearing display pod after a fit coupon passes.
- Calibrate flow, extrusion temperature, shrinkage, and rail/latch clearance for every production spool color. Color changes do not authorize slicer scaling of the released STL.
- The black commercial handle, black purchased fans, natural-metal fasteners, and silicone fan pins retain their supplied finishes in every scheme.
- Gold capture rails and orange pins shown in the Three.js assembly view are functional visualization colors, not extra printable color zones. The integral rails print in the color of their parent U-cover or base part.
- Record the selected scheme letter and actual filament manufacturer, product, color name, material batch, and slicer profile in the release manifest.

## 3D-print manufacturability checklist

Legend: PASS is demonstrated in R1 output; PARTIAL needs redesign or a coupon; MISSING has no current evidence.

| Check | R1 | R2 acceptance gate |
| --- | --- | --- |
| Every oriented part fits 180 x 180 x 180 mm | PASS | Maximum dimension <= 175 mm, with the proposed print orientation recorded in the manifest. |
| Valid solid and closed STL | PASS | One valid solid per printable part, zero non-manifold edges. |
| Device and part collision checks | PASS | Repeat with rounded geometry, rail interfaces, latches, real fan dimensions, and measured display PCB. |
| Rounded exposed edges | MISSING | Outer U radius 10-12 mm; exposed edges radius 3-5 mm; latch roots radius >= 1.2 mm. |
| Support-free main parts | PARTIAL | U cover top-face-down, base flat, front bezel face-down; no global supports. |
| Overhang control | PARTIAL | Structural overhangs <= 45 degrees from vertical; use chamfers/teardrops for rail undersides and cable holes. |
| Bridge control | PARTIAL | No structural bridge longer than 12 mm; longer cosmetic bridges must pass a PETG coupon. |
| Wall and rib thickness | PASS but heavy | 3.2-3.6 mm shell, >= 2.0 mm ribs, >= 1.2 mm latch flexure, and >= 3.0 mm around inserts. |
| Sliding-joint tolerance | MISSING | Test 0.30, 0.40, and 0.50 mm clearance-per-side segmented-rail coupons, including a second-segment lead-in; select the loosest fit without rattle or binding. |
| Snap-latch strain and service life | MISSING | Integral PETG latch, 18-22 mm flex length, 1.4-1.6 mm flexure, root radius >= 1.5 mm, sequential anti-relock action, and 50 assembly cycles without whitening/cracks. |
| Front grille airflow | PARTIAL | Measured projected open area >= 75%; no bar closer than 6 mm to the fan blade plane. |
| Base flatness and warping | PARTIAL | Ribbed base prints flat with <= 0.8 mm corner lift after cooling; brim allowed but no raft. |
| Fan vibration isolation | MISSING | Silicone fan pins or isolators; no fan-frame contact with a loose bezel surface. |
| Thermal material suitability | PASS at material level | PETG only for the enclosure; run a sustained-load soak and confirm no local printed part exceeds its validated service temperature. |
| Color and filament release | MISSING | Release manifest identifies scheme A, B, or C (C default), records every filament spool/batch, and includes an approved physical color/surface coupon. |
| GB10 fit without foam | PARTIAL | Rounded hard-guide pair gauge passes with 0.6-0.8 mm side clearance, no forced insertion, and no objectionable impact during a carry/tilt test. Optional silicone dots are a post-test remedy, not a default BOM item. |
| Fan and display fit | MISSING | Physical 140 mm, 60 mm, and display PCB gauges pass before full print. |
| Rear connector and bend clearance | PARTIAL | All planned USB-C, HDMI, Ethernet, and QSFP cables install with the rear fan module fitted. |
| Tool-less service path | MISSING | Each lower latch releases separately and remains 3-4 mm open; the panel opens 30-40 mm for fan quick-connector access; both GB10 units slide out after rear cables are disconnected; no hidden screw. |
| Carry-load path | PARTIAL | 2x M4 handle version survives a static 12 kg proof load for 60 seconds with no cracking, insert pull-out, or rail movement. |
| Enclosure screw count | PARTIAL | Two M4 handle bolts total; no body-panel or normal fan-mount screws. Both fans use four silicone pins; fan screw holes are fallback-only. |
| Slicer review | MISSING | Inspect first-layer contact, walls, seams, bridges, travel, support, estimated material, and print time for every release STL. |

## Mandatory test pieces before the full R2 print

1. Three-clearance 60 mm-long segmented-rail coupon with two successive capture sections and representative debris-relief gap.
2. Shared front/rear hook, integral latch, release-window, and sequential anti-relock coupon, printed in final orientation.
3. Rounded U-corner section to verify surface quality and actual wall thickness.
4. 60 x 60 mm grille coupon to measure stiffness and open area.
5. Existing GB10-pair and both fan-mount gauges, updated with measured dimensions.
6. Display bezel and side-rail gauge after the PCB arrives.

## Proposed assembly order

1. Fit the 140 mm fan to the front bezel and the 60 mm fan to the one-piece rear frame, using four silicone pins for each fan.
2. Slide the ribbed base into the U cover until it reaches the rear stop.
3. Hook and latch the rear frame onto the main body; install the controller harness and side display cartridge.
4. Slide the two GB10 units in from the open front along the base guides.
5. Connect and verify fan, sensor, and display wiring.
6. Hook the complete front-bezel-and-fan module at the top and press the two lower latches home; this also locks the base.
7. Install the commercial top strap with the two M4 bolts, or omit this step on the screwless two-hand-grip version.
