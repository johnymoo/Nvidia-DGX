#!/usr/bin/env python3
"""Generate the Dual GB10 R2.1 enclosure release-candidate delivery package.

Coordinate system:
  X: left/right
  Y: front/rear
  Z: bottom/top

The R2 geometry follows the approved one-piece U-cover, sliding base,
snap-on fan panels, reversible display pod, and two-bolt commercial handle
architecture. Hardware dimensions that still need physical measurement remain
centralized in Params and are called out in every generated release document.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import struct
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from build123d import (
    Axis,
    Box,
    BuildSketch,
    Circle,
    Compound,
    Cylinder,
    ExportDXF,
    ExportSVG,
    Locations,
    Mode,
    Plane,
    Polygon,
    Pos,
    RectangleRounded,
    Shape,
    export_step,
    export_stl,
    extrude,
    fillet,
)
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Circle as PlotCircle
from matplotlib.patches import FancyBboxPatch, Rectangle


ROOT = Path(__file__).resolve().parents[1]
RELEASE_ID = "dual-gb10-r2-1-rc2"
DEFAULT_OUTPUT = ROOT / "output" / RELEASE_ID
DEFAULT_PDF = ROOT / "output" / "pdf" / f"{RELEASE_ID}-engineering-drawings.pdf"


@dataclass(frozen=True)
class Params:
    revision: str = "R2.1-RC2"
    units: str = "mm"
    print_limit: float = 180.0
    u_cover_brim: float = 10.0

    # Main body envelope.
    body_width: float = 152.0
    body_depth: float = 158.0
    body_height: float = 166.0
    shell_wall: float = 3.6
    outer_top_radius: float = 12.0
    inner_top_radius: float = 8.4
    exposed_edge_radius: float = 3.0

    # Sliding base and segmented capture rails.
    base_plate_width: float = 136.0
    base_depth: float = 154.0
    base_front_y: float = 2.0
    base_thickness: float = 7.0
    tongue_outer_x: float = 71.0
    tongue_inner_x: float = 67.5
    tongue_lower_inner_x: float = 68.4
    tongue_lower_inner_z: float = 2.9
    tongue_outer_bottom_z: float = 5.5
    tongue_outer_top_z: float = 10.8
    rail_inner_x: float = 67.2
    rail_lower_floor_z: float = 1.0
    rail_lower_inner_z: float = 2.5
    rail_upper_inner_bottom_z: float = 7.4
    rail_upper_inner_top_z: float = 9.8
    rail_top_z: float = 15.0
    rail_segment_length: float = 34.0
    rail_segment_starts: tuple[float, float, float] = (8.0, 62.0, 116.0)
    rail_lead_in: float = 2.0
    nominal_rail_clearance: float = 0.40

    # Two GB10 devices.
    device_thickness: float = 50.5
    device_depth: float = 150.0
    device_height: float = 150.0
    device_center_gap: float = 4.0
    device_side_clearance: float = 0.8
    device_front_clearance: float = 4.0
    device_bottom_clearance: float = 0.8
    guide_width: float = 2.4
    guide_height: float = 6.0
    guide_end_relief: float = 2.5
    rear_stop_width: float = 70.0

    # Front intake assembly. The fan occupies Y=-25..0 and does not lengthen
    # the 158 mm device cavity.
    front_bezel_offset: float = 32.0
    front_bezel_thickness: float = 7.0
    front_opening_radius: float = 68.5
    front_grille_pitch: float = 15.0
    front_grille_bar: float = 2.0
    front_fan_size: float = 140.0
    front_fan_thickness: float = 25.0
    front_fan_hole_spacing: float = 124.5
    front_pin_hole_diameter: float = 4.8

    # Rear exhaust-assist assembly.
    rear_frame_thickness: float = 7.0
    rear_fan_size: float = 60.0
    rear_fan_thickness: float = 15.0
    rear_fan_hole_spacing: float = 50.0
    rear_pin_hole_diameter: float = 4.6
    rear_fan_opening_radius: float = 27.5

    # Shared front/rear panel interfaces.
    panel_latch_x: float = 48.0
    upper_hook_width: float = 18.0
    upper_hook_thickness: float = 3.0
    upper_hook_z: float = 160.0
    upper_hook_reach: float = 7.0
    upper_hook_tooth_height: float = 2.8
    lower_latch_width: float = 16.0
    lower_latch_thickness: float = 1.5
    lower_latch_z: float = 5.55
    lower_latch_flex_length: float = 22.0
    latch_root_radius: float = 1.5
    panel_fit_clearance: float = 0.40
    panel_arm_root_overlap: float = 2.0
    latch_release_window_width: float = 8.0
    latch_throat_height: float = 2.2
    latch_pocket_height: float = 4.2
    latch_catch_height: float = 1.3
    latch_capture: float = 0.40
    front_latch_pocket_front_y: float = 5.0
    front_latch_pocket_rear_y: float = 9.5
    rear_latch_pocket_front_y: float = 144.5
    rear_latch_pocket_rear_y: float = 149.0
    service_opening_travel: float = 35.0

    # Reversible display pod. PCB dimensions remain provisional.
    display_projection: float = 18.0
    display_depth: float = 80.0
    display_height: float = 70.0
    display_center_y: float = 70.0
    display_center_z: float = 112.0
    display_gap: float = 0.5
    display_screen_width: float = 58.0
    display_screen_height: float = 42.0
    display_wall: float = 3.0
    display_lock_travel: float = 7.0
    display_fit_clearance: float = 0.60
    display_hook_stem_y: float = 4.4
    display_hook_head_y: float = 7.2
    display_hook_head_z: float = 7.2
    display_hook_y: tuple[float, float] = (36.0, 104.0)
    display_hook_z: float = 126.0
    display_latch_z: float = 82.0

    # Commercial handle load path.
    handle_anchor_front_y: float = 32.0
    handle_anchor_rear_y: float = 126.0
    handle_bolt_clearance: float = 4.5
    handle_insert_pilot: float = 5.6
    handle_boss_diameter: float = 18.0
    handle_rib_width: float = 12.0
    handle_rib_thickness: float = 4.8
    handle_reference_height: float = 34.0

    # Color schedule. Hex values are appearance references, not metrology.
    default_color_scheme: str = "C"


@dataclass(frozen=True)
class PartSpec:
    part_number: str
    name: str
    assembly_shape: Shape
    print_shape: Shape
    quantity: int
    material: str
    color_role: str
    print_orientation: str
    notes: str


@dataclass(frozen=True)
class GaugeSpec:
    name: str
    shape: Shape
    notes: str


def box_at(size: tuple[float, float, float], center: tuple[float, float, float]) -> Shape:
    return Pos(*center) * Box(*size)


def rounded_box_at(
    size: tuple[float, float, float],
    center: tuple[float, float, float],
    radius: float,
) -> Shape:
    raw = box_at(size, center)
    return fillet(raw.edges(), min(radius, min(size) / 2 - 0.01))


def cyl_z(radius: float, height: float, center: tuple[float, float, float]) -> Shape:
    return Pos(*center) * Cylinder(radius, height)


def cyl_y(radius: float, height: float, center: tuple[float, float, float]) -> Shape:
    return Pos(*center) * Cylinder(radius, height, rotation=(90, 0, 0))


def cyl_x(radius: float, height: float, center: tuple[float, float, float]) -> Shape:
    return Pos(*center) * Cylinder(radius, height, rotation=(0, 90, 0))


def union(shapes: Iterable[Shape]) -> Shape:
    items = list(shapes)
    if not items:
        raise ValueError("union() needs at least one shape")
    result = items[0]
    for item in items[1:]:
        result = result + item
    return result.clean()


def cut(shape: Shape, cutters: Iterable[Shape]) -> Shape:
    result = shape
    for cutter in cutters:
        result = result - cutter
    return result.clean()


def normalize(shape: Shape) -> Shape:
    bbox = shape.bounding_box()
    return shape.translate((-bbox.min.X, -bbox.min.Y, -bbox.min.Z))


def oriented(shape: Shape, axis: Axis | None = None, angle: float = 0.0) -> Shape:
    result = shape.rotate(axis, angle) if axis is not None and angle else shape
    return normalize(result)


def prism_xz(points: list[tuple[float, float]], y_start: float, length: float) -> Shape:
    with BuildSketch(Plane.XZ) as sketch:
        Polygon(*points, align=None)
    return extrude(sketch.sketch, amount=length, dir=(0, 1, 0)).translate((0, y_start, 0))


def prism_yz(points: list[tuple[float, float]], x_start: float, width: float) -> Shape:
    with BuildSketch(Plane.YZ) as sketch:
        Polygon(*points, align=None)
    return extrude(sketch.sketch, amount=width, dir=(1, 0, 0)).translate((x_start, 0, 0))


def prism_xy(points: list[tuple[float, float]], z_start: float, height: float) -> Shape:
    with BuildSketch(Plane.XY) as sketch:
        Polygon(*points, align=None)
    return extrude(sketch.sketch, amount=height, dir=(0, 0, 1)).translate((0, 0, z_start))


def self_supporting_slot_x(
    x_center: float,
    x_width: float,
    y_center: float,
    y_width: float,
    z_bottom: float,
    z_top: float,
) -> Shape:
    points = [
        (y_center - y_width / 2, z_bottom),
        (y_center - y_width / 2, z_top),
        (y_center + y_width / 2, z_top),
        (y_center + y_width / 2, z_bottom),
        (y_center, z_bottom - y_width / 2),
    ]
    return prism_yz(points, x_center - x_width / 2, x_width)


def rounded_prism_xz(
    width: float,
    height: float,
    radius: float,
    x: float,
    z: float,
    y_start: float,
    length: float,
) -> Shape:
    with BuildSketch(Plane.XZ) as sketch:
        with Locations((x, z)):
            RectangleRounded(width, height, radius)
    return extrude(sketch.sketch, amount=length, dir=(0, 1, 0)).translate((0, y_start, 0))


def rounded_prism_xy(
    width: float,
    depth: float,
    radius: float,
    x: float,
    y: float,
    z_start: float,
    height: float,
) -> Shape:
    with BuildSketch(Plane.XY) as sketch:
        with Locations((x, y)):
            RectangleRounded(width, depth, radius)
    return extrude(sketch.sketch, amount=height, dir=(0, 0, 1)).translate((0, 0, z_start))


def rounded_plate_xz(
    width: float,
    height: float,
    radius: float,
    depth: float,
    y_start: float,
    circular_opening: float | None = None,
    holes: Iterable[tuple[float, float, float]] = (),
) -> Shape:
    with BuildSketch(Plane.XZ) as sketch:
        with Locations((0, height / 2)):
            RectangleRounded(width, height, radius)
        if circular_opening is not None:
            with Locations((0, height / 2)):
                Circle(circular_opening, mode=Mode.SUBTRACT)
        for x, z, diameter in holes:
            with Locations((x, z)):
                Circle(diameter / 2, mode=Mode.SUBTRACT)
    return extrude(sketch.sketch, amount=depth, dir=(0, 1, 0)).translate((0, y_start, 0))


def device_centers(p: Params) -> tuple[float, float]:
    offset = p.device_center_gap / 2 + p.device_thickness / 2
    return -offset, offset


def right_lower_rail_profile(p: Params) -> list[tuple[float, float]]:
    wall_inner = p.body_width / 2 - p.shell_wall
    outer_top = p.rail_lower_inner_z + wall_inner - p.tongue_lower_inner_x
    return [
        (wall_inner, p.rail_lower_floor_z),
        (wall_inner, outer_top),
        (p.tongue_lower_inner_x, p.rail_lower_inner_z),
        (p.tongue_lower_inner_x, p.rail_lower_floor_z),
    ]


def right_upper_rail_profile(p: Params) -> list[tuple[float, float]]:
    wall_inner = p.body_width / 2 - p.shell_wall
    outer_bottom = p.rail_upper_inner_bottom_z + wall_inner - p.rail_inner_x
    return [
        (wall_inner, outer_bottom),
        (wall_inner, p.rail_top_z),
        (p.rail_inner_x, p.rail_upper_inner_top_z),
        (p.rail_inner_x, p.rail_upper_inner_bottom_z),
    ]


def right_tongue_profile(p: Params, clearance: float | None = None) -> list[tuple[float, float]]:
    fit = p.nominal_rail_clearance if clearance is None else clearance
    delta = fit - p.nominal_rail_clearance
    return [
        (p.tongue_inner_x - 0.3, p.tongue_lower_inner_z + delta),
        (p.tongue_lower_inner_x, p.tongue_lower_inner_z + delta),
        (p.tongue_outer_x, p.tongue_outer_bottom_z + delta),
        (p.tongue_outer_x, p.tongue_outer_top_z - delta),
        (p.tongue_inner_x, p.rail_upper_inner_bottom_z - p.nominal_rail_clearance - delta),
    ]


def side_profile(points: list[tuple[float, float]], side: int) -> list[tuple[float, float]]:
    mirrored = [(side * x, z) for x, z in points]
    if side == -1:
        mirrored.reverse()
    return mirrored


def build_u_cover(p: Params) -> Shape:
    inner_width = p.body_width - 2 * p.shell_wall
    inner_bottom = -4.0
    inner_top = p.body_height - p.shell_wall
    with BuildSketch(Plane.XZ) as profile:
        with Locations((0, p.body_height / 2)):
            RectangleRounded(p.body_width, p.body_height, p.outer_top_radius)
        with Locations((0, (inner_bottom + inner_top) / 2)):
            RectangleRounded(
                inner_width,
                inner_top - inner_bottom,
                p.inner_top_radius,
                mode=Mode.SUBTRACT,
            )
    shell = extrude(profile.sketch, amount=p.body_depth, dir=(0, 1, 0))

    # RectangleRounded also rounds the open lower corners. These side feet
    # restore a continuous wall down to Z=0 before the exposed edge fillet.
    right_foot = [
        (p.body_width / 2 - p.shell_wall, 0.0),
        (p.body_width / 2, 0.0),
        (p.body_width / 2, 8.0),
        (p.body_width / 2 - p.shell_wall, 8.0 - p.shell_wall),
    ]
    side_feet = [
        prism_xz(side_profile(right_foot, side), 0.0, p.body_depth)
        for side in (-1, 1)
    ]
    shell = union([shell, *side_feet])
    lower_edges = [
        edge
        for edge in shell.edges().filter_by(Axis.Y)
        if edge.center().Z < 0.2 and abs(edge.center().X) > p.body_width / 2 - 0.5
    ]
    if lower_edges:
        shell = fillet(lower_edges, p.exposed_edge_radius)

    # Paired 45-degree rails capture the base in both vertical directions.
    # Their sloped print-leading faces grow from the side wall without support
    # when the U cover is printed exterior-top-face down.
    rail_parts: list[Shape] = []
    right_profiles = [right_lower_rail_profile(p), right_upper_rail_profile(p)]
    for side in (-1, 1):
        for right_profile in right_profiles:
            profile_points = side_profile(right_profile, side)
            for start in p.rail_segment_starts:
                rail_parts.append(
                    prism_xz(
                        profile_points,
                        start + p.rail_lead_in,
                        p.rail_segment_length - 2 * p.rail_lead_in,
                    )
                )

    # Handle ribs overlap the top skin and stop 0.8 mm above the GB10 envelope.
    rib_z = p.body_height - p.shell_wall - p.handle_rib_thickness / 2 + 1.0
    handle_parts: list[Shape] = []
    for y in (p.handle_anchor_front_y, p.handle_anchor_rear_y):
        handle_parts.append(
            rounded_box_at(
                (p.body_width - 2 * p.shell_wall + 1.0, p.handle_rib_width, p.handle_rib_thickness),
                (0, y, rib_z),
                1.4,
            )
        )
        handle_parts.append(
            cyl_z(
                p.handle_boss_diameter / 2,
                p.body_height - 158.6,
                (0, y, (p.body_height + 158.6) / 2),
            )
        )

    cover = union([shell, *rail_parts, *handle_parts])

    cutters: list[Shape] = []
    for y in (p.handle_anchor_front_y, p.handle_anchor_rear_y):
        cutters.append(cyl_z(p.handle_insert_pilot / 2, 10.0, (0, y, p.body_height - 3.5)))

    # Upper front/rear hook pockets leave at least 2.2 mm of outer top skin.
    hook_pocket_width = p.upper_hook_width + 2 * p.panel_fit_clearance
    hook_pocket_height = p.upper_hook_tooth_height + 2 * p.panel_fit_clearance
    for x in (-p.panel_latch_x, p.panel_latch_x):
        cutters.append(box_at((hook_pocket_width, 9.0, hook_pocket_height), (x, 4.5, p.upper_hook_z + 1.8)))
        cutters.append(box_at((hook_pocket_width, 9.0, hook_pocket_height), (x, 153.5, p.upper_hook_z + 1.8)))

    # Reversible display key slots share their production geometry with the
    # display fit coupon and kinematic tests.
    for side in (-1, 1):
        cutters.extend(build_display_slot_cutters(p, side))
    return cut(cover, cutters)


def build_base_tongues(p: Params, clearance: float | None = None) -> list[Shape]:
    right_tongue = right_tongue_profile(p, clearance)
    tongues: list[Shape] = []
    for side in (-1, 1):
        points = side_profile(right_tongue, side)
        tongues.append(prism_xz(points, p.base_front_y, p.base_depth))
    return tongues


def base_guide_limits(p: Params) -> tuple[float, float]:
    front = p.front_latch_pocket_rear_y + p.guide_end_relief
    rear = p.rear_latch_pocket_front_y - p.guide_end_relief
    if rear <= front:
        raise ValueError("Guide relief consumes the complete guide length")
    return front, rear


def build_base_guides(p: Params) -> list[Shape]:
    front, rear = base_guide_limits(p)

    bundle_outer = p.device_center_gap / 2 + p.device_thickness
    outer_guide_x = bundle_outer + p.device_side_clearance + p.guide_width / 2
    return [
        rounded_prism_xz(
            p.guide_width,
            p.guide_height,
            p.guide_width / 2 - 0.05,
            x,
            p.base_thickness + p.guide_height / 2 - 0.3,
            front,
            rear - front,
        )
        for x in (-outer_guide_x, 0.0, outer_guide_x)
    ]


def build_base_rear_stop(p: Params) -> list[Shape]:
    stop_bottom = p.base_thickness - 0.8
    rear_stop = prism_yz(
        [
            (154.8, stop_bottom),
            (156.0, stop_bottom),
            (157.8, stop_bottom + 1.8),
            (157.8, stop_bottom + p.guide_height),
            (154.8, stop_bottom + p.guide_height),
        ],
        -p.rear_stop_width / 2,
        p.rear_stop_width,
    )
    rear_stop_foot = box_at((p.rear_stop_width, 4.0, 1.2), (0, 154.0, p.base_thickness - 0.5))
    return [rear_stop, rear_stop_foot]


def build_latch_receiver_cutters(
    p: Params,
    x_positions: tuple[float, ...] | None = None,
) -> list[Shape]:
    width = p.lower_latch_width + 2 * p.panel_fit_clearance
    base_rear_y = p.base_front_y + p.base_depth
    pocket_center_z = p.lower_latch_z + (p.latch_catch_height - p.lower_latch_thickness) / 2
    throat_bottom_z = p.lower_latch_z - p.latch_throat_height / 2
    throat_top_z = p.lower_latch_z + p.latch_throat_height / 2
    relief_top_z = p.base_thickness + 0.5
    relief_run = relief_top_z - throat_top_z
    cutters: list[Shape] = []
    for x in x_positions or (-p.panel_latch_x, p.panel_latch_x):
        front_throat_y0 = p.base_front_y - 0.5
        front_throat_y1 = p.front_latch_pocket_rear_y
        cutters.append(
            box_at(
                (width, front_throat_y1 - front_throat_y0, p.latch_throat_height),
                (x, (front_throat_y0 + front_throat_y1) / 2, p.lower_latch_z),
            )
        )
        cutters.append(
            prism_yz(
                [
                    (front_throat_y0, throat_top_z),
                    (front_throat_y0, relief_top_z),
                    (p.front_latch_pocket_front_y - relief_run, relief_top_z),
                    (p.front_latch_pocket_front_y, throat_top_z),
                ],
                x - width / 2,
                width,
            )
        )
        cutters.append(
            box_at(
                (
                    width,
                    p.front_latch_pocket_rear_y - p.front_latch_pocket_front_y,
                    p.latch_pocket_height,
                ),
                (
                    x,
                    (p.front_latch_pocket_front_y + p.front_latch_pocket_rear_y) / 2,
                    pocket_center_z,
                ),
            )
        )

        rear_throat_y0 = p.rear_latch_pocket_front_y
        rear_throat_y1 = base_rear_y + 0.5
        cutters.append(
            box_at(
                (width, rear_throat_y1 - rear_throat_y0, p.latch_throat_height),
                (x, (rear_throat_y0 + rear_throat_y1) / 2, p.lower_latch_z),
            )
        )
        cutters.append(
            prism_yz(
                [
                    (p.rear_latch_pocket_rear_y, throat_top_z),
                    (p.rear_latch_pocket_rear_y + relief_run, relief_top_z),
                    (rear_throat_y1, relief_top_z),
                    (rear_throat_y1, throat_top_z),
                ],
                x - width / 2,
                width,
            )
        )
        cutters.append(
            box_at(
                (
                    width,
                    p.rear_latch_pocket_rear_y - p.rear_latch_pocket_front_y,
                    p.latch_pocket_height,
                ),
                (
                    x,
                    (p.rear_latch_pocket_front_y + p.rear_latch_pocket_rear_y) / 2,
                    pocket_center_z,
                ),
            )
        )
    return cutters


def build_sliding_base(p: Params) -> Shape:
    plate = rounded_box_at(
        (p.base_plate_width, p.base_depth, p.base_thickness),
        (0, p.base_front_y + p.base_depth / 2, p.base_thickness / 2),
        2.2,
    )
    tongues = build_base_tongues(p)
    guides = build_base_guides(p)
    rear_stop = build_base_rear_stop(p)
    base = union([plate, *tongues, *guides, *rear_stop])

    cutters = build_latch_receiver_cutters(p)

    # Protected side harness channel stays outside the GB10 footprint.
    cutters.append(box_at((8.0, 92.0, 1.6), (-63.0, 92.0, p.base_thickness - 0.5)))
    cutters.append(box_at((8.0, 92.0, 1.6), (63.0, 92.0, p.base_thickness - 0.5)))
    return cut(base, cutters)


def fan_hole_locations(spacing: float, center_z: float) -> list[tuple[float, float]]:
    half = spacing / 2
    return [(x, center_z + z) for x in (-half, half) for z in (-half, half)]


def build_lower_latch(p: Params, x: float, root_y: float, front: bool) -> list[Shape]:
    arm_bottom = p.lower_latch_z - p.lower_latch_thickness / 2
    arm_top = p.lower_latch_z + p.lower_latch_thickness / 2
    tooth_top = arm_top + p.latch_catch_height
    if front:
        shoulder_y = p.front_latch_pocket_front_y + p.latch_capture
        lead_y = shoulder_y + 3.0
    else:
        shoulder_y = p.rear_latch_pocket_rear_y - p.latch_capture
        lead_y = shoulder_y - 3.0

    arm_y0, arm_y1 = sorted((root_y, lead_y))
    arm = rounded_box_at(
        (p.lower_latch_width, arm_y1 - arm_y0, p.lower_latch_thickness),
        (x, (arm_y0 + arm_y1) / 2, p.lower_latch_z),
        min(0.7, p.lower_latch_thickness / 2 - 0.05),
    )
    if front:
        catch_profile = [
            (shoulder_y + tooth_top - arm_bottom, arm_bottom),
            (shoulder_y, tooth_top),
            (lead_y, arm_top),
            (lead_y, arm_bottom),
        ]
    else:
        catch_profile = [
            (lead_y, arm_bottom),
            (lead_y, arm_top),
            (shoulder_y, tooth_top),
            (shoulder_y - (tooth_top - arm_bottom), arm_bottom),
        ]
    catch = prism_yz(catch_profile, x - p.lower_latch_width / 2, p.lower_latch_width)

    root_length = 3.0
    root_center_y = root_y + (root_length / 2 if front else -root_length / 2)
    root = rounded_box_at(
        (p.lower_latch_width, root_length, p.lower_latch_thickness + 2.0),
        (x, root_center_y, p.lower_latch_z),
        p.latch_root_radius,
    )
    return [arm, catch, root]


def build_upper_hook(p: Params, x: float, root_y: float, front: bool) -> list[Shape]:
    tip_y = p.upper_hook_reach if front else p.body_depth - p.upper_hook_reach
    arm_y0, arm_y1 = sorted((root_y, tip_y))
    arm = rounded_box_at(
        (p.upper_hook_width, arm_y1 - arm_y0, p.upper_hook_thickness),
        (x, (arm_y0 + arm_y1) / 2, p.upper_hook_z),
        min(0.7, p.upper_hook_thickness / 2 - 0.05),
    )
    tooth_bottom = p.upper_hook_z + 0.4
    tooth_top = tooth_bottom + p.upper_hook_tooth_height
    if front:
        tooth_profile = [
            (tip_y, tooth_bottom),
            (tip_y, tooth_top),
            (tip_y - 3.0, tooth_top),
            (tip_y - 0.2, tooth_bottom),
        ]
    else:
        tooth_profile = [
            (tip_y, tooth_bottom),
            (tip_y + 0.2, tooth_bottom),
            (tip_y + 3.0, tooth_top),
            (tip_y, tooth_top),
        ]
    tooth = prism_yz(tooth_profile, x - p.upper_hook_width / 2, p.upper_hook_width)
    return [arm, tooth]


def build_front_bezel(p: Params) -> Shape:
    y_start = -p.front_bezel_offset
    holes = [(x, z, p.front_pin_hole_diameter) for x, z in fan_hole_locations(p.front_fan_hole_spacing, p.body_height / 2)]
    frame = rounded_plate_xz(
        p.body_width,
        p.body_height,
        p.outer_top_radius,
        p.front_bezel_thickness,
        y_start,
        circular_opening=p.front_opening_radius,
        holes=holes,
    )

    grille: list[Shape] = []
    # Extend every bar into the fan ring by 3 mm. A merely tangent bar creates
    # fragile print joints and microscopic sliver faces during STL meshing.
    radius = p.front_opening_radius + 3.0
    positions = np.arange(-60.0, 60.01, p.front_grille_pitch)
    for x in positions:
        chord = 2 * math.sqrt(max(0.0, radius * radius - x * x))
        grille.append(
            rounded_prism_xz(
                p.front_grille_bar,
                chord,
                0.7,
                float(x),
                p.body_height / 2,
                y_start,
                2.4,
            )
        )
    for z_offset in positions:
        chord = 2 * math.sqrt(max(0.0, radius * radius - z_offset * z_offset))
        grille.append(
            rounded_prism_xz(
                chord,
                p.front_grille_bar,
                0.7,
                0,
                p.body_height / 2 + float(z_offset),
                y_start,
                2.4,
            )
        )

    back_face = y_start + p.front_bezel_thickness
    hooks: list[Shape] = []
    for x in (-p.panel_latch_x, p.panel_latch_x):
        hooks.extend(build_upper_hook(p, x, back_face - p.panel_arm_root_overlap, front=True))
        hooks.extend(build_lower_latch(p, x, back_face - p.panel_arm_root_overlap, front=True))

    bezel = union([frame, *grille, *hooks])
    release_windows = [
        box_at(
            (p.latch_release_window_width, p.front_bezel_thickness + 2.0, 5.0),
            (x, y_start + p.front_bezel_thickness / 2, p.lower_latch_z + 0.5),
        )
        for x in (-p.panel_latch_x, p.panel_latch_x)
    ]
    return cut(bezel, release_windows)


def build_rear_frame(p: Params) -> Shape:
    y_start = p.body_depth
    with BuildSketch(Plane.XZ) as sketch:
        with Locations((0, p.body_height / 2)):
            RectangleRounded(p.body_width, p.body_height, p.outer_top_radius)
            RectangleRounded(p.body_width - 16.0, p.body_height - 16.0, 6.0, mode=Mode.SUBTRACT)
    perimeter = extrude(sketch.sketch, amount=p.rear_frame_thickness, dir=(0, 1, 0)).translate((0, y_start, 0))

    center_z = p.body_height / 2
    fan_plate = box_at((66.0, p.rear_frame_thickness, 66.0), (0, y_start + p.rear_frame_thickness / 2, center_z))
    fan_plate = fan_plate - cyl_y(p.rear_fan_opening_radius, p.rear_frame_thickness + 2.0, (0, y_start + p.rear_frame_thickness / 2, center_z))
    for x, z in fan_hole_locations(p.rear_fan_hole_spacing, center_z):
        fan_plate = fan_plate - cyl_y(p.rear_pin_hole_diameter / 2, p.rear_frame_thickness + 2.0, (x, y_start + p.rear_frame_thickness / 2, z))

    supports = [
        rounded_box_at((5.0, p.rear_frame_thickness, p.body_height - 16.0), (x, y_start + p.rear_frame_thickness / 2, center_z), 1.5)
        for x in (-34.0, 34.0)
    ]
    guard = [
        rounded_box_at((2.0, 2.4, 56.5), (0, y_start + p.rear_frame_thickness - 1.2, center_z), 0.7),
        rounded_box_at((56.5, 2.4, 2.0), (0, y_start + p.rear_frame_thickness - 1.2, center_z), 0.7),
    ]

    hooks: list[Shape] = []
    rear_root_y = y_start + p.panel_arm_root_overlap
    for x in (-p.panel_latch_x, p.panel_latch_x):
        hooks.extend(build_upper_hook(p, x, rear_root_y, front=False))
        hooks.extend(build_lower_latch(p, x, rear_root_y, front=False))
    frame = union([perimeter, fan_plate, *supports, *guard, *hooks])
    release_windows = [
        box_at(
            (p.latch_release_window_width, p.rear_frame_thickness + 2.0, 5.0),
            (x, y_start + p.rear_frame_thickness / 2, p.lower_latch_z + 0.5),
        )
        for x in (-p.panel_latch_x, p.panel_latch_x)
    ]
    return cut(frame, release_windows)


def display_inner_face_x(p: Params, side: int) -> float:
    return side * (p.body_width / 2 + p.display_gap)


def build_display_top_hooks(
    p: Params,
    side: int,
    hook_y: tuple[float, ...] | None = None,
) -> list[Shape]:
    hooks: list[Shape] = []
    inner_face = display_inner_face_x(p, side)
    stem_outer_x = abs(inner_face) + 0.4
    transition_outer_x = abs(inner_face) - 4.7
    transition_inner_x = transition_outer_x - (
        p.display_hook_head_y - p.display_hook_stem_y
    ) / 2
    head_inner_x = transition_inner_x - 1.5
    stem_half_y = p.display_hook_stem_y / 2
    head_half_y = p.display_hook_head_y / 2
    right_profile = [
        (stem_outer_x, -stem_half_y),
        (transition_outer_x, -stem_half_y),
        (transition_inner_x, -head_half_y),
        (head_inner_x, -head_half_y),
        (head_inner_x, head_half_y),
        (transition_inner_x, head_half_y),
        (transition_outer_x, stem_half_y),
        (stem_outer_x, stem_half_y),
    ]
    for y in hook_y or p.display_hook_y:
        profile = [(side * x, y + local_y) for x, local_y in right_profile]
        if side == -1:
            profile.reverse()
        hooks.append(
            prism_xy(
                profile,
                p.display_hook_z - 2.0,
                4.0,
            )
        )
    return hooks


def build_display_slot_cutters(
    p: Params,
    side: int,
    hook_y: tuple[float, ...] | None = None,
    include_latch: bool = True,
) -> list[Shape]:
    wall_center_x = side * (p.body_width - p.shell_wall) / 2
    entry_y = p.display_hook_head_y + 2 * p.display_fit_clearance
    entry_z = p.display_hook_head_z + 2 * p.display_fit_clearance
    slot_y = p.display_hook_stem_y + 2 * p.display_fit_clearance
    slot_z = p.display_lock_travel + 4.0
    cutters: list[Shape] = []
    for y in hook_y or p.display_hook_y:
        cutters.append(
            self_supporting_slot_x(
                wall_center_x,
                p.shell_wall + 4.0,
                y,
                entry_y,
                p.display_hook_z + p.display_lock_travel - entry_z / 2,
                p.display_hook_z + p.display_lock_travel + entry_z / 2,
            )
        )
        cutters.append(
            self_supporting_slot_x(
                wall_center_x,
                p.shell_wall + 4.0,
                y,
                slot_y,
                p.display_hook_z + p.display_lock_travel / 2 - slot_z / 2,
                p.display_hook_z + p.display_lock_travel / 2 + slot_z / 2,
            )
        )
    if include_latch:
        cutters.append(
            self_supporting_slot_x(
                wall_center_x,
                p.shell_wall + 4.0,
                p.display_center_y,
                10.0 + 2 * p.display_fit_clearance,
                p.display_latch_z - (5.0 + 2 * p.display_fit_clearance) / 2,
                p.display_latch_z + (5.0 + 2 * p.display_fit_clearance) / 2,
            )
        )
        cutters.append(
            self_supporting_slot_x(
                wall_center_x,
                p.shell_wall + 4.0,
                p.display_center_y,
                12.0,
                70.0,
                78.0,
            )
        )
    return cutters


def build_display_latch(p: Params, side: int) -> list[Shape]:
    inner_face = display_inner_face_x(p, side)
    stem_outer_x = abs(inner_face) + 0.4
    stem_inner_x = abs(inner_face) - 5.0
    head_inner_x = stem_inner_x - 2.25
    stem_bottom = p.display_latch_z - 0.75
    stem_top = p.display_latch_z + 0.75
    right_profile = [
        (stem_outer_x, stem_bottom),
        (stem_inner_x, stem_bottom),
        (head_inner_x, p.display_latch_z - 2.0),
        (head_inner_x, p.display_latch_z + 4.0),
        (stem_inner_x, stem_top),
        (stem_outer_x, stem_top),
    ]
    return [
        prism_xz(
            side_profile(right_profile, side),
            p.display_center_y - 5.0,
            10.0,
        )
    ]


def build_display_hooks(p: Params, side: int) -> list[Shape]:
    return [*build_display_top_hooks(p, side), *build_display_latch(p, side)]


def build_display_pod(p: Params, side: int) -> Shape:
    if side not in (-1, 1):
        raise ValueError("display side must be -1 or 1")
    inner_face = display_inner_face_x(p, side)
    outer_face = inner_face + side * p.display_projection
    center_x = (inner_face + outer_face) / 2
    outer = rounded_box_at(
        (p.display_projection, p.display_depth, p.display_height),
        (center_x, p.display_center_y, p.display_center_z),
        5.0,
    )

    # The cavity opens through the enclosure-facing side. The U-cover wall is
    # the installed back and the print no longer has a 60+ mm sealed bridge.
    cavity_inner = inner_face - side * 2.0
    cavity_outer = outer_face - side * p.display_wall
    cavity = rounded_box_at(
        (abs(cavity_outer - cavity_inner), p.display_depth - 8.0, p.display_height - 8.0),
        ((cavity_inner + cavity_outer) / 2, p.display_center_y, p.display_center_z),
        3.0,
    )
    screen_cut = box_at(
        (7.0, p.display_screen_width, p.display_screen_height),
        (outer_face - side * 1.5, p.display_center_y, p.display_center_z + 5.0),
    )
    bottom_service = box_at(
        (p.display_projection + 2.0, p.display_depth - 12.0, 5.0),
        (center_x, p.display_center_y, p.display_center_z - p.display_height / 2 + 1.5),
    )
    usb_slot = box_at(
        (8.0, 12.0, 8.0),
        (inner_face + side * 4.0, p.display_center_y + 22.0, p.display_center_z - p.display_height / 2 + 2.0),
    )
    pod = cut(outer, [cavity, screen_cut, bottom_service, usb_slot])
    boss_outer = outer_face - side * (p.display_wall - 0.5)
    boss_inner = inner_face - side * 0.5
    boss_depth = abs(boss_inner - boss_outer)
    boss_center_x = (boss_inner + boss_outer) / 2
    mount_bosses = [
        box_at((boss_depth, 9.0, 10.0), (boss_center_x, y, p.display_hook_z))
        for y in p.display_hook_y
    ]
    mount_bosses.append(
        box_at((boss_depth, 12.0, 8.0), (boss_center_x, p.display_center_y, p.display_latch_z))
    )
    return union([pod, *mount_bosses, *build_display_hooks(p, side)])


def build_display_blank(p: Params, side: int) -> Shape:
    if side not in (-1, 1):
        raise ValueError("display side must be -1 or 1")
    inner_face = display_inner_face_x(p, side)
    center_x = inner_face + side * 1.5
    plate = rounded_box_at(
        (3.0, p.display_depth, p.display_height),
        (center_x, p.display_center_y, p.display_center_z),
        4.0,
    )
    return union([plate, *build_display_hooks(p, side)])


def build_device_references(p: Params) -> list[Shape]:
    z = p.base_thickness + p.device_bottom_clearance + p.device_height / 2
    y = p.device_front_clearance + p.device_depth / 2
    return [
        rounded_box_at(
            (p.device_thickness, p.device_depth, p.device_height),
            (x, y, z),
            3.5,
        )
        for x in device_centers(p)
    ]


def build_fan_references(p: Params) -> list[Shape]:
    front = rounded_box_at(
        (p.front_fan_size, p.front_fan_thickness, p.front_fan_size),
        (0, -p.front_fan_thickness / 2, p.body_height / 2),
        2.0,
    )
    rear = rounded_box_at(
        (p.rear_fan_size, p.rear_fan_thickness, p.rear_fan_size),
        (0, p.body_depth + p.rear_frame_thickness + p.rear_fan_thickness / 2, p.body_height / 2),
        2.0,
    )
    return [front, rear]


def build_handle_reference(p: Params) -> Shape:
    z0 = p.body_height
    z1 = z0 + p.handle_reference_height
    front = p.handle_anchor_front_y
    rear = p.handle_anchor_rear_y
    return union(
        [
            cyl_z(4.2, z1 - z0, (0, front, (z0 + z1) / 2)),
            cyl_z(4.2, z1 - z0, (0, rear, (z0 + z1) / 2)),
            cyl_y(4.2, rear - front, (0, (front + rear) / 2, z1)),
        ]
    )


def build_pair_fit_gauge(p: Params) -> Shape:
    depth = 24.0
    plate = rounded_box_at((116.0, depth, 4.0), (0, depth / 2, 2.0), 1.5)
    bundle_outer = p.device_center_gap / 2 + p.device_thickness
    outer_x = bundle_outer + p.device_side_clearance + p.guide_width / 2
    guides = [
        rounded_prism_xz(p.guide_width, p.guide_height, 1.1, x, 7.0, 0, depth)
        for x in (-outer_x, 0.0, outer_x)
    ]
    return union([plate, *guides])


def build_fan_mount_gauge(size: float, spacing: float, hole_diameter: float) -> Shape:
    thickness = 3.0
    gauge = rounded_box_at((size, size, thickness), (0, 0, thickness / 2), 3.0)
    gauge = gauge - cyl_z(size / 2 - 9.0, thickness + 2.0, (0, 0, thickness / 2))
    half = spacing / 2
    for x in (-half, half):
        for y in (-half, half):
            gauge = gauge - cyl_z(hole_diameter / 2, thickness + 2.0, (x, y, thickness / 2))
    return gauge.clean()


def build_grille_coupon(p: Params) -> Shape:
    size = 60.0
    frame = rounded_box_at((size, size, 3.0), (0, 0, 1.5), 3.0)
    frame = frame - cyl_z(26.0, 5.0, (0, 0, 1.5))
    bars: list[Shape] = []
    radius = 26.0
    for x in np.arange(-22.5, 22.6, p.front_grille_pitch):
        chord = 2 * math.sqrt(max(0.0, radius * radius - x * x)) + 1.0
        bars.append(rounded_prism_xy(p.front_grille_bar, chord, 0.7, float(x), 0, 0, 2.4))
    for y in np.arange(-22.5, 22.6, p.front_grille_pitch):
        chord = 2 * math.sqrt(max(0.0, radius * radius - y * y)) + 1.0
        bars.append(rounded_prism_xy(chord, p.front_grille_bar, 0.7, 0, float(y), 0, 2.4))
    return union([frame, *bars])


def build_corner_coupon(p: Params) -> Shape:
    cover = build_u_cover(p)
    return cover & box_at((34.0, 24.0, 34.0), (p.body_width / 2 - 17.0, 12.0, p.body_height - 17.0))


def build_display_window_gauge(p: Params) -> Shape:
    plate = rounded_box_at((74.0, 58.0, 3.0), (0, 0, 1.5), 4.0)
    return plate - box_at((p.display_screen_width, p.display_screen_height, 5.0), (0, 0, 1.5))


def build_rail_coupon_cover(p: Params) -> Shape:
    wall_inner = p.body_width / 2 - p.shell_wall
    lane_positions = (-35.0, 0.0, 35.0)
    parts: list[Shape] = [
        box_at((80.0, 3.0, 3.0), (5.0, 5.5, 13.5)),
    ]
    for lane_x in lane_positions:
        parts.append(box_at((10.0, 42.0, 3.0), (lane_x + 5.0, 25.0, 1.5)))
        parts.append(box_at((p.shell_wall, 42.0, p.rail_top_z), (lane_x + p.shell_wall / 2, 25.0, p.rail_top_z / 2)))
        for y_start, length in ((5.0, 15.0), (28.0, 15.0)):
            for profile in (right_lower_rail_profile(p), right_upper_rail_profile(p)):
                shifted = [(lane_x + x - wall_inner, z) for x, z in profile]
                parts.append(prism_xz(shifted, y_start, length))
    return union(parts)


def build_rail_coupon_slider(p: Params) -> Shape:
    wall_inner = p.body_width / 2 - p.shell_wall
    lane_positions = (-35.0, 0.0, 35.0)
    parts: list[Shape] = [
        box_at((80.0, 3.0, 3.0), (-5.0, 48.5, 1.5)),
    ]
    for index, lane_x in enumerate(lane_positions):
        parts.append(box_at((5.6, 50.0, 3.0), (lane_x - 7.2, 25.0, 1.5)))
        clearance = (0.30, 0.40, 0.50)[index]
        profile = [
            (lane_x + x - wall_inner, z)
            for x, z in right_tongue_profile(p, clearance)
        ]
        parts.append(prism_xz(profile, 2.0, 44.0))
    return union(parts)


def build_latch_coupon_panel(p: Params, front: bool = True) -> Shape:
    if front:
        plate_y = -p.front_bezel_offset + p.front_bezel_thickness / 2
        root_y = -p.front_bezel_offset + p.front_bezel_thickness - p.panel_arm_root_overlap
    else:
        plate_y = p.body_depth + p.rear_frame_thickness / 2
        root_y = p.body_depth + p.panel_arm_root_overlap
    plate = rounded_box_at((40.0, 7.0, 18.0), (0, plate_y, 9.0), 2.0)
    coupon = union([plate, *build_lower_latch(p, 0.0, root_y, front)])
    return oriented(coupon, Axis.X, 90 if front else -90)


def build_latch_coupon_receiver(p: Params, front: bool = True) -> Shape:
    if front:
        receiver = rounded_box_at((40.0, 16.0, 10.0), (0, 8.0, 5.0), 2.0)
    else:
        receiver = rounded_box_at((40.0, 16.0, 10.0), (0, 148.0, 5.0), 2.0)
    return normalize(cut(receiver, build_latch_receiver_cutters(p, (0.0,))))


def build_display_coupon_cover(p: Params) -> Shape:
    side = -1
    wall_center_x = side * (p.body_width - p.shell_wall) / 2
    wall = box_at((p.shell_wall, 46.0, 70.0), (wall_center_x, 53.0, 107.0))
    cutters = build_display_slot_cutters(p, side, (p.display_hook_y[0],), include_latch=True)
    return oriented(cut(wall, cutters), Axis.X, 180)


def build_display_coupon_pod(p: Params) -> Shape:
    side = -1
    inner_face = display_inner_face_x(p, side)
    backing = box_at((15.0, 46.0, 70.0), (inner_face - 7.5, 53.0, 107.0))
    top_hook = build_display_top_hooks(p, side, (p.display_hook_y[0],))
    return oriented(
        union([backing, *top_hook, *build_display_latch(p, side)]),
        Axis.Y,
        -90,
    )


COLOR_SCHEMES = {
    "A": {
        "name": "Dark-copper industrial",
        "u_cover_and_blank": "Mist gray #D9DDDA",
        "base_front_rear": "Graphite #292F31",
        "display_pod": "Dark copper-orange #A94D2D",
    },
    "B": {
        "name": "NVIDIA technical",
        "u_cover_and_blank": "Cool white #ECEFED",
        "base_front_rear": "Charcoal #1D2224",
        "display_pod": "NVIDIA green reference #76B900",
    },
    "C": {
        "name": "Graphite workstation",
        "u_cover_and_blank": "Deep graphite #343A3C",
        "base_front_rear": "Matte black #171B1D",
        "display_pod": "Titanium gray #8B9698",
    },
}


def shape_volume(shape: Shape) -> float:
    return float(sum(solid.volume for solid in shape.solids()))


def intersection_volume(a: Shape, b: Shape) -> float:
    return shape_volume(a & b)


def bbox_record(shape: Shape) -> dict[str, list[float]]:
    bbox = shape.bounding_box()
    return {
        "min": [round(bbox.min.X, 4), round(bbox.min.Y, 4), round(bbox.min.Z, 4)],
        "max": [round(bbox.max.X, 4), round(bbox.max.Y, 4), round(bbox.max.Z, 4)],
        "size": [round(bbox.size.X, 4), round(bbox.size.Y, 4), round(bbox.size.Z, 4)],
    }


def parse_binary_stl(path: Path) -> tuple[np.ndarray, np.ndarray]:
    data = path.read_bytes()
    if len(data) < 84:
        raise ValueError(f"STL too short: {path}")
    count = struct.unpack_from("<I", data, 80)[0]
    if len(data) != 84 + count * 50:
        raise ValueError(f"Expected binary STL: {path}")
    triangles = np.empty((count, 3, 3), dtype=np.float64)
    for index in range(count):
        offset = 84 + index * 50 + 12
        triangles[index] = np.array(struct.unpack_from("<9f", data, offset)).reshape(3, 3)
    return triangles, triangles.reshape(-1, 3)


def clean_binary_stl(path: Path, area_tolerance: float = 1e-10) -> int:
    data = path.read_bytes()
    count = struct.unpack_from("<I", data, 80)[0]
    records: list[bytes] = []
    removed = 0
    for index in range(count):
        offset = 84 + index * 50
        record = data[offset : offset + 50]
        vertices = np.array(struct.unpack_from("<9f", record, 12), dtype=np.float64).reshape(3, 3)
        area = np.linalg.norm(np.cross(vertices[1] - vertices[0], vertices[2] - vertices[0])) / 2
        if area <= area_tolerance:
            removed += 1
        else:
            records.append(record)
    path.write_bytes(data[:80] + struct.pack("<I", len(records)) + b"".join(records))
    return removed


def stl_mesh_record(path: Path) -> dict[str, int | list[float]]:
    triangles, vertices = parse_binary_stl(path)
    areas = np.linalg.norm(
        np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]),
        axis=1,
    ) / 2
    degenerate = int(np.count_nonzero(areas <= 1e-10))
    triangles = triangles[areas > 1e-10]
    vertices = triangles.reshape(-1, 3)
    rounded = np.round(vertices, 5)
    vertex_ids: dict[tuple[float, float, float], int] = {}
    ids: list[int] = []
    for vertex in rounded:
        key = tuple(float(value) for value in vertex)
        if key not in vertex_ids:
            vertex_ids[key] = len(vertex_ids)
        ids.append(vertex_ids[key])
    edges: dict[tuple[int, int], int] = {}
    face_ids = np.array(ids, dtype=np.int64).reshape(-1, 3)
    for face in face_ids:
        for first, second in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            if first == second:
                continue
            edge = tuple(sorted((int(first), int(second))))
            edges[edge] = edges.get(edge, 0) + 1
    mins = vertices.min(axis=0)
    maxs = vertices.max(axis=0)
    return {
        "triangles": int(len(triangles)),
        "vertices": int(len(vertex_ids)),
        "degenerate_triangles": degenerate,
        "non_manifold_edges": int(sum(count != 2 for count in edges.values())),
        "mesh_size": [round(float(value), 4) for value in maxs - mins],
    }


def stl_printability_record(
    path: Path,
    horizontal_cosine: float = 0.98,
    bed_tolerance: float = 0.05,
    near_bed_support_height: float = 3.0,
) -> dict[str, float]:
    triangles, vertices = parse_binary_stl(path)
    cross_products = np.cross(
        triangles[:, 1] - triangles[:, 0],
        triangles[:, 2] - triangles[:, 0],
    )
    double_areas = np.linalg.norm(cross_products, axis=1)
    valid = double_areas > 1e-10
    triangles = triangles[valid]
    cross_products = cross_products[valid]
    areas = double_areas[valid] / 2
    normal_z = cross_products[:, 2] / double_areas[valid]
    min_z = float(vertices[:, 2].min())
    on_bed = (
        (np.abs(normal_z) >= horizontal_cosine)
        & (np.max(triangles[:, :, 2], axis=1) <= min_z + bed_tolerance)
    )
    above_bed = (
        np.min(triangles[:, :, 2], axis=1)
        > min_z + near_bed_support_height
    )
    unsupported_horizontal = (normal_z <= -horizontal_cosine) & above_bed
    return {
        "bed_contact_area_mm2": round(float(areas[on_bed].sum()), 2),
        "unsupported_downward_horizontal_area_mm2": round(
            float(areas[unsupported_horizontal].sum()),
            2,
        ),
    }


def render_stl_preview(stl_path: Path, image_path: Path, elev: float, azim: float) -> None:
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    triangles, vertices = parse_binary_stl(stl_path)
    fig = plt.figure(figsize=(7.2, 7.2), facecolor="#e9eded")
    ax = fig.add_subplot(111, projection="3d", facecolor="#e9eded")
    mesh = Poly3DCollection(
        triangles,
        facecolor="#343a3c",
        edgecolor="none",
        linewidth=0.0,
        alpha=1.0,
    )
    ax.add_collection3d(mesh)
    mins = vertices.min(axis=0)
    maxs = vertices.max(axis=0)
    center = (mins + maxs) / 2
    radius = max(maxs - mins) * 0.62
    ax.set_xlim(center[0] - radius, center[0] + radius)
    ax.set_ylim(center[1] - radius, center[1] + radius)
    ax.set_zlim(center[2] - radius, center[2] + radius)
    ax.set_box_aspect((1, 1, 1))
    ax.set_proj_type("ortho")
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()
    fig.tight_layout(pad=0)
    image_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(image_path, dpi=200, bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)


def projection_vectors(view: str, p: Params) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    look = (0.0, p.body_depth / 2, p.body_height / 2)
    vectors = {
        "front": ((0.0, -1000.0, p.body_height / 2), (0.0, 0.0, 1.0), look),
        "rear": ((0.0, 1000.0, p.body_height / 2), (0.0, 0.0, 1.0), look),
        "top": ((0.0, p.body_depth / 2, 1000.0), (0.0, 1.0, 0.0), look),
        "left": ((-1000.0, p.body_depth / 2, p.body_height / 2), (0.0, 0.0, 1.0), look),
        "right": ((1000.0, p.body_depth / 2, p.body_height / 2), (0.0, 0.0, 1.0), look),
    }
    return vectors[view]


def export_projection(shape: Shape, view: str, dxf_path: Path, svg_path: Path, p: Params) -> None:
    origin, up, look_at = projection_vectors(view, p)
    visible, _hidden = shape.project_to_viewport(origin, up, look_at)
    dxf = ExportDXF()
    dxf.add_layer("VISIBLE")
    dxf.add_shape(visible, "VISIBLE")
    dxf.write(dxf_path)
    svg = ExportSVG(scale=1.0, margin=5.0)
    svg.add_layer("VISIBLE")
    svg.add_shape(visible, "VISIBLE")
    svg.write(svg_path)


def _sheet(p: Params, drawing_no: str, title: str) -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(figsize=(11.69, 8.27), facecolor="white")
    ax = fig.add_axes((0.055, 0.105, 0.89, 0.78))
    ax.set_axis_off()
    fig.add_artist(Rectangle((0.025, 0.035), 0.95, 0.93, fill=False, linewidth=1.2, transform=fig.transFigure))
    fig.add_artist(Rectangle((0.025, 0.035), 0.95, 0.065, fill=False, linewidth=0.8, transform=fig.transFigure))
    fig.text(0.04, 0.067, "DUAL GB10 R2.1 ENCLOSURE", fontsize=10, weight="bold")
    fig.text(0.30, 0.067, title, fontsize=9, weight="bold")
    fig.text(0.70, 0.067, drawing_no, fontsize=9, family="monospace")
    fig.text(0.83, 0.067, p.revision, fontsize=9, weight="bold")
    fig.text(0.04, 0.046, "UNITS: mm | SCALE: AS SHOWN | THIRD ANGLE", fontsize=7)
    fig.text(0.70, 0.046, "STATUS: RC - VERIFY HARDWARE", fontsize=7, color="#a33525", weight="bold")
    fig.text(0.04, 0.925, "NOT FOR PRODUCTION UNTIL PHYSICAL RELEASE GATES ARE SIGNED", fontsize=8, color="#a33525", weight="bold")
    return fig, ax


def _dim_h(ax: plt.Axes, x0: float, x1: float, y: float, label: str, offset: float = 8.0) -> None:
    yy = y + offset
    ax.annotate("", (x0, yy), (x1, yy), arrowprops={"arrowstyle": "<->", "lw": 0.8, "color": "#273034"})
    ax.plot([x0, x0], [y, yy + 1], color="#6a7478", lw=0.6)
    ax.plot([x1, x1], [y, yy + 1], color="#6a7478", lw=0.6)
    ax.text(
        (x0 + x1) / 2,
        yy + 1.5,
        label,
        ha="center",
        va="bottom",
        fontsize=7,
        bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.4},
    )


def _dim_v(ax: plt.Axes, y0: float, y1: float, x: float, label: str, offset: float = 8.0) -> None:
    xx = x + offset
    ax.annotate("", (xx, y0), (xx, y1), arrowprops={"arrowstyle": "<->", "lw": 0.8, "color": "#273034"})
    ax.plot([x, xx + 1], [y0, y0], color="#6a7478", lw=0.6)
    ax.plot([x, xx + 1], [y1, y1], color="#6a7478", lw=0.6)
    ax.text(
        xx + 1.5,
        (y0 + y1) / 2,
        label,
        ha="left",
        va="center",
        rotation=90,
        fontsize=7,
        bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.4},
    )


def _view_axis(fig: plt.Figure, rect: tuple[float, float, float, float], title: str) -> plt.Axes:
    ax = fig.add_axes(rect)
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title(title, fontsize=8, pad=2)
    return ax


def generate_engineering_drawings(p: Params, pdf_path: Path) -> None:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(pdf_path) as pdf:
        fig, ax = _sheet(p, "R2-000", "RELEASE COVER AND CONTROLLED DIMENSIONS")
        ax.text(0.0, 0.96, "Dual xFusion FusionXpark GB10 - R2.1 Release Candidate", transform=ax.transAxes, fontsize=18, weight="bold", va="top")
        ax.text(0.0, 0.88, "Selected architecture", transform=ax.transAxes, fontsize=11, weight="bold")
        bullets = [
            "One-piece rounded U cover and front-loading captured base",
            "140 x 25 front intake fan; 60 x 15 central rear exhaust assist",
            "Tool-less front and rear fan panels; two M4 handle bolts only",
            "Two GB10 units on edge with 0.8 nominal hard-guide clearance",
            "Reversible side display pod; default left; no rotary encoder hole",
            "Color scheme C is default; schemes A and B remain approved alternates",
        ]
        for index, line in enumerate(bullets):
            ax.text(0.02, 0.82 - index * 0.055, f"{index + 1}. {line}", transform=ax.transAxes, fontsize=9)
        ax.text(0.0, 0.44, "Mandatory physical release gates", transform=ax.transAxes, fontsize=11, weight="bold", color="#a33525")
        gates = [
            "Measure both GB10 units and run pair-fit gauge",
            "Measure fan hole patterns, frame thicknesses, and silicone pins",
            "Measure selected display PCB, screen, USB-C, and mounting envelope",
            "Confirm commercial handle hole spacing and pass 12 kg / 60 s proof load",
            "Install all rear cables and confirm bend radius with rear frame fitted",
            "Verify GB10 USB-C source current before controller power release",
        ]
        for index, line in enumerate(gates):
            ax.text(0.02, 0.38 - index * 0.05, f"G{index + 1}  {line}", transform=ax.transAxes, fontsize=8.5)
        ax.text(0.0, 0.04, "CAD generation passing does not close these hardware gates.", transform=ax.transAxes, fontsize=9, weight="bold")
        pdf.savefig(fig)
        plt.close(fig)

        fig, _ = _sheet(p, "R2-001", "GENERAL ARRANGEMENT")
        front = _view_axis(fig, (0.07, 0.17, 0.25, 0.58), "FRONT")
        front.add_patch(FancyBboxPatch((-p.body_width / 2, 0), p.body_width, p.body_height, boxstyle=f"round,pad=0,rounding_size={p.outer_top_radius}", fill=False, lw=1.2))
        front.add_patch(PlotCircle((0, p.body_height / 2), p.front_opening_radius, fill=False, lw=0.9))
        front.set_xlim(-95, 95); front.set_ylim(-18, 190)
        _dim_h(front, -p.body_width / 2, p.body_width / 2, 0, f"{p.body_width:.1f}", -12)
        _dim_v(front, 0, p.body_height, p.body_width / 2, f"{p.body_height:.1f}", 12)

        side = _view_axis(fig, (0.37, 0.17, 0.28, 0.58), "LEFT SIDE - DISPLAY INSTALLED")
        side.add_patch(Rectangle((0, 0), p.body_depth, p.body_height, fill=False, lw=1.2))
        side.add_patch(Rectangle((-p.front_bezel_offset, 0), p.front_bezel_thickness, p.body_height, fill=False, lw=0.9))
        side.add_patch(Rectangle((p.body_depth, 0), p.rear_frame_thickness, p.body_height, fill=False, lw=0.9))
        side.add_patch(FancyBboxPatch((p.display_center_y - p.display_depth / 2, p.display_center_z - p.display_height / 2), p.display_depth, p.display_height, boxstyle="round,pad=0,rounding_size=5", fill=False, lw=0.9))
        side.set_xlim(-48, 184); side.set_ylim(-18, 190)
        _dim_h(side, -p.front_bezel_offset, p.body_depth + p.rear_frame_thickness, 0, f"PRINTED DEPTH {p.body_depth + p.rear_frame_thickness + p.front_bezel_offset:.1f}", -12)
        _dim_h(side, 0, p.body_depth, p.body_height, f"BODY {p.body_depth:.1f}", 10)

        top = _view_axis(fig, (0.70, 0.17, 0.23, 0.58), "TOP")
        top.add_patch(Rectangle((-p.body_width / 2, 0), p.body_width, p.body_depth, fill=False, lw=1.2))
        top.add_patch(Rectangle((-p.body_width / 2 - p.display_projection - p.display_gap, p.display_center_y - p.display_depth / 2), p.display_projection, p.display_depth, fill=False, lw=0.9))
        top.plot([0, 0], [p.handle_anchor_front_y, p.handle_anchor_rear_y], color="#273034", lw=4)
        top.set_xlim(-115, 100); top.set_ylim(-18, 178)
        _dim_h(top, -p.body_width / 2 - p.display_projection - p.display_gap, p.body_width / 2, 0, f"WITH POD {p.body_width + p.display_projection + p.display_gap:.1f}", -12)
        _dim_v(top, p.handle_anchor_front_y, p.handle_anchor_rear_y, 0, f"HANDLE PITCH {p.handle_anchor_rear_y - p.handle_anchor_front_y:.1f}", 15)
        pdf.savefig(fig)
        plt.close(fig)

        fig, _ = _sheet(p, "R2-101", "ONE-PIECE U COVER")
        cross = _view_axis(fig, (0.08, 0.18, 0.38, 0.6), "FRONT CROSS-SECTION")
        cross.add_patch(FancyBboxPatch((-p.body_width / 2, 0), p.body_width, p.body_height, boxstyle=f"round,pad=0,rounding_size={p.outer_top_radius}", fill=False, lw=1.2))
        cross.add_patch(FancyBboxPatch((-(p.body_width - 2 * p.shell_wall) / 2, -6), p.body_width - 2 * p.shell_wall, p.body_height - p.shell_wall + 6, boxstyle=f"round,pad=0,rounding_size={p.inner_top_radius}", facecolor="white", edgecolor="#667176", lw=0.8))
        for side_sign in (-1, 1):
            for profile in (right_lower_rail_profile(p), right_upper_rail_profile(p)):
                cross.add_patch(plt.Polygon(side_profile(profile, side_sign), fill=False, lw=0.8))
        cross.set_xlim(-95, 95); cross.set_ylim(-15, 188)
        _dim_h(cross, -p.body_width / 2, p.body_width / 2, 0, f"{p.body_width:.1f}", -10)
        _dim_v(cross, 0, p.body_height, p.body_width / 2, f"{p.body_height:.1f}", 12)
        cross.text(0, 150, f"R OUT {p.outer_top_radius:.1f}\nR IN {p.inner_top_radius:.1f}\nWALL {p.shell_wall:.1f}", ha="center", fontsize=8)

        rail = _view_axis(fig, (0.53, 0.20, 0.38, 0.56), "LEFT INNER RAIL - SIDE")
        rail.add_patch(Rectangle((0, 0), p.body_depth, 18, fill=False, lw=0.9))
        for start in p.rail_segment_starts:
            length = p.rail_segment_length - 2 * p.rail_lead_in
            rail.add_patch(Rectangle((start + p.rail_lead_in, p.rail_lower_floor_z), length, p.rail_lower_inner_z - p.rail_lower_floor_z, facecolor="#aeb8ba", edgecolor="#273034"))
            rail.add_patch(Rectangle((start + p.rail_lead_in, p.rail_upper_inner_bottom_z), length, p.rail_top_z - p.rail_upper_inner_bottom_z, facecolor="#aeb8ba", edgecolor="#273034"))
        rail.set_xlim(-5, 165); rail.set_ylim(-2, 25)
        _dim_h(rail, 0, p.body_depth, 0, f"DEPTH {p.body_depth:.1f}", -3)
        rail.text(80, 21, f"3 x {p.rail_segment_length:.1f} SEGMENTS | 2 mm LEAD-IN | NOMINAL GAP {p.nominal_rail_clearance:.2f}", ha="center", fontsize=7)
        pdf.savefig(fig)
        plt.close(fig)

        fig, _ = _sheet(p, "R2-102", "FRONT-LOADING SLIDING BASE")
        plan = _view_axis(fig, (0.09, 0.16, 0.48, 0.62), "TOP")
        plan.add_patch(FancyBboxPatch((-p.base_plate_width / 2, p.base_front_y), p.base_plate_width, p.base_depth, boxstyle="round,pad=0,rounding_size=2.2", fill=False, lw=1.2))
        bundle_outer = p.device_center_gap / 2 + p.device_thickness
        outer_guide = bundle_outer + p.device_side_clearance
        guide_front, guide_rear = base_guide_limits(p)
        for x in (-outer_guide, 0, outer_guide):
            plan.plot([x, x], [guide_front, guide_rear], lw=1.2, color="#273034")
        plan.add_patch(Rectangle((-p.rear_stop_width / 2, 154.8), p.rear_stop_width, 3, fill=False, lw=0.9))
        plan.set_xlim(-90, 90); plan.set_ylim(-12, 174)
        _dim_h(plan, -p.tongue_outer_x, p.tongue_outer_x, p.base_front_y, f"TONGUE WIDTH {2 * p.tongue_outer_x:.1f}", -8)
        _dim_v(plan, p.base_front_y, p.base_front_y + p.base_depth, p.tongue_outer_x, f"{p.base_depth:.1f}", 10)

        section = _view_axis(fig, (0.64, 0.27, 0.26, 0.42), "TONGUE SECTION")
        section.add_patch(Rectangle((-p.base_plate_width / 2, 0), p.base_plate_width, p.base_thickness, fill=False, lw=1.0))
        section.add_patch(plt.Polygon(right_tongue_profile(p), fill=False, color="#273034", lw=1.0))
        section.set_xlim(58, 78); section.set_ylim(-2, 16)
        section.text(68, 13, f"45 DEG SELF-SUPPORT\nRAIL GAP {p.nominal_rail_clearance:.2f}", ha="center", fontsize=7)
        pdf.savefig(fig)
        plt.close(fig)

        fig, _ = _sheet(p, "R2-103", "140 MM FRONT FAN BEZEL")
        view = _view_axis(fig, (0.15, 0.14, 0.55, 0.66), "FRONT FACE")
        view.add_patch(FancyBboxPatch((-p.body_width / 2, 0), p.body_width, p.body_height, boxstyle=f"round,pad=0,rounding_size={p.outer_top_radius}", fill=False, lw=1.2))
        view.add_patch(PlotCircle((0, p.body_height / 2), p.front_opening_radius, fill=False, lw=0.9))
        for x, z in fan_hole_locations(p.front_fan_hole_spacing, p.body_height / 2):
            view.add_patch(PlotCircle((x, z), p.front_pin_hole_diameter / 2, fill=False, lw=0.7))
        for x in np.arange(-60, 60.1, p.front_grille_pitch): view.plot([x, x], [22, 144], color="#7b8589", lw=0.5)
        for z in np.arange(23, 143.1, p.front_grille_pitch): view.plot([-61, 61], [z, z], color="#7b8589", lw=0.5)
        view.set_xlim(-95, 105); view.set_ylim(-18, 190)
        _dim_h(view, -p.front_fan_hole_spacing / 2, p.front_fan_hole_spacing / 2, p.body_height / 2 - p.front_fan_hole_spacing / 2, f"HOLE PITCH {p.front_fan_hole_spacing:.1f}", -12)
        _dim_v(view, p.body_height / 2 - p.front_fan_hole_spacing / 2, p.body_height / 2 + p.front_fan_hole_spacing / 2, p.front_fan_hole_spacing / 2, f"{p.front_fan_hole_spacing:.1f}", 12)
        fig.text(0.72, 0.62, f"PIN HOLES: 4 x DIA {p.front_pin_hole_diameter:.1f}\nOPENING: DIA {2 * p.front_opening_radius:.1f}\nGRILLE: {p.front_grille_bar:.1f} BAR / {p.front_grille_pitch:.1f} PITCH\nPROJECTED OPEN: {(1 - p.front_grille_bar / p.front_grille_pitch) ** 2 * 100:.1f}%\nPANEL OFFSET: {p.front_bezel_offset:.1f}", fontsize=8, linespacing=1.7)
        pdf.savefig(fig)
        plt.close(fig)

        fig, _ = _sheet(p, "R2-104", "60 MM FULL-PERIMETER REAR FRAME")
        view = _view_axis(fig, (0.13, 0.14, 0.58, 0.66), "REAR FACE")
        view.add_patch(FancyBboxPatch((-p.body_width / 2, 0), p.body_width, p.body_height, boxstyle=f"round,pad=0,rounding_size={p.outer_top_radius}", fill=False, lw=1.2))
        view.add_patch(FancyBboxPatch((-(p.body_width - 16) / 2, 8), p.body_width - 16, p.body_height - 16, boxstyle="round,pad=0,rounding_size=6", fill=False, lw=0.8))
        view.add_patch(Rectangle((-33, p.body_height / 2 - 33), 66, 66, fill=False, lw=0.9))
        view.add_patch(PlotCircle((0, p.body_height / 2), p.rear_fan_opening_radius, fill=False, lw=0.9))
        for x, z in fan_hole_locations(p.rear_fan_hole_spacing, p.body_height / 2): view.add_patch(PlotCircle((x, z), p.rear_pin_hole_diameter / 2, fill=False, lw=0.7))
        view.set_xlim(-95, 105); view.set_ylim(-18, 190)
        _dim_h(view, -p.rear_fan_hole_spacing / 2, p.rear_fan_hole_spacing / 2, p.body_height / 2 - p.rear_fan_hole_spacing / 2, f"HOLE PITCH {p.rear_fan_hole_spacing:.1f}", -10)
        fig.text(0.72, 0.62, f"PIN HOLES: 4 x DIA {p.rear_pin_hole_diameter:.1f}\nOPENING: DIA {2 * p.rear_fan_opening_radius:.1f}\nFRAME DEPTH: {p.rear_frame_thickness:.1f}\nUPPER/LOWER BYPASS: OPEN\nCONNECTOR ZONES: OPEN", fontsize=8, linespacing=1.7)
        pdf.savefig(fig)
        plt.close(fig)

        fig, _ = _sheet(p, "R2-105", "REVERSIBLE DISPLAY POD AND SIDE BLANK")
        pod = _view_axis(fig, (0.10, 0.20, 0.42, 0.55), "OUTER DISPLAY FACE")
        pod.add_patch(FancyBboxPatch((-p.display_depth / 2, -p.display_height / 2), p.display_depth, p.display_height, boxstyle="round,pad=0,rounding_size=5", fill=False, lw=1.2))
        pod.add_patch(Rectangle((-p.display_screen_width / 2, -p.display_screen_height / 2 + 5), p.display_screen_width, p.display_screen_height, fill=False, lw=0.9))
        pod.set_xlim(-55, 55); pod.set_ylim(-48, 48)
        _dim_h(pod, -p.display_depth / 2, p.display_depth / 2, -p.display_height / 2, f"{p.display_depth:.1f}", -8)
        _dim_v(pod, -p.display_height / 2, p.display_height / 2, p.display_depth / 2, f"{p.display_height:.1f}", 8)

        side = _view_axis(fig, (0.60, 0.22, 0.28, 0.52), "LOCKING INTERFACE")
        side.add_patch(Rectangle((0, -p.display_height / 2), p.display_projection, p.display_height, fill=False, lw=1.0))
        for z in (p.display_hook_z - p.display_center_z,) * 2:
            side.add_patch(Rectangle((-6, z - 4), 6, 8, fill=False, lw=0.8))
        side.annotate("", (-12, 8), (-12, 8 + p.display_lock_travel), arrowprops={"arrowstyle": "<->", "lw": 0.8})
        side.text(-15, 12, f"LOCK {p.display_lock_travel:.1f}", rotation=90, fontsize=7, ha="right")
        side.set_xlim(-25, 30); side.set_ylim(-45, 45)
        fig.text(0.59, 0.18, "PCB outline, mounting holes, and USB-C direction are PROVISIONAL.\nNo encoder opening. Bottom service opening and harness entry retained.", fontsize=8, color="#a33525")
        pdf.savefig(fig)
        plt.close(fig)

        fig, ax = _sheet(p, "R2-900", "MATERIAL, COLOR, AND ASSEMBLY SCHEDULE")
        ax.text(0.0, 0.96, "Color schedule", transform=ax.transAxes, fontsize=12, weight="bold", va="top")
        rows = []
        for key, scheme in COLOR_SCHEMES.items():
            rows.append([key + (" DEFAULT" if key == p.default_color_scheme else " ALT"), scheme["u_cover_and_blank"], scheme["base_front_rear"], scheme["display_pod"]])
        table = ax.table(cellText=rows, colLabels=["SCHEME", "U COVER / BLANK", "BASE / FRONT / REAR", "DISPLAY POD"], bbox=(0.0, 0.69, 1.0, 0.20), cellLoc="left")
        table.auto_set_font_size(False); table.set_fontsize(7.5)
        ax.text(0.0, 0.61, "Material rules", transform=ax.transAxes, fontsize=11, weight="bold")
        rules = [
            "Opaque standard PETG or qualified tough PETG for all structural parts.",
            "No silk, CF-filled, glow, wood-filled, or transparent PETG on rails, tongues, hooks, or latches.",
            "Hex values are digital references; the approved physical coupon controls production color.",
            "Gold rails in the visual model are interface annotations and print in their parent-part color.",
        ]
        for index, line in enumerate(rules): ax.text(0.02, 0.56 - index * 0.045, f"- {line}", transform=ax.transAxes, fontsize=8)
        ax.text(0.0, 0.35, "Assembly order", transform=ax.transAxes, fontsize=11, weight="bold")
        assembly = [
            "1  Validate rail, latch, corner, grille, GB10, fan, and display coupons.",
            "2  Slide base into inverted/empty U cover until the rear hard stop seats.",
            "3  Fit rear fan to frame with four silicone pins; hook and latch rear frame.",
            "4  Install controller harness and selected-side display pod; fit opposite blank.",
            "5  Slide both GB10 units from the front along the hard PETG guides.",
            "6  Fit front fan to bezel; connect quick plug; hook and latch front bezel.",
            "7  Install commercial handle with two M4 bolts and proof-test before carrying.",
        ]
        for index, line in enumerate(assembly): ax.text(0.02, 0.30 - index * 0.038, line, transform=ax.transAxes, fontsize=7.8)
        pdf.savefig(fig)
        plt.close(fig)


def write_release_documents(p: Params, docs_dir: Path, report: dict) -> None:
    docs_dir.mkdir(parents=True, exist_ok=True)
    readme = f"""# Dual GB10 {p.revision} 交付包

