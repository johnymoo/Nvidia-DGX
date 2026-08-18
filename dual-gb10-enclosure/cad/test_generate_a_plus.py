#!/usr/bin/env python3

import unittest

from build123d import Axis, Compound

from . import generate_a_plus as cad


class APlusCadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = cad.Params()
        cls.main = cad.build_main_shell(cls.p)
        cls.front = cad.build_front_module(cls.p)
        cls.rear = cad.build_rear_module(cls.p)
        cls.lid = cad.build_top_lid(cls.p)
        cls.cross_front = cad.build_handle_crossbar(cls.p, cls.p.handle_anchor_front_y)
        cls.cross_rear = cad.build_handle_crossbar(cls.p, cls.p.handle_anchor_rear_y)
        cls.display_left = cad.build_display_pod(cls.p, -1)
        cls.blank_right = cad.build_display_blank(cls.p, 1)

    def test_print_parts_are_single_valid_solids(self):
        parts = [
            self.main,
            self.front,
            self.rear,
            self.lid,
            self.cross_front,
            cad.build_tpu_handle_strap(self.p),
            cad.build_tpu_pad(self.p),
            self.display_left,
            cad.build_display_pod(self.p, 1),
            cad.build_display_blank(self.p, -1),
            self.blank_right,
        ]
        for shape in parts:
            self.assertTrue(shape.is_valid())
            self.assertEqual(len(shape.solids()), 1)

    def test_all_print_orientations_fit_180mm_cube(self):
        print_shapes = [
            cad.oriented(self.main),
            cad.oriented(self.front, Axis.X, 90),
            cad.oriented(self.rear, Axis.X, 90),
            cad.oriented(self.lid, Axis.X, 180),
            cad.oriented(self.cross_front),
            cad.oriented(cad.build_tpu_handle_strap(self.p)),
            cad.oriented(self.display_left, Axis.Y, -90),
        ]
        for shape in print_shapes:
            size = shape.bounding_box().size
            self.assertLessEqual(max(size.X, size.Y, size.Z), 180.01)

    def test_approved_body_depth_is_218mm(self):
        assembly = Compound(children=[self.main, self.front, self.rear, self.lid])
        size = assembly.bounding_box().size
        self.assertAlmostEqual(size.Y, 218.0, places=3)
        self.assertAlmostEqual(size.Z, 166.0, places=3)

    def test_gb10_references_clear_printed_structure(self):
        printed = [self.main, self.front, self.rear, self.lid, self.cross_front, self.cross_rear]
        for device in cad.build_device_references(self.p):
            for part in printed:
                self.assertLessEqual(cad.intersection_volume(device, part), 0.01)

    def test_assembled_parts_do_not_overlap(self):
        parts = {
            "main": self.main,
            "front": self.front,
            "rear": self.rear,
            "lid": self.lid,
            "cross_front": self.cross_front,
            "cross_rear": self.cross_rear,
            "display_left": self.display_left,
            "blank_right": self.blank_right,
        }
        pairs = [
            ("main", "front"),
            ("main", "rear"),
            ("main", "lid"),
            ("main", "cross_front"),
            ("main", "cross_rear"),
            ("main", "display_left"),
            ("main", "blank_right"),
            ("lid", "cross_front"),
            ("lid", "cross_rear"),
            ("front", "lid"),
            ("rear", "lid"),
        ]
        for first, second in pairs:
            self.assertLessEqual(cad.intersection_volume(parts[first], parts[second]), 0.01)

    def test_fit_gauges_are_valid(self):
        gauges = [
            cad.build_pair_fit_gauge(self.p),
            cad.build_fan_mount_gauge(
                self.p.front_fan_size,
                self.p.front_fan_hole_spacing,
                self.p.front_fan_hole_diameter,
            ),
            cad.build_fan_mount_gauge(
                self.p.rear_fan_size,
                self.p.rear_fan_hole_spacing,
                self.p.rear_fan_hole_diameter,
            ),
        ]
        for shape in gauges:
            self.assertTrue(shape.is_valid())
            self.assertEqual(len(shape.solids()), 1)


if __name__ == "__main__":
    unittest.main()
