#!/usr/bin/env python3

import ast
import tempfile
import unittest
from dataclasses import fields, replace
from pathlib import Path

from build123d import Axis, export_stl

from . import generate_r2 as cad


class R2CadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = cad.Params()
        cad.validate_params(cls.p)
        cls.cover = cad.build_u_cover(cls.p)
        cls.base = cad.build_sliding_base(cls.p)
        cls.front = cad.build_front_bezel(cls.p)
        cls.rear = cad.build_rear_frame(cls.p)
        cls.pod_left = cad.build_display_pod(cls.p, -1)
        cls.pod_right = cad.build_display_pod(cls.p, 1)
        cls.blank_left = cad.build_display_blank(cls.p, -1)
        cls.blank_right = cad.build_display_blank(cls.p, 1)

    def printed_parts(self):
        return {
            "u_cover": cad.oriented(self.cover, Axis.X, 180),
            "sliding_base": cad.oriented(self.base),
            "front_140_bezel": cad.oriented(self.front, Axis.X, 90),
            "rear_60_frame": cad.oriented(self.rear, Axis.X, -90),
            "display_pod_left": cad.oriented(self.pod_left, Axis.Y, -90),
            "display_pod_right": cad.oriented(self.pod_right, Axis.Y, 90),
            "display_blank_left": cad.oriented(self.blank_left, Axis.Y, -90),
            "display_blank_right": cad.oriented(self.blank_right, Axis.Y, 90),
        }

    def test_all_printed_parts_are_single_valid_solids(self):
        for shape in self.printed_parts().values():
            self.assertTrue(shape.is_valid())
            self.assertEqual(len(shape.solids()), 1)

    def test_all_print_orientations_fit_180mm_cube(self):
        for shape in self.printed_parts().values():
            size = shape.bounding_box().size
            self.assertLessEqual(max(size.X, size.Y, size.Z), self.p.print_limit + 0.01)

    def test_print_orientations_have_bed_contact_and_report_horizontal_bridges(self):
        with tempfile.TemporaryDirectory() as temporary:
            for name, shape in self.printed_parts().items():
                path = Path(temporary) / f"{name}.stl"
                export_stl(shape, path, tolerance=0.03, angular_tolerance=0.16)
                cad.clean_binary_stl(path)
                metrics = cad.stl_printability_record(path)
                self.assertGreaterEqual(metrics["bed_contact_area_mm2"], 100.0, name)
                self.assertGreaterEqual(metrics["unsupported_downward_horizontal_area_mm2"], 0.0, name)

    def test_approved_main_body_envelope(self):
        size = self.cover.bounding_box().size
        self.assertAlmostEqual(size.X, 152.0, places=3)
        self.assertAlmostEqual(size.Y, 158.0, places=3)
        self.assertAlmostEqual(size.Z, 166.0, places=3)

    def test_capture_rails_constrain_base_in_both_z_directions(self):
        self.assertEqual(len(self.p.rail_segment_starts), 3)
        self.assertGreaterEqual(self.p.rail_segment_length, 30.0)
        self.assertLessEqual(self.p.rail_segment_length, 35.0)
        self.assertAlmostEqual(self.p.nominal_rail_clearance, 0.40, places=2)
        self.assertLessEqual(cad.intersection_volume(self.cover, self.base), 0.01)
        travel = self.p.nominal_rail_clearance + 0.10
        self.assertGreater(cad.intersection_volume(self.cover, self.base.translate((0, 0, travel))), 0.05)
        self.assertGreater(cad.intersection_volume(self.cover, self.base.translate((0, 0, -travel))), 0.05)

    def test_rail_segments_and_base_tongue_have_real_y_lead_ins(self):
        segment = cad.tapered_rail_segment(
            cad.right_lower_rail_profile(self.p),
            1,
            self.p.rail_segment_starts[0],
            self.p.rail_segment_length,
            self.p.rail_lead_in,
            self.p.rail_top_z,
        )
        start = self.p.rail_segment_starts[0]
        thin = 0.10
        entry_slice = cad.box_at((20.0, thin, 20.0), (70.0, start + 0.15, 8.0))
        full_slice = cad.box_at((20.0, thin, 20.0), (70.0, start + self.p.rail_lead_in + 0.15, 8.0))
        self.assertGreater(cad.intersection_volume(segment, full_slice), cad.intersection_volume(segment, entry_slice) * 2)

        for outward in cad.linear_motion_samples(160.0, 0.0, self.p.rail_motion_step):
            self.assertLessEqual(
                cad.intersection_volume(self.cover, self.base.translate((0, -outward, 0))),
                0.01,
            )

    def test_guides_and_rear_stop_do_not_enter_latch_pockets(self):
        cutters = cad.build_latch_receiver_cutters(self.p)
        for feature in [*cad.build_base_guides(self.p), *cad.build_base_rear_stop(self.p)]:
            for cutter in cutters:
                self.assertLessEqual(cad.intersection_volume(feature, cutter), 0.01)

    def test_front_and_rear_lower_latches_lock_release_and_anti_relock(self):
        self.assertLessEqual(cad.intersection_volume(self.base, self.front), 0.01)
        self.assertLessEqual(cad.intersection_volume(self.base, self.rear), 0.01)
        self.assertGreater(cad.intersection_volume(self.base, self.front.translate((0, -0.5, 0))), 0.05)
        self.assertGreater(cad.intersection_volume(self.base, self.rear.translate((0, 0.5, 0))), 0.05)

        arm_bottom, _ = cad.latch_arm_bounds_z(self.p)
        self.assertGreaterEqual(arm_bottom - self.p.latch_throat_bottom_z, self.p.latch_release_deflection)
        self.assertGreaterEqual(self.p.base_thickness - self.p.latch_throat_top_z, 1.2)
        for front in (True, False):
            sign = -1 if front else 1
            root_y = cad.panel_latch_root_y(self.p, front)
            shoulder_y = cad.latch_shoulder_y(self.p, front)
            self.assertAlmostEqual(abs(shoulder_y - root_y), self.p.lower_latch_flex_length, places=3)
            locked_shapes = cad.build_lower_latch(self.p, self.p.panel_latch_x, root_y, front)
            released_shapes = cad.build_lower_latch(
                self.p,
                self.p.panel_latch_x,
                root_y,
                front,
                self.p.latch_release_deflection,
            )
            self.assertEqual(
                cad.bbox_record(locked_shapes[-1]),
                cad.bbox_record(released_shapes[-1]),
            )
            self.assertAlmostEqual(
                locked_shapes[1].bounding_box().max.Z - released_shapes[1].bounding_box().max.Z,
                self.p.latch_release_deflection,
                places=3,
            )
            locked = cad.union(locked_shapes).translate((0, sign * self.p.latch_anti_relock_travel, 0))
            released = cad.union(released_shapes).translate((0, sign * self.p.latch_anti_relock_travel, 0))
            self.assertGreater(cad.intersection_volume(self.base, locked), 0.05)
            self.assertLessEqual(cad.intersection_volume(self.base, released), 0.01)

            released_panel = (
                cad.build_front_bezel(self.p, self.p.latch_release_deflection)
                if front
                else cad.build_rear_frame(self.p, self.p.latch_release_deflection)
            )
            for travel in cad.linear_motion_samples(
                0.0,
                self.p.latch_anti_relock_travel,
                self.p.panel_motion_step,
            ):
                self.assertLessEqual(
                    cad.intersection_volume(
                        self.base,
                        released_panel.translate((0, sign * travel, 0)),
                    ),
                    0.01,
                )

    def test_display_complete_pod_path_and_release_latch(self):
        for side in (-1, 1):
            top_hooks = cad.union(cad.build_display_top_hooks(self.p, side))
            for travel in cad.linear_motion_samples(
                0.0,
                self.p.display_lock_travel,
                self.p.display_motion_step,
            ):
                self.assertLessEqual(
                    cad.intersection_volume(self.cover, top_hooks.translate((0, 0, travel))),
                    0.01,
                )

            # The T-head blocks outward removal in the locked position, then
            # clears the enlarged entry exactly one declared travel upward.
            self.assertGreater(
                cad.intersection_volume(self.cover, top_hooks.translate((side * 2.0, 0, 0))),
                1.0,
            )
            self.assertLessEqual(
                cad.intersection_volume(
                    self.cover,
                    top_hooks.translate((side * 2.0, 0, self.p.display_lock_travel)),
                ),
                    0.01,
                )

            locked_pod = cad.build_display_pod(self.p, side)
            released_pod = cad.build_display_pod(
                self.p,
                side,
                self.p.display_latch_release_deflection,
            )
            self.assertLessEqual(cad.intersection_volume(self.cover, locked_pod), 0.01)
            self.assertGreater(
                cad.intersection_volume(self.cover, locked_pod.translate((0, 0, 1.0))),
                0.05,
            )
            for travel in cad.linear_motion_samples(
                0.0,
                self.p.display_lock_travel,
                self.p.display_motion_step,
            ):
                self.assertLessEqual(
                    cad.intersection_volume(self.cover, released_pod.translate((0, 0, travel))),
                    0.01,
                )

            estimated_strain = (
                1.5
                * self.p.display_latch_thickness
                * self.p.display_latch_release_deflection
                / self.p.display_latch_flex_length**2
            )
            self.assertLessEqual(estimated_strain, 0.015)

    def test_device_references_clear_all_printed_structure(self):
        printed = [self.cover, self.base, self.front, self.rear, self.pod_left, self.blank_right]
        for device in cad.build_device_references(self.p):
            for part in printed:
                self.assertLessEqual(cad.intersection_volume(device, part), 0.01)

    def test_devices_have_bottom_support_and_front_retention(self):
        for device in cad.build_device_references(self.p):
            self.assertGreater(
                cad.intersection_volume(device.translate((0, 0, -0.10)), self.base),
                0.05,
            )
            front_overtravel = self.p.device_front_retainer_gap + 0.10
            self.assertGreater(
                cad.intersection_volume(device.translate((0, -front_overtravel, 0)), self.front),
                0.05,
            )

    def test_fan_references_clear_all_printed_structure(self):
        printed = [self.cover, self.base, self.front, self.rear, self.pod_left, self.blank_right]
        for fan in cad.build_fan_references(self.p):
            for part in printed:
                self.assertLessEqual(cad.intersection_volume(fan, part), 0.01)

    def test_assembled_printed_parts_do_not_overlap(self):
        parts = {
            "cover": self.cover,
            "base": self.base,
            "front": self.front,
            "rear": self.rear,
            "pod_left": self.pod_left,
            "blank_right": self.blank_right,
        }
        pairs = [
            ("cover", "base"),
            ("cover", "front"),
            ("base", "front"),
            ("cover", "rear"),
            ("base", "rear"),
            ("cover", "pod_left"),
            ("cover", "blank_right"),
        ]
        for first, second in pairs:
            self.assertLessEqual(cad.intersection_volume(parts[first], parts[second]), 0.01)

    def test_hard_guide_clearance_and_handle_load_path(self):
        bundle_outer = self.p.device_center_gap / 2 + self.p.device_thickness
        guide_inner_face = bundle_outer + self.p.device_side_clearance
        self.assertAlmostEqual(guide_inner_face - bundle_outer, 0.8, places=3)
        self.assertGreaterEqual(self.p.device_bottom_clearance, 0.6)
        self.assertLessEqual(self.p.device_bottom_clearance, 0.8)
        wall_inner = self.p.body_width / 2 - self.p.shell_wall
        rib_half_span = (self.p.body_width - 2 * self.p.shell_wall + 1.0) / 2
        self.assertGreater(rib_half_span, wall_inner)

    def test_base_has_sub_half_mm_axial_stops(self):
        self.assertGreater(cad.intersection_volume(self.front, self.base.translate((0, -0.5, 0))), 0.05)
        self.assertGreater(cad.intersection_volume(self.rear, self.base.translate((0, 0.5, 0))), 0.05)

    def test_front_grille_meets_open_area_requirement(self):
        projected_open = cad.front_grille_projected_open_fraction(self.p, self.front)
        self.assertGreaterEqual(projected_open, 0.80)
        self.assertLessEqual(self.p.front_grille_pitch - self.p.front_grille_bar, 12.0)
        self.assertLessEqual(self.p.rear_grille_pitch - self.p.rear_grille_bar, 10.0)

    def test_display_harness_port_and_protected_riser_exist(self):
        for side in (-1, 1):
            wall_center_x = side * (self.p.body_width - self.p.shell_wall) / 2
            port = cad.box_at(
                (
                    self.p.shell_wall + 2.0,
                    self.p.harness_port_width - 0.4,
                    self.p.harness_port_height - 0.4,
                ),
                (wall_center_x, self.p.harness_port_y, self.p.harness_port_z),
            )
            self.assertLessEqual(cad.intersection_volume(self.cover, port), 0.01)
        self.assertEqual(len(cad.build_harness_guides(self.p)), 4)

    def test_display_parts_are_true_mirrors(self):
        left_size = self.pod_left.bounding_box().size
        right_size = self.pod_right.bounding_box().size
        self.assertAlmostEqual(left_size.X, right_size.X, places=3)
        self.assertAlmostEqual(left_size.Y, right_size.Y, places=3)
        self.assertAlmostEqual(left_size.Z, right_size.Z, places=3)

    def test_fit_gauges_are_single_valid_solids(self):
        gauges = [
            cad.build_pair_fit_gauge(self.p),
            cad.build_fan_mount_gauge(self.p.front_fan_size, self.p.front_fan_hole_spacing, self.p.front_pin_hole_diameter),
            cad.build_fan_mount_gauge(self.p.rear_fan_size, self.p.rear_fan_hole_spacing, self.p.rear_pin_hole_diameter),
            cad.build_grille_coupon(self.p),
            cad.build_corner_coupon(self.p),
            cad.build_display_window_gauge(self.p),
            cad.build_rail_coupon_cover(self.p),
            cad.build_rail_coupon_slider(self.p),
            cad.build_latch_coupon_panel(self.p, True),
            cad.build_latch_coupon_receiver(self.p, True),
            cad.build_latch_coupon_panel(self.p, False),
            cad.build_latch_coupon_receiver(self.p, False),
            cad.build_display_coupon_cover(self.p),
            cad.build_display_coupon_pod(self.p),
            cad.build_rail_lead_coupon_cover(self.p),
            cad.build_rail_lead_coupon_slider(self.p),
        ]
        for shape in gauges:
            self.assertTrue(shape.is_valid())
            self.assertEqual(len(shape.solids()), 1)

    def test_rail_fit_gauge_halves_mate_and_capture(self):
        receiver = cad.build_rail_coupon_cover(self.p)
        slider = cad.build_rail_coupon_slider(self.p)
        self.assertLessEqual(cad.intersection_volume(receiver, slider), 0.01)
        self.assertGreater(cad.intersection_volume(receiver, slider.translate((0, 0, 0.6))), 0.05)
        self.assertGreater(cad.intersection_volume(receiver, slider.translate((0, 0, -0.6))), 0.05)

        lead_receiver = cad.build_rail_lead_coupon_cover(self.p)
        lead_slider = cad.build_rail_lead_coupon_slider(self.p)
        for outward in cad.linear_motion_samples(80.0, 0.0, self.p.rail_motion_step):
            self.assertLessEqual(
                cad.intersection_volume(lead_receiver, lead_slider.translate((0, -outward, 0))),
                0.01,
            )

    def test_release_uses_two_handle_bolts_and_color_c(self):
        self.assertEqual(self.p.default_color_scheme, "C")
        self.assertIn("C", cad.COLOR_SCHEMES)
        self.assertEqual(len((self.p.handle_anchor_front_y, self.p.handle_anchor_rear_y)), 2)

    def test_parameter_contract_rejects_unsafe_variants(self):
        unsafe_variants = [
            replace(self.p, lower_latch_flex_length=10.0),
            replace(self.p, display_latch_release_deflection=0.5),
            replace(self.p, front_grille_bar=4.0),
            replace(self.p, front_fan_size=152.0),
            replace(self.p, rail_motion_step=2.0),
        ]
        for params in unsafe_variants:
            with self.assertRaises(ValueError):
                cad.validate_params(params)

    def test_all_declared_parameters_are_consumed(self):
        tree = ast.parse(Path(cad.__file__).read_text(encoding="utf-8"))
        consumed = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
        }
        declared = {field.name for field in fields(cad.Params)}
        self.assertEqual(set(), declared - consumed)


if __name__ == "__main__":
    unittest.main()