本包是已确认 R2 结构的参数化可打印候选版：一体式圆角 U 型罩、前向滑入底板、前置 140 mm 风扇、后置中央 60 mm 风扇、免工具前后面板、左右可换显示仓和两颗 M4 固定的商业提手。

## 放行状态

- CAD/网格/包络/碰撞自动检查：`{report['checks']['cad_generation_passed']}`
- 生产放行：`False`
- 默认配色：`C - Graphite workstation`

生产放行仍需完成 `OPEN_ISSUES.md` 中的实物测量和样件测试。不要跳过 `05_FIT_GAUGES` 直接打印 U 型罩。

## 目录

- `01_STEP`：装配坐标下的可编辑 B-Rep 零件。
- `02_STL`：已摆正到推荐打印方向的打印网格。
- `03_ASSEMBLY`：左右显示仓总装、爆炸和带设备/风扇参考体的 STEP。
- `04_DRAWINGS`：PDF 图册以及实际 B-Rep 投影的 DXF/SVG。
- `05_FIT_GAUGES`：滑轨、卡扣、圆角、格栅、双机、风扇和显示窗口样件。
- `06_DOCS`：BOM、打印、装配、参数和未关闭事项。
- `07_SOURCE`：Build123d 源码、测试和锁定依赖。
- `08_REPORTS`：验证结果、发布清单和 SHA-256。

