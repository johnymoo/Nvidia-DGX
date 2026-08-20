#!/usr/bin/env python3

import tempfile
import unittest
from pathlib import Path

from build123d import Axis, export_stl

from . import generate_r2 as cad


class R2CadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = cad.Params()
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

    def test_print_orientations_have_bed_contact_and_no_horizontal_support(self):
        with tempfile.TemporaryDirectory() as temporary:
            for name, shape in self.printed_parts().items():
                path = Path(temporary) / f"{name}.stl"
                export_stl(shape, path, tolerance=0.03, angular_tolerance=0.16)
                cad.clean_binary_stl(path)
                metrics = cad.stl_printability_record(path)
                self.assertGreaterEqual(metrics["bed_contact_area_mm2"], 100.0, name)
                self.assertLessEqual(metrics["unsupported_downward_horizontal_area_mm2"], 25.0, name)

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

    def test_guides_and_rear_stop_do_not_enter_latch_pockets(self):
        cutters = cad.build_latch_receiver_cutters(self.p)
        for feature in [*cad.build_base_guides(self.p), *cad.build_base_rear_stop(self.p)]:
            for cutter in cutters:
                self.assertLessEqual(cad.intersection_volume(feature, cutter), 0.01)

    def test_front_and_rear_lower_latches_resist_outward_motion(self):
        self.assertLessEqual(cad.intersection_volume(self.base, self.front), 0.01)
        self.assertLessEqual(cad.intersection_volume(self.base, self.rear), 0.01)
        self.assertGreater(cad.intersection_volume(self.base, self.front.translate((0, -1.5, 0))), 0.05)
        self.assertGreater(cad.intersection_volume(self.base, self.rear.translate((0, 1.5, 0))), 0.05)

    def test_display_key_path_and_release_latch(self):
        for side in (-1, 1):
            top_hooks = cad.union(cad.build_display_top_hooks(self.p, side))
            latch = cad.union(cad.build_display_latch(self.p, side))
            for travel in (0.0, 1.0, 3.5, 6.9, self.p.display_lock_travel):
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

            # Upward motion is blocked by the lower latch until its head is
            # pressed 4.5 mm inward through the service opening.
            test_travel = self.p.display_lock_travel / 2
            self.assertGreater(
                cad.intersection_volume(self.cover, latch.translate((0, 0, test_travel))),
                0.05,
            )
            self.assertLessEqual(
                cad.intersection_volume(
                    self.cover,
                    latch.translate((-side * 4.5, 0, test_travel)),
                ),
                0.01,
            )

    def test_device_references_clear_all_printed_structure(self):
        printed = [self.cover, self.base, self.front, self.rear, self.pod_left, self.blank_right]
        for device in cad.build_device_references(self.p):
            for part in printed:
                self.assertLessEqual(cad.intersection_volume(device, part), 0.01)

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

    def test_front_grille_meets_open_area_requirement(self):
        projected_open = (1 - self.p.front_grille_bar / self.p.front_grille_pitch) ** 2
        self.assertGreaterEqual(projected_open, 0.75)

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

    def test_release_uses_two_handle_bolts_and_color_c(self):
        self.assertEqual(self.p.default_color_scheme, "C")
        self.assertIn("C", cad.COLOR_SCHEMES)
        self.assertEqual(len((self.p.handle_anchor_front_y, self.p.handle_anchor_rear_y)), 2)


if __name__ == "__main__":
    unittest.main()
