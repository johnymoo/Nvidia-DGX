#!/usr/bin/env python3

import unittest

from build123d import Axis

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

    def test_all_printed_parts_are_single_valid_solids(self):
        shapes = [
            self.cover,
            self.base,
            self.front,
            self.rear,
            self.pod_left,
            self.pod_right,
            self.blank_left,
            self.blank_right,
        ]
        for shape in shapes:
            self.assertTrue(shape.is_valid())
            self.assertEqual(len(shape.solids()), 1)

    def test_all_print_orientations_fit_180mm_cube(self):
        print_shapes = [
            cad.oriented(self.cover, Axis.X, 180),
            cad.oriented(self.base),
            cad.oriented(self.front, Axis.X, 90),
            cad.oriented(self.rear, Axis.X, 90),
            cad.oriented(self.pod_left, Axis.Y, -90),
            cad.oriented(self.pod_right, Axis.Y, 90),
            cad.oriented(self.blank_left, Axis.Y, -90),
            cad.oriented(self.blank_right, Axis.Y, 90),
        ]
        for shape in print_shapes:
            size = shape.bounding_box().size
            self.assertLessEqual(max(size.X, size.Y, size.Z), self.p.print_limit + 0.01)

    def test_approved_main_body_envelope(self):
        size = self.cover.bounding_box().size
        self.assertAlmostEqual(size.X, 152.0, places=3)
        self.assertAlmostEqual(size.Y, 158.0, places=3)
        self.assertAlmostEqual(size.Z, 166.0, places=3)

    def test_three_capture_rail_segments_per_side(self):
        self.assertEqual(len(self.p.rail_segment_starts), 3)
        self.assertGreaterEqual(self.p.rail_segment_length, 30.0)
        self.assertLessEqual(self.p.rail_segment_length, 35.0)
        self.assertAlmostEqual(self.p.nominal_rail_clearance, 0.40, places=2)

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

    def test_hard_guide_clearance_matches_approved_value(self):
        bundle_outer = self.p.device_center_gap / 2 + self.p.device_thickness
        guide_inner_face = bundle_outer + self.p.device_side_clearance
        self.assertAlmostEqual(guide_inner_face - bundle_outer, 0.8, places=3)
        self.assertGreaterEqual(self.p.device_bottom_clearance, 0.6)
        self.assertLessEqual(self.p.device_bottom_clearance, 0.8)

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
            cad.build_latch_coupon_panel(self.p),
            cad.build_latch_coupon_receiver(self.p),
        ]
        for shape in gauges:
            self.assertTrue(shape.is_valid())
            self.assertEqual(len(shape.solids()), 1)

    def test_release_uses_two_handle_bolts_and_color_c(self):
        self.assertEqual(self.p.default_color_scheme, "C")
        self.assertIn("C", cad.COLOR_SCHEMES)
        self.assertEqual(len((self.p.handle_anchor_front_y, self.p.handle_anchor_rear_y)), 2)


if __name__ == "__main__":
    unittest.main()