## 关键规则

所有尺寸单位为 mm。不要在切片软件中缩放 STL；测量后修改 `07_SOURCE/generate_r2.py` 中的 `Params` 并重新生成。两台 GB10 仍使用各自原装 240 W 电源，温控器不得接入或拆分 48 V / 5 A EPR 输入。
"""
    (docs_dir / "README_CN.md").write_text(readme, encoding="utf-8")

    printing = f"""# 打印与表面加工说明

## 推荐设置

- 材料：不透明标准 PETG 或经过样件验证的 Tough PETG。
- 层高：0.20 mm；喷嘴：0.4 或 0.6 mm。
- 壁线：至少 4；顶/底层：至少 5。
- 局部加强区：25-35% gyroid；卡扣和导轨优先依靠壁线，不依靠稀疏填充。
- U 型罩外顶面朝下；底板平放；前后面板外表面朝下；显示仓外表面朝下。
- U 型罩使用 {p.u_cover_brim:.0f} mm brim（允许 8-10 mm），不使用 raft；主体不得依赖全局支撑。
- 每卷实际耗材都要重新校准流量、温度和滑轨/卡扣配合。

## 配色

| 方案 | 状态 | U 型罩/侧封片 | 底板/前面板/背框 | 显示仓 |
| --- | --- | --- | --- | --- |
| A | 备选 | 雾灰 `#D9DDDA` | 石墨 `#292F31` | 暗铜橙 `#A94D2D` |
| B | 备选 | 冷白 `#ECEFED` | 炭黑 `#1D2224` | NVIDIA 绿参考 `#76B900` |
| C | **默认** | 深石墨 `#343A3C` | 哑黑 `#171B1D` | 钛灰 `#8B9698` |

