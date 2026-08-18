# Airflow Options V2

Status: A and A+ are under direct visual comparison; B and C remain fallback alternatives.

## Re-evaluation

- Two mirrored upright GB10 units expose a combined central rear vent region of approximately 51 x 150 mm, or 7,650 mm2 before grille blockage.
- A 140 mm fan has approximately 15,400 mm2 gross circular area, roughly twice the central rear throat. Using it on top adds bulk without proportionate airflow.
- A 92 mm fan has approximately 6,650 mm2 gross circular area and is a closer throat match.
- Two 60 mm fans have approximately 5,650 mm2 combined gross circular area but require higher speed and more wiring.
- The two full front grilles together occupy approximately 102 x 150 mm, or 15,300 mm2. This is a good match for one front 140 mm fan.

## Shared geometry

- Two 51 x 150 x 150 mm GB10 units stand on opposite short edges.
- Both front grilles face the front 140 mm fan.
- At the rear, connector columns are on the outer left and right; exhaust columns meet in the center.
- Rear connectors remain flush and exposed. Cable bends occur outside the enclosure.
- No foam seal. Small non-contact printed lips may guide flow.
- Target four captive external M3 screws, with only two used for routine top access.

## A - Open rear

- External fans: one front 140 mm PWM fan.
- Exhaust: both GB10 internal fan systems discharge directly through the open central rear vents.
- Envelope: approximately 152 W x 193 D x 166 H mm, excluding the side display treatment.
- Benefits: shortest, quietest, least restrictive, easiest cable access, fewest failure modes.
- Risk: hot-air recirculation if the rear is placed too close to a wall.
- Current recommendation for the base enclosure.

## A+ - Semi-open rear 60 mm assist

- External fans: one front 140 mm PWM fan plus one rear 60 x 60 x 15 mm PWM fan.
- Exhaust: the 60 mm fan sits on a removable central bridge approximately 8-10 mm behind the base rear frame and exhausts straight backward.
- Passive fallback: openings above and below the fan preserve native GB10 exhaust if the assist fan is stopped or removed.
- Connector access: the left and right connector planes remain flush at the original A depth; only the central fan bridge projects rearward.
- Handling: a fold-down commercial soft handle mounts along the top centerline using two load-bearing fasteners shared with the removable top service panel; the load transfers into fixed upper crossmembers rather than the printed lid alone.
- Display: the side display pod uses a mirrored slide-on mount and may be installed on the left or right; the unused side receives a flush blanking plate.
- Envelope: approximately 152 W x 218 D x 166 H mm, excluding the side display treatment.
- Benefits: lower rear pressure and less hot-air recirculation while preserving a straight-through path.
- Costs: approximately 25 mm more maximum depth, a higher-speed fan, and one additional PWM/tach channel.
- Current recommendation for direct thermal comparison against A; not yet selected as the final base enclosure.

## B - 92 mm top assist

- External fans: front 140 mm plus one horizontal top 92 mm PWM fan.
- Exhaust: a narrow central collector turns rear exhaust upward.
- Envelope: approximately 152 W x 205 D x 190 H mm.
- Benefits: controlled extraction when rear clearance is poor or ambient temperature is high.
- Costs: taller shell, extra pressure loss, more noise and components.
- Recommended as an optional add-on module only if thermal tests justify it.

## C - Dual 60 mm top exhaust

- External fans: front 140 mm plus two horizontal 60 mm fans.
- Exhaust: split collectors serve each GB10 rear vent region.
- Envelope: approximately 152 W x 198 D x 181 H mm.
- Benefits: shorter and lower than the 92 mm assist option.
- Costs: more fan noise, more wiring, more tach/PWM channels, and two additional failure points.
- Not recommended unless a measured hot spot requires independently controlled exhaust branches.

## Visual review

- Inline Three.js source: `/Users/chris/.codex/visualizations/2026/08/17/01a01056-29c3-70f1-8526-2019d3c10bfa/dual-gb10-airflow-options.html`
- Views per option: assembled, transparent airflow, rear connector access, and exploded.
- The browser QA covered 1,024 x 800 and 360 x 800 viewports, all variant/view controls, canvas rendering, and console errors.