Hex 仅用于数字外观参考，以打印色样为验收依据。金色导轨是 Three.js 的接口标识，不是独立换色区。

## 禁用材料

滑轨、舌边、挂钩和悬臂卡扣不得使用 Silk、碳纤填充、夜光、木粉或透明 PETG。显示仓可以在独立配合样件通过后使用装饰性 PETG。

## 切片放行检查

1. 最大尺寸不得超过 {p.print_limit:.0f} mm 打印空间。
2. 结构悬垂不大于 45 度；不得自动生成堵塞滑轨和卡扣窗口的支撑。
3. 对照 `08_REPORTS/validation.json` 核查热床接触面积和离床向下水平面面积；单件总量不得超过 25 mm2，且任一桥接跨度不得超过 12 mm。
4. 每个 STL 保持 100% 比例；禁止用整体缩放补偿耗材收缩。
"""
    (docs_dir / "PRINTING_AND_FINISHING.md").write_text(printing, encoding="utf-8")

    assembly = f"""# 装配与维护说明

1. 先打印并验证 `05_FIT_GAUGES` 全部样件。
2. 空壳状态下，将底板从正面沿两侧连续舌边滑入 U 型罩的三段捕获轨，直至后止挡。
3. 用四个硅胶拉钉把 60 mm 风扇固定到全周背框；上挂钩先入位，再逐个压入下卡扣。
4. 安装控制器线束；显示仓挂入选定侧后下移 {p.display_lock_travel:.1f} mm 锁定，另一侧安装封片。
5. 两台 GB10 从正面沿硬质圆角导向筋推入，后接口朝背框，前格栅朝 140 mm 风扇。
6. 用四个硅胶拉钉将 140 mm 风扇装在前面板内侧，连接防呆快插并保留 {p.service_opening_travel:.0f} mm 服务余量。
7. 前面板先挂上方两个挂钩，再逐个压入下方卡扣；前面板同时阻止底板前移。
8. 用两颗 M4 安装商业提手。完成 12 kg、60 秒静载、10 次受控提放和 6 kg、24 小时悬挂蠕变试验后才允许提起整机。

维护前断开风扇快插。拆背框前允许先拔除 GB10 后部线缆；不要拉扯线缆强行打开面板。
"""
    (docs_dir / "ASSEMBLY_AND_SERVICE.md").write_text(assembly, encoding="utf-8")

    open_issues = """# 未关闭的生产放行事项

| Gate | 必需证据 | 当前状态 |
| --- | --- | --- |
| G1 双机尺寸 | 两台 GB10 卡尺记录、圆角/脚垫记录、双机配合规通过 | 未测 |
| G2 前风扇 | 140 mm 实物孔距、厚度、拉钉长度和最小稳定 PWM | 未测 |
| G3 后风扇 | 60 mm 实物孔距、厚度、拉钉长度、针脚和最小稳定 PWM | 未测 |
| G4 显示 PCB | PCB 外形、屏幕、USB-C、安装孔和电缆方向 | 未测 |
| G5 提手 | 最终插入件/螺栓/垫片/扭矩锁定后：12 kg x 60 s 挠度 <=2 mm、10 次提放、6 kg x 24 h，卸载残余 <=0.5 mm | 未测 |
| G6 后部线缆 | USB-C、HDMI、网线、QSFP 全部安装后的弯曲半径和排风空间 | 未测 |
| G7 热浸 | 30+/-2 C 环境双机满载 2 h：无降频/关机，GPU <=85 C、PETG <=60 C；失败则改 80 mm 或双 60 mm 后排风 | 未测 |
| G8 控制器供电 | GB10 USB-C 连续 5 V 输出和双风扇启动电流 | 未测 |
| G9 全尺寸干装 | 量产方向 U 罩/底板：154 mm 峰值滑入力 <=40 N、三站 Z 间隙 <=0.8 mm、后挡间隙 <=0.5 mm，双机可单人推入/取出 | 未测 |
| G10 显示仓保持 | USB-C 线缆插合状态 30 N 外拉 5 次；无裂纹/脱锁，残余位移 <=0.2 mm，仍可 7 mm 解锁和 4.5 mm 按压释放 | 未测 |
| G11 切片边界 | U 罩加 8-10 mm brim 后避开打印机 purge/prime/skirt 保留区 | 未测 |

CAD 自动检查通过不等于这些实物 Gate 已关闭。
"""
    (docs_dir / "OPEN_ISSUES.md").write_text(open_issues, encoding="utf-8")
    (docs_dir / "PARAMETERS.json").write_text(json.dumps(asdict(p), indent=2), encoding="utf-8")

    bom_rows = [
        ("PRINT", "R2-101 U cover", 1, "Opaque PETG", "C: deep graphite", "Print after coupons"),
        ("PRINT", "R2-102 sliding base", 1, "Opaque PETG", "C: matte black", "No foam"),
        ("PRINT", "R2-103 front 140 bezel", 1, "Opaque PETG", "C: matte black", "Integral grille/latches"),
        ("PRINT", "R2-104 rear 60 frame", 1, "Opaque PETG", "C: matte black", "Integral hooks/latches"),
        ("PRINT", "Display pod, selected side", 1, "PETG", "C: titanium gray", "PCB dimensions pending"),
        ("PRINT", "Display blank, opposite side", 1, "Opaque PETG", "C: deep graphite", "Mirror interface"),
        ("HARDWARE", "140 x 140 x 25 PWM fan", 1, "12 V, 4-wire", "Supplied", "Hole/pin check required"),
        ("HARDWARE", "60 x 60 x 15 PWM fan", 1, "Delta AFB0612LB candidate", "Purchased black", "Hole/pin check required"),
        ("HARDWARE", "Silicone fan pull pin", 8, "Fan-compatible", "Supplied finish", "Length check required"),
        ("HARDWARE", "Commercial top handle", 1, f"{p.handle_anchor_rear_y - p.handle_anchor_front_y:.1f} mm nominal pitch", "Black", "Physical choice pending"),
        ("HARDWARE", "M4 heat-set insert", 2, f"Pilot {p.handle_insert_pilot:.1f} mm nominal", "Brass", "Match purchased insert"),
        ("HARDWARE", "M4 bolt and broad washer", 2, "Handle-compatible", "Metal", "Only body screws"),
        ("ELECTRONICS", "ESP32-S3-Touch-LCD-2.4", 1, "N16R8 candidate", "Module", "PCB outline pending"),
        ("ELECTRONICS", "TPS61088 5 V to 12 V module", 1, "12 V fixed candidate", "Module", "Load test required"),
        ("ELECTRONICS", "10K B3950 NTC probe", 2, "Wired", "Module", "Inlet and exhaust"),
        ("ELECTRONICS", "Keyed fan quick connector", 2, "4-wire plus separate tach", "Harness", "35 mm service loop"),
    ]
    with (docs_dir / "BOM.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["CATEGORY", "ITEM", "QTY", "SPEC", "FINISH", "STATUS_NOTES"])
        writer.writerows(bom_rows)


def write_sha256(root: Path, destination: Path) -> None:
    lines: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path == destination:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(root).as_posix()}")
    destination.write_text("\n".join(lines) + "\n", encoding="ascii")


def generate(p: Params, output_dir: Path, pdf_path: Path) -> dict:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    step_dir = output_dir / "01_STEP"
    stl_dir = output_dir / "02_STL"
    assembly_dir = output_dir / "03_ASSEMBLY"
    drawing_dir = output_dir / "04_DRAWINGS"
    projection_dir = drawing_dir / "DXF_SVG"
    gauge_dir = output_dir / "05_FIT_GAUGES"
    docs_dir = output_dir / "06_DOCS"
    source_dir = output_dir / "07_SOURCE"
    report_dir = output_dir / "08_REPORTS"
    preview_dir = output_dir / "PREVIEWS"
    for directory in (step_dir, stl_dir, assembly_dir, projection_dir, gauge_dir, docs_dir, source_dir, report_dir, preview_dir):
        directory.mkdir(parents=True, exist_ok=True)

    cover = build_u_cover(p)
    base = build_sliding_base(p)
    front = build_front_bezel(p)
    rear = build_rear_frame(p)
    pod_left = build_display_pod(p, -1)
    pod_right = build_display_pod(p, 1)
    blank_left = build_display_blank(p, -1)
    blank_right = build_display_blank(p, 1)

    parts = [
        PartSpec("R2-101", "u_cover", cover, oriented(cover, Axis.X, 180), 1, "Opaque PETG", "U cover / blank", "Exterior top face down; 8-10 mm brim; no global support.", "One-piece rounded top and side shell, paired segmented capture rails, display slots, and handle load ribs."),
        PartSpec("R2-102", "sliding_base", base, oriented(base), 1, "Opaque PETG", "Base / front / rear", "Print flat on base underside.", "Continuous captured tongues, rounded GB10 guides, rear stop, latch channels, and harness routes."),
        PartSpec("R2-103", "front_140_bezel", front, oriented(front, Axis.X, 90), 1, "Opaque PETG", "Base / front / rear", "Exterior front face down.", "140 mm grille, silicone-pin holes, long upper hooks, and sequential lower latches."),
        PartSpec("R2-104", "rear_60_frame", rear, oriented(rear, Axis.X, -90), 1, "Opaque PETG", "Base / front / rear", "Exterior rear face down.", "Full perimeter frame, central 60 mm mount, passive bypass, hooks, and latches."),
        PartSpec("R2-105", "display_pod_left", pod_left, oriented(pod_left, Axis.Y, -90), 1, "PETG", "Display pod", "Outer display face down.", "Left-side pod; PCB and USB-C dimensions remain provisional."),
        PartSpec("R2-106", "display_pod_right", pod_right, oriented(pod_right, Axis.Y, 90), 1, "PETG", "Display pod", "Outer display face down.", "Right-side mirror pod; print only for right-display configuration."),
        PartSpec("R2-107", "display_blank_left", blank_left, oriented(blank_left, Axis.Y, -90), 1, "Opaque PETG", "U cover / blank", "Outer face down.", "Use when the display pod is on the right."),
        PartSpec("R2-108", "display_blank_right", blank_right, oriented(blank_right, Axis.Y, 90), 1, "Opaque PETG", "U cover / blank", "Outer face down.", "Use when the display pod is on the left."),
    ]

    report: dict = {
        "release": RELEASE_ID,
        "revision": p.revision,
        "units": p.units,
        "parameters": asdict(p),
        "parts": [],
        "fit_gauges": [],
        "collisions_mm3": {},
        "warnings": [
            "Physical GB10 dimensions and manufacturing spread are not yet measured.",
            "Fan hole patterns and silicone pull-pin lengths are provisional.",
            "Display PCB outline, screen position, mounting holes, and USB-C direction are provisional.",
            "Commercial handle pitch and heat-set insert dimensions must match purchased hardware.",
            "Rear cable bend clearance and GB10 USB-C source capability require bench verification.",
        ],
    }

    oversized: list[str] = []
    invalid: list[str] = []
    multi_solid: list[str] = []
    non_manifold: list[str] = []
    insufficient_bed_contact: list[str] = []
    unsupported_horizontal: list[str] = []
    for spec in parts:
        basename = f"{spec.part_number}_{spec.name}"
        stl_path = stl_dir / f"{basename}.stl"
        step_path = step_dir / f"{basename}.step"
        export_stl(spec.print_shape, stl_path, tolerance=0.03, angular_tolerance=0.16)
        clean_binary_stl(stl_path)
        export_step(spec.assembly_shape, step_path)
        mesh = stl_mesh_record(stl_path)
        printability = stl_printability_record(stl_path)
        bbox = bbox_record(spec.print_shape)
        if any(float(value) > p.print_limit + 0.01 for value in bbox["size"]):
            oversized.append(spec.name)
        if not spec.print_shape.is_valid():
            invalid.append(spec.name)
        if len(spec.print_shape.solids()) != 1:
            multi_solid.append(spec.name)
        if mesh["non_manifold_edges"]:
            non_manifold.append(spec.name)
        if printability["bed_contact_area_mm2"] < 100.0:
            insufficient_bed_contact.append(spec.name)
        if printability["unsupported_downward_horizontal_area_mm2"] > 25.0:
            unsupported_horizontal.append(spec.name)
        report["parts"].append({
            "part_number": spec.part_number,
            "name": spec.name,
            "quantity": spec.quantity,
            "material": spec.material,
            "color_role": spec.color_role,
            "print_orientation": spec.print_orientation,
            "notes": spec.notes,
            "step": step_path.relative_to(output_dir).as_posix(),
            "stl": stl_path.relative_to(output_dir).as_posix(),
            "valid_brep": bool(spec.print_shape.is_valid()),
            "solids": len(spec.print_shape.solids()),
            "volume_mm3": round(shape_volume(spec.print_shape), 2),
            "solid_petg_mass_g": round(shape_volume(spec.print_shape) / 1000 * 1.27, 1),
            "bbox": bbox,
            "mesh": mesh,
            "printability": printability,
        })

    projection_views = {
        "R2-101_u_cover": (cover, "front"),
        "R2-102_sliding_base": (base, "top"),
        "R2-103_front_140_bezel": (front, "front"),
        "R2-104_rear_60_frame": (rear, "rear"),
        "R2-105_display_pod_left": (pod_left, "left"),
        "R2-108_display_blank_right": (blank_right, "right"),
    }
    for name, (shape, view) in projection_views.items():
        export_projection(shape, view, projection_dir / f"{name}_{view}.dxf", projection_dir / f"{name}_{view}.svg", p)

    corner = cover & box_at((34.0, 24.0, 34.0), (p.body_width / 2 - 17.0, 12.0, p.body_height - 17.0))
    gauges = [
        GaugeSpec("G01_gb10_pair_fit", build_pair_fit_gauge(p), "Verify both device thicknesses, center divider, and 0.8 mm side clearance."),
        GaugeSpec("G02_fan140_pin_pattern", build_fan_mount_gauge(p.front_fan_size, p.front_fan_hole_spacing, p.front_pin_hole_diameter), "Verify 140 mm frame, 124.5 mm provisional pitch, and pull-pin holes."),
        GaugeSpec("G03_fan60_pin_pattern", build_fan_mount_gauge(p.rear_fan_size, p.rear_fan_hole_spacing, p.rear_pin_hole_diameter), "Verify 60 mm frame, 50 mm provisional pitch, and pull-pin holes."),
        GaugeSpec("G04_grille_open_area", build_grille_coupon(p), "Verify stiffness, surface, bridge quality, and projected open area."),
        GaugeSpec("G05_rounded_u_corner", corner, "Verify 12 mm outer corner, 3.6 mm wall, and exterior finish."),
        GaugeSpec("G06_display_window", build_display_window_gauge(p), "Verify physical screen/window envelope before freezing the pod."),
        GaugeSpec("G07_rail_cover_030_040_050", build_rail_coupon_cover(p), "Receiver half for three rail-clearance lanes."),
        GaugeSpec("G08_rail_slider_030_040_050", build_rail_coupon_slider(p), "Slider half with 0.30, 0.40, and 0.50 mm nominal lanes."),
        GaugeSpec("G09_front_latch_panel", build_latch_coupon_panel(p, True), "Production-derived front latch; cycle-test flexure and retaining shoulder."),
        GaugeSpec("G10_front_latch_receiver", build_latch_coupon_receiver(p, True), "Production-derived front receiver pocket and throat."),
        GaugeSpec("G11_rear_latch_panel", build_latch_coupon_panel(p, False), "Production-derived rear latch; cycle-test flexure and retaining shoulder."),
        GaugeSpec("G12_rear_latch_receiver", build_latch_coupon_receiver(p, False), "Production-derived rear receiver pocket and throat."),
        GaugeSpec("G13_display_lock_cover", build_display_coupon_cover(p), "Production-derived 7 mm key path, entry, and lower latch receiver."),
        GaugeSpec("G14_display_lock_pod", build_display_coupon_pod(p), "Production-derived top key and lower display latch."),
    ]
    for gauge in gauges:
        shape = oriented(gauge.shape)
        stl_path = gauge_dir / f"{gauge.name}.stl"
        step_path = gauge_dir / f"{gauge.name}.step"
        export_stl(shape, stl_path, tolerance=0.03, angular_tolerance=0.16)
        clean_binary_stl(stl_path)
        export_step(shape, step_path)
        mesh = stl_mesh_record(stl_path)
        if not shape.is_valid(): invalid.append(gauge.name)
        if len(shape.solids()) != 1: multi_solid.append(gauge.name)
        if mesh["non_manifold_edges"]: non_manifold.append(gauge.name)
        report["fit_gauges"].append({
            "name": gauge.name,
            "notes": gauge.notes,
            "valid_brep": bool(shape.is_valid()),
            "solids": len(shape.solids()),
            "bbox": bbox_record(shape),
            "mesh": mesh,
            "step": step_path.relative_to(output_dir).as_posix(),
            "stl": stl_path.relative_to(output_dir).as_posix(),
        })

    handle = build_handle_reference(p)
    devices = build_device_references(p)
    fans = build_fan_references(p)
    printed_left = [cover, base, front, rear, pod_left, blank_right]
    printed_right = [cover, base, front, rear, pod_right, blank_left]
    assembly_left = Compound(children=[*printed_left, handle])
    assembly_right = Compound(children=[*printed_right, handle])
    fit_reference = Compound(children=[*printed_left, handle, *devices, *fans])
    assembly_left_path = assembly_dir / "R2_complete_left_display.step"
    assembly_right_path = assembly_dir / "R2_complete_right_display.step"
    fit_reference_path = assembly_dir / "R2_fit_reference_devices_fans.step"
    export_step(assembly_left, assembly_left_path)
    export_step(assembly_right, assembly_right_path)
    export_step(fit_reference, fit_reference_path)
    preview_stl = assembly_dir / "R2_complete_left_display_preview.stl"
    export_stl(assembly_left, preview_stl, tolerance=0.04, angular_tolerance=0.2)
    clean_binary_stl(preview_stl)
    fit_preview_stl = assembly_dir / "R2_fit_reference_devices_fans_preview.stl"
    export_stl(fit_reference, fit_preview_stl, tolerance=0.04, angular_tolerance=0.2)
    clean_binary_stl(fit_preview_stl)

    exploded = Compound(children=[
        cover.translate((0, 0, 72)),
        base.translate((0, 0, -30)),
        front.translate((0, -62, 0)),
        rear.translate((0, 55, 0)),
        pod_left.translate((-42, 0, 0)),
        blank_right.translate((25, 0, 0)),
        handle.translate((0, 0, 118)),
    ])
    export_step(exploded, assembly_dir / "R2_exploded_left_display.step")
    exploded_stl = assembly_dir / "R2_exploded_left_display_preview.stl"
    export_stl(exploded, exploded_stl, tolerance=0.04, angular_tolerance=0.2)
    clean_binary_stl(exploded_stl)

    collision_shapes = {
        "u_cover": cover,
        "sliding_base": base,
        "front_bezel": front,
        "rear_frame": rear,
        "display_pod_left": pod_left,
        "display_blank_right": blank_right,
    }
    part_pairs = [
        ("u_cover", "sliding_base"),
        ("u_cover", "front_bezel"),
        ("sliding_base", "front_bezel"),
        ("u_cover", "rear_frame"),
        ("sliding_base", "rear_frame"),
        ("u_cover", "display_pod_left"),
        ("u_cover", "display_blank_right"),
    ]
    report["collisions_mm3"]["printed_parts"] = {
        f"{first}__{second}": round(intersection_volume(collision_shapes[first], collision_shapes[second]), 5)
        for first, second in part_pairs
    }
    report["collisions_mm3"]["devices"] = {
        f"gb10_{index + 1}__{name}": round(intersection_volume(device, shape), 5)
        for index, device in enumerate(devices)
        for name, shape in collision_shapes.items()
    }
    report["collisions_mm3"]["fans"] = {
        f"fan_{index + 1}__{name}": round(intersection_volume(fan, shape), 5)
        for index, fan in enumerate(fans)
        for name, shape in collision_shapes.items()
    }

    front_open_area = (1 - p.front_grille_bar / p.front_grille_pitch) ** 2
    collision_values = [
        value
        for group in report["collisions_mm3"].values()
        for value in group.values()
    ]
    report["checks"] = {
        "all_parts_valid": not invalid,
        "all_parts_single_solid": not multi_solid,
        "all_parts_within_180mm": not oversized,
        "all_meshes_closed": not non_manifold,
        "all_parts_have_at_least_100mm2_bed_contact": not insufficient_bed_contact,
        "no_large_downward_horizontal_surfaces_above_bed": not unsupported_horizontal,
        "device_and_assembly_collision_free": all(value <= 0.01 for value in collision_values),
        "front_grille_projected_open_area": round(front_open_area, 4),
        "front_grille_at_least_75_percent": front_open_area >= 0.75,
        "body_panel_screw_count": 0,
        "structural_handle_bolt_count": 2,
        "cad_generation_passed": False,
        "production_released": False,
        "invalid": invalid,
        "multi_solid": multi_solid,
        "oversized": oversized,
        "non_manifold": non_manifold,
        "insufficient_bed_contact": insufficient_bed_contact,
        "unsupported_horizontal": unsupported_horizontal,
    }
    report["checks"]["cad_generation_passed"] = all([
        report["checks"]["all_parts_valid"],
        report["checks"]["all_parts_single_solid"],
        report["checks"]["all_parts_within_180mm"],
        report["checks"]["all_meshes_closed"],
        report["checks"]["all_parts_have_at_least_100mm2_bed_contact"],
        report["checks"]["no_large_downward_horizontal_surfaces_above_bed"],
        report["checks"]["device_and_assembly_collision_free"],
        report["checks"]["front_grille_at_least_75_percent"],
    ])

    report_path = report_dir / "validation.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    generate_engineering_drawings(p, pdf_path)
    shutil.copy2(pdf_path, drawing_dir / pdf_path.name)
    write_release_documents(p, docs_dir, report)
    shutil.copy2(ROOT / "planning" / "02-working" / "enclosure-r2-manufacturability-review.md", docs_dir / "R2_MANUFACTURABILITY_REVIEW.md")
    shutil.copy2(ROOT / "planning" / "02-working" / "enclosure-r2.1-remediation.md", docs_dir / "R2.1_REMEDIATION.md")
    shutil.copy2(ROOT / "planning" / "02-working" / "enclosure-r2.1-claude-review.md", docs_dir / "R2.1_CLAUDE_REVIEW.md")
    shutil.copy2(ROOT / "planning" / "03-core" / "confirmed-constraints.md", docs_dir / "CONFIRMED_CONSTRAINTS.md")

    source_files = [
        Path(__file__),
        Path(__file__).with_name("test_generate_r2.py"),
        ROOT / "pyproject.toml",
        ROOT / "uv.lock",
        ROOT / "site" / "r2-assembly.html",
        ROOT / "site" / "r2.html",
    ]
    for source in source_files:
        if source.exists():
            shutil.copy2(source, source_dir / source.name)

    render_stl_preview(fit_preview_stl, preview_dir / "R2_complete_C_left_display.png", elev=24, azim=-128)
    render_stl_preview(exploded_stl, preview_dir / "R2_exploded_left_display.png", elev=24, azim=-128)

    manifest = {
        "release": RELEASE_ID,
        "revision": p.revision,
        "status": "release candidate - physical gates open",
        "default_color_scheme": p.default_color_scheme,
        "color_schemes": COLOR_SCHEMES,
        "units": p.units,
        "parts": report["parts"],
        "fit_gauges": report["fit_gauges"],
        "assemblies": [path.relative_to(output_dir).as_posix() for path in sorted(assembly_dir.glob("*.step"))],
        "engineering_drawings": (drawing_dir / pdf_path.name).relative_to(output_dir).as_posix(),
        "validation": report_path.relative_to(output_dir).as_posix(),
        "checks": report["checks"],
    }
    manifest_path = report_dir / "release_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_sha256(output_dir, report_dir / "SHA256SUMS.txt")

    zip_path = output_dir.parent / f"{RELEASE_ID}-delivery.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(output_dir.rglob("*")):
            if path.is_file():
                archive.write(path, Path(RELEASE_ID) / path.relative_to(output_dir))
    report["delivery_zip"] = str(zip_path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    args = parser.parse_args()
    report = generate(Params(), args.output.resolve(), args.pdf.resolve())
    print(json.dumps(report["checks"], indent=2))
    print(f"Generated R2 delivery in {args.output.resolve()}")
    print(f"Generated engineering drawings at {args.pdf.resolve()}")
    print(f"Generated delivery ZIP at {report['delivery_zip']}")


if __name__ == "__main__":
    main()
