#!/usr/bin/env python3
"""Generate the approved dual-GB10 A+ enclosure prototype.

Coordinate system:
  X: left/right, Y: front/rear, Z: bottom/top.

The generated geometry is a fit-checkable engineering prototype. Exact GB10
corner radii, rear vent boundaries, display PCB dimensions, and fan hole
patterns remain parameters because the physical hardware still needs caliper
verification before a full production print.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from build123d import Align, Axis, Box, Compound, Cylinder, Pos, Shape, export_step, export_stl


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "output" / "cad-a-plus"


@dataclass(frozen=True)
class Params:
    # Approved system envelope. Width excludes the selected side display pod.
    body_width: float = 152.0
    main_depth: float = 158.0
    front_module_depth: float = 35.0
    rear_module_depth: float = 25.0
    body_height: float = 166.0

    # Printed shell.
    wall: float = 5.0
    base_thickness: float = 6.0
    lid_thickness: float = 4.0
    shell_height_without_lid: float = 162.0
    fit_clearance: float = 0.40

    # GB10 fit. The official paper rounds thickness to 51 mm; the user measured
    # 50.5 mm, so that value remains the default until the supplied units are
    # checked with calipers.
    device_thickness: float = 50.5
    device_depth: float = 150.0
    device_height: float = 150.0
    device_side_clearance: float = 0.80
    device_center_gap: float = 4.0
    device_front_clearance: float = 4.2
    device_bottom_z: float = 7.0

    # Supplied front fan. Standard hole spacing is a provisional default.
    front_fan_size: float = 140.0
    front_fan_thickness: float = 25.0
    front_fan_hole_spacing: float = 124.5
    front_fan_hole_diameter: float = 4.6

    # A+ rear assist fan. Confirm the selected fan before final production.
    rear_fan_size: float = 60.0
    rear_fan_thickness: float = 15.0
    rear_fan_hole_spacing: float = 50.0
    rear_fan_hole_diameter: float = 4.2

    # Side display pod, based on the approved visual envelope.
    display_pod_depth: float = 78.0
    display_pod_height: float = 70.0
    display_pod_projection: float = 12.0
    display_screen_width: float = 58.0
    display_screen_height: float = 42.0
    display_encoder_hole: float = 7.0

    # Handle load path and removable top.
    handle_anchor_front_y: float = 28.0
    handle_anchor_rear_y: float = 122.0
    handle_bolt_clearance: float = 4.5
    handle_insert_pilot: float = 5.6
    handle_boss_diameter: float = 14.0
    handle_strap_width: float = 24.0
    handle_strap_length: float = 176.0
    handle_strap_thickness: float = 4.0

    # Replaceable TPU contact points.
    tpu_pad_diameter: float = 12.0
    tpu_pad_height: float = 1.2


@dataclass
class PartSpec:
    name: str
    assembly_shape: Shape
    print_shape: Shape
    quantity: int
    material: str
    print_orientation: str
    notes: str


def box_at(size: tuple[float, float, float], center: tuple[float, float, float]) -> Shape:
    return Pos(*center) * Box(*size)


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


def device_centers(p: Params) -> tuple[float, float]:
    offset = p.device_center_gap / 2 + p.device_thickness / 2
    return -offset, offset


def build_main_shell(p: Params) -> Shape:
    w = p.body_width
    d = p.main_depth
    h = p.shell_height_without_lid
    side_x = (w - p.wall) / 2
    inner_edge = w / 2 - p.wall

    base = box_at((w, d, p.base_thickness), (0, d / 2, p.base_thickness / 2))
    left_wall = box_at((p.wall, d, h), (-side_x, d / 2, h / 2))
    right_wall = box_at((p.wall, d, h), (side_x, d / 2, h / 2))

    # The inward flanges support the two removable handle crossbars. They stop
    # at Z=158, leaving room for the crossbars and lid above the GB10 units.
    flange_width = 7.5
    flange_z = 156.0
    flanges = [
        box_at((flange_width, d, 4.0), (-inner_edge + flange_width / 2, d / 2, flange_z)),
        box_at((flange_width, d, 4.0), (inner_edge - flange_width / 2, d / 2, flange_z)),
    ]

    left_center, right_center = device_centers(p)
    bundle_outer = p.device_center_gap / 2 + p.device_thickness
    guide_inner_face = bundle_outer + p.device_side_clearance
    guide_width = 2.5
    guide_z = p.base_thickness + 3.0
    guides = [
        box_at((p.device_center_gap - 1.0, p.device_depth, 6.0), (0, p.device_front_clearance + p.device_depth / 2, guide_z)),
        box_at((guide_width, p.device_depth, 6.0), (guide_inner_face + guide_width / 2, p.device_front_clearance + p.device_depth / 2, guide_z)),
        box_at((guide_width, p.device_depth, 6.0), (-guide_inner_face - guide_width / 2, p.device_front_clearance + p.device_depth / 2, guide_z)),
    ]

    # Rear module tongues are rooted into top and bottom bridges. The tongues
    # remain outside the device volume and slide into the rear module channels.
    rear_y = p.main_depth - 1.7
    rear_mounts = [
        box_at((64.0, 3.4, 6.0), (0, rear_y, 9.0)),
        box_at((64.0, 3.4, 6.0), (0, rear_y, 159.0)),
        box_at((2.4, 3.0, 144.0), (-30.0, p.main_depth - 1.5, 84.0)),
        box_at((2.4, 3.0, 144.0), (30.0, p.main_depth - 1.5, 84.0)),
    ]

    # Identical external rails on both sides let one display pod and one blank
    # cover swap sides without reprinting the load-bearing shell.
    display_rails = []
    rail_x = w / 2 + 1.5
    for side in (-1, 1):
        for y in (12.0, 72.0):
            display_rails.append(box_at((3.0, 6.0, 50.0), (side * rail_x, y, 111.0)))

    shell = union([base, left_wall, right_wall, *flanges, *guides, *rear_mounts, *display_rails])

    cutters: list[Shape] = []
    # Shallow TPU pad pockets under each device.
    for x in (left_center, right_center):
        for y in (28.0, 132.0):
            cutters.append(cyl_z(p.tpu_pad_diameter / 2 + 0.15, 1.05, (x, y, p.base_thickness - 0.525)))

    # Reversible display/controller cable slots.
    for side in (-1, 1):
        cutters.append(box_at((8.0, 14.0, 20.0), (side * side_x, 42.0, 91.0)))

    # The front tongue enters the top flange without colliding with it.
    cutters.append(box_at((141.5, 4.4, 4.6), (0, 2.0, 157.7)))
    return cut(shell, cutters)


def build_front_module(p: Params) -> Shape:
    w = p.body_width
    depth = p.front_module_depth
    h = p.body_height
    y_center = -depth / 2
    side_beam = p.wall
    border = 6.0

    structural = [
        box_at((side_beam, depth, h), (-(w - side_beam) / 2, y_center, h / 2)),
        box_at((side_beam, depth, h), ((w - side_beam) / 2, y_center, h / 2)),
        box_at((w - 2 * side_beam, depth, border), (0, y_center, border / 2)),
        box_at((w - 2 * side_beam, depth, border), (0, y_center, h - border / 2)),
    ]

    # Rear fan mounting web. The 134 mm opening keeps useful material around
    # provisional standard 140 mm mounting holes.
    mount_web = box_at((146.0, 4.0, 146.0), (0, -2.0, h / 2))
    mount_web = mount_web - cyl_y(67.0, 7.0, (0, -2.0, h / 2))
    half_spacing = p.front_fan_hole_spacing / 2
    for x in (-half_spacing, half_spacing):
        for z in (h / 2 - half_spacing, h / 2 + half_spacing):
            mount_web = mount_web - cyl_y(p.front_fan_hole_diameter / 2, 8.0, (x, -2.0, z))

    # Integrated low-obstruction front guard.
    guard_slats = [
        box_at((142.0, 2.6, 2.2), (0, -33.0, z))
        for z in np.linspace(14.0, h - 14.0, 18)
    ]

    # A 4 mm deep perimeter tongue fits inside the U-shell. The top tongue is
    # captured by the lid; no separate enclosure screw is required.
    tongue_y = 1.95
    tongue_depth = 4.1
    tongue_outer_w = 141.2
    tongue_side = 3.2
    tongue = [
        box_at((tongue_side, tongue_depth, 144.0), (-(tongue_outer_w - tongue_side) / 2, tongue_y, 81.0)),
        box_at((tongue_side, tongue_depth, 144.0), ((tongue_outer_w - tongue_side) / 2, tongue_y, 81.0)),
        box_at((tongue_outer_w, tongue_depth, 4.0), (0, tongue_y, 8.4)),
        box_at((tongue_outer_w, tongue_depth, 4.0), (0, tongue_y, 157.6)),
    ]
    return union([*structural, mount_web, *guard_slats, *tongue])


def build_rear_module(p: Params) -> Shape:
    start_y = p.main_depth - 2.0
    # The side rails span the full 25 mm protrusion and overlap the main shell
    # by 2 mm. This joins the rear guard to the mounting frame as one solid.
    frame_depth = p.rear_module_depth + 2.0
    frame_center_y = start_y + frame_depth / 2
    z_center = p.body_height / 2
    frame = [
        box_at((4.0, frame_depth, 150.0), (-30.0, frame_center_y, z_center)),
        box_at((4.0, frame_depth, 150.0), (30.0, frame_center_y, z_center)),
        box_at((64.0, frame_depth, 4.0), (0, frame_center_y, 10.0)),
        box_at((64.0, frame_depth, 4.0), (0, frame_center_y, 156.0)),
    ]

    # Central fan mounting ring; the upper and lower zones remain completely
    # open as passive exhaust bypasses.
    fan_y = p.main_depth + 9.5
    fan_ring = box_at((64.0, 4.0, 64.0), (0, fan_y, z_center))
    fan_ring = fan_ring - cyl_y(27.0, 7.0, (0, fan_y, z_center))
    half_spacing = p.rear_fan_hole_spacing / 2
    for x in (-half_spacing, half_spacing):
        for z in (z_center - half_spacing, z_center + half_spacing):
            fan_ring = fan_ring - cyl_y(p.rear_fan_hole_diameter / 2, 8.0, (x, fan_y, z))

    # Rear guard at the maximum approved depth.
    guard_y = p.main_depth + p.rear_module_depth - 1.2
    guard = [
        box_at((64.0, 2.4, 4.0), (0, guard_y, z_center - 30.0)),
        box_at((64.0, 2.4, 4.0), (0, guard_y, z_center + 30.0)),
        box_at((4.0, 2.4, 56.0), (-30.0, guard_y, z_center)),
        box_at((4.0, 2.4, 56.0), (30.0, guard_y, z_center)),
    ]
    for z in np.linspace(z_center - 22.0, z_center + 22.0, 6):
        guard.append(box_at((56.0, 2.0, 1.8), (0, guard_y - 1.0, float(z))))

    module = union([*frame, fan_ring, *guard])
    # Rear-facing channels accept the U-shell tongues while retaining the
    # module around them.
    grooves = [
        box_at((2.8, 9.0, 146.0), (-30.0, p.main_depth + 2.0, 84.0)),
        box_at((2.8, 9.0, 146.0), (30.0, p.main_depth + 2.0, 84.0)),
        box_at((64.8, 2.5, 6.4), (0, p.main_depth - 0.8, 10.0)),
        box_at((64.8, 2.5, 6.4), (0, p.main_depth - 0.8, 157.0)),
    ]
    return cut(module, grooves)


def build_top_lid(p: Params) -> Shape:
    w = p.body_width
    d = p.main_depth
    plate = box_at((w, d, p.lid_thickness), (0, d / 2, p.shell_height_without_lid + p.lid_thickness / 2))
    lips = [
        box_at((3.0, 146.0, 5.0), (-61.5, d / 2, 159.5)),
        box_at((3.0, 146.0, 5.0), (61.5, d / 2, 159.5)),
        box_at((126.0, 3.0, 5.0), (0, 6.5, 159.5)),
        box_at((126.0, 3.0, 5.0), (0, d - 6.5, 159.5)),
    ]
    lid = union([plate, *lips])

    boss_clearance = p.handle_boss_diameter / 2 + p.fit_clearance
    cutters = [
        cyl_z(boss_clearance, 12.0, (0, p.handle_anchor_front_y, 162.0)),
        cyl_z(boss_clearance, 12.0, (0, p.handle_anchor_rear_y, 162.0)),
    ]
    # Crossbar-end notches prevent the downward lid lips from colliding with
    # the removable load bars.
    for y in (p.handle_anchor_front_y, p.handle_anchor_rear_y):
        for x in (-61.5, 61.5):
            cutters.append(box_at((5.0, 14.0, 6.0), (x, y, 159.0)))
    return cut(lid, cutters)


def build_handle_crossbar(p: Params, y: float) -> Shape:
    bar = box_at((141.2, 12.0, 4.0), (0, y, 160.0))
    boss = cyl_z(p.handle_boss_diameter / 2, 8.0, (0, y, 162.0))
    crossbar = union([bar, boss])
    return crossbar - cyl_z(p.handle_insert_pilot / 2, 10.0, (0, y, 162.0))


def build_tpu_pad(p: Params) -> Shape:
    return Cylinder(
        p.tpu_pad_diameter / 2,
        p.tpu_pad_height,
        align=(Align.CENTER, Align.CENTER, Align.MIN),
    )


def build_tpu_handle_strap(p: Params) -> Shape:
    radius = p.handle_strap_width / 2
    body_length = p.handle_strap_length - 2 * radius
    strap = union(
        [
            box_at((p.handle_strap_width, body_length, p.handle_strap_thickness), (0, 0, p.handle_strap_thickness / 2)),
            cyl_z(radius, p.handle_strap_thickness, (0, -body_length / 2, p.handle_strap_thickness / 2)),
            cyl_z(radius, p.handle_strap_thickness, (0, body_length / 2, p.handle_strap_thickness / 2)),
        ]
    )
    hole_y = body_length / 2
    return cut(
        strap,
        [
            cyl_z(p.handle_bolt_clearance / 2, p.handle_strap_thickness + 2, (0, -hole_y, p.handle_strap_thickness / 2)),
            cyl_z(p.handle_bolt_clearance / 2, p.handle_strap_thickness + 2, (0, hole_y, p.handle_strap_thickness / 2)),
        ],
    )


def build_display_pod(p: Params, side: int) -> Shape:
    if side not in (-1, 1):
        raise ValueError("display side must be -1 or 1")
    shell_x = side * (p.body_width / 2 + p.display_pod_projection / 2)
    pod_y = 42.0
    pod_z = 111.0
    outer = box_at(
        (p.display_pod_projection, p.display_pod_depth, p.display_pod_height),
        (shell_x, pod_y, pod_z),
    )
    cavity = box_at((8.0, 66.0, 62.0), (side * (p.body_width / 2 + 4.0), pod_y, pod_z))
    pod = outer - cavity

    outer_face_x = side * (p.body_width / 2 + p.display_pod_projection - 2.0)
    screen_cut = box_at(
        (6.0, p.display_screen_width, p.display_screen_height),
        (outer_face_x, 38.0, 121.0),
    )
    encoder_cut = cyl_x(
        p.display_encoder_hole / 2,
        8.0,
        (outer_face_x, 61.0, 87.0),
    )
    cable_cut = box_at((8.0, 14.0, 20.0), (side * (p.body_width / 2 + 1.0), 42.0, 91.0))
    rail_cuts = [
        box_at((3.4, 6.4, 50.6), (side * (p.body_width / 2 + 1.5), y, 111.0))
        for y in (12.0, 72.0)
    ]
    return cut(pod, [screen_cut, encoder_cut, cable_cut, *rail_cuts])


def build_display_blank(p: Params, side: int) -> Shape:
    plate_x = side * (p.body_width / 2 + 2.0)
    plate = box_at((4.0, p.display_pod_depth, p.display_pod_height), (plate_x, 42.0, 111.0))
    rail_cuts = [
        box_at((3.4, 6.4, 50.6), (side * (p.body_width / 2 + 1.5), y, 111.0))
        for y in (12.0, 72.0)
    ]
    return cut(plate, rail_cuts)


def build_pair_fit_gauge(p: Params) -> Shape:
    left_center, right_center = device_centers(p)
    bundle_outer = p.device_center_gap / 2 + p.device_thickness
    guide_inner_face = bundle_outer + p.device_side_clearance
    guide_width = 2.5
    depth = 24.0
    width = 116.0
    base = box_at((width, depth, p.base_thickness), (0, depth / 2, p.base_thickness / 2))
    guides = [
        box_at((p.device_center_gap - 1.0, depth, 6.0), (0, depth / 2, p.base_thickness + 3.0)),
        box_at((guide_width, depth, 6.0), (guide_inner_face + guide_width / 2, depth / 2, p.base_thickness + 3.0)),
        box_at((guide_width, depth, 6.0), (-guide_inner_face - guide_width / 2, depth / 2, p.base_thickness + 3.0)),
    ]
    gauge = union([base, *guides])
    # Two small labels are represented as index notches, keeping the gauge
    # printable without relying on text geometry or fonts.
    notches = [
        box_at((2.0, 4.0, 2.0), (left_center, 2.0, p.base_thickness)),
        box_at((2.0, 4.0, 2.0), (right_center, 2.0, p.base_thickness)),
    ]
    return cut(gauge, notches)


def build_fan_mount_gauge(size: float, spacing: float, hole_diameter: float) -> Shape:
    thickness = 3.0
    gauge = box_at((size, size, thickness), (0, 0, thickness / 2))
    gauge = gauge - cyl_z(size / 2 - 9.0, thickness + 2, (0, 0, thickness / 2))
    half = spacing / 2
    for x in (-half, half):
        for y in (-half, half):
            gauge = gauge - cyl_z(hole_diameter / 2, thickness + 2, (x, y, thickness / 2))
    return gauge


def build_device_references(p: Params) -> list[Shape]:
    shapes = []
    y = p.device_front_clearance + p.device_depth / 2
    z = p.device_bottom_z + p.device_height / 2
    for x in device_centers(p):
        shapes.append(box_at((p.device_thickness, p.device_depth, p.device_height), (x, y, z)))
    return shapes


def build_fan_references(p: Params) -> list[Shape]:
    front = box_at(
        (p.front_fan_size, p.front_fan_thickness, p.front_fan_size),
        (0, -16.5, p.body_height / 2),
    )
    rear = box_at(
        (p.rear_fan_size, p.rear_fan_thickness, p.rear_fan_size),
        (0, p.main_depth + 16.0, p.body_height / 2),
    )
    return [front, rear]


def build_handle_reference(p: Params) -> Shape:
    bottom = p.body_height
    top = bottom + 33.0
    post_height = top - bottom
    front_y = p.handle_anchor_front_y
    rear_y = p.handle_anchor_rear_y
    parts = [
        cyl_z(4.2, post_height, (0, front_y, bottom + post_height / 2)),
        cyl_z(4.2, post_height, (0, rear_y, bottom + post_height / 2)),
        cyl_y(4.2, rear_y - front_y, (0, (front_y + rear_y) / 2, top)),
    ]
    return union(parts)


def shape_volume(shape: Shape) -> float:
    return float(sum(solid.volume for solid in shape.solids()))


def bbox_record(shape: Shape) -> dict[str, list[float] | float]:
    bbox = shape.bounding_box()
    size = bbox.size
    return {
        "min": [round(bbox.min.X, 4), round(bbox.min.Y, 4), round(bbox.min.Z, 4)],
        "max": [round(bbox.max.X, 4), round(bbox.max.Y, 4), round(bbox.max.Z, 4)],
        "size": [round(size.X, 4), round(size.Y, 4), round(size.Z, 4)],
    }


def parse_binary_stl(path: Path) -> tuple[np.ndarray, np.ndarray]:
    data = path.read_bytes()
    if len(data) < 84:
        raise ValueError(f"STL is too short: {path}")
    triangle_count = struct.unpack_from("<I", data, 80)[0]
    expected = 84 + triangle_count * 50
    if len(data) != expected:
        raise ValueError(f"Expected binary STL length {expected}, got {len(data)}: {path}")
    raw = np.frombuffer(data, dtype=np.uint8, offset=84).reshape(triangle_count, 50)
    normals = np.frombuffer(raw[:, :12].copy().tobytes(), dtype="<f4").reshape(-1, 3)
    vertices = np.frombuffer(raw[:, 12:48].copy().tobytes(), dtype="<f4").reshape(-1, 3, 3)
    return normals, vertices


def stl_mesh_record(path: Path) -> dict[str, int | list[float]]:
    _, vertices = parse_binary_stl(path)
    flat = vertices.reshape(-1, 3)
    rounded = np.round(flat, 4)
    vertex_ids: dict[tuple[float, float, float], int] = {}
    ids = []
    for vertex in rounded:
        key = (float(vertex[0]), float(vertex[1]), float(vertex[2]))
        if key not in vertex_ids:
            vertex_ids[key] = len(vertex_ids)
        ids.append(vertex_ids[key])
    ids_array = np.asarray(ids, dtype=np.int64).reshape(-1, 3)
    edge_counts: dict[tuple[int, int], int] = {}
    for tri in ids_array:
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            edge = (int(min(a, b)), int(max(a, b)))
            edge_counts[edge] = edge_counts.get(edge, 0) + 1
    non_manifold = sum(1 for count in edge_counts.values() if count != 2)
    size = flat.max(axis=0) - flat.min(axis=0)
    return {
        "triangles": int(len(vertices)),
        "vertices": int(len(vertex_ids)),
        "non_manifold_edges": int(non_manifold),
        "mesh_size": [round(float(value), 4) for value in size],
    }


def render_stl_preview(stl_path: Path, image_path: Path, elev: float, azim: float) -> None:
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    _, triangles = parse_binary_stl(stl_path)
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    max_faces = 14000
    if len(triangles) > max_faces:
        step = math.ceil(len(triangles) / max_faces)
        triangles = triangles[::step]
        normals = normals[::step]

    light = np.array([-0.45, -0.55, 0.70], dtype=float)
    light /= np.linalg.norm(light)
    unit_normals = normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-6)
    intensity = np.clip(np.sum(unit_normals.astype(np.float64) * light, axis=1), -0.2, 1.0)
    base = np.array([0.34, 0.39, 0.42])
    colors = np.clip(base * (0.62 + 0.46 * intensity[:, None]), 0.08, 0.92)
    colors = np.concatenate([colors, np.ones((len(colors), 1))], axis=1)

    fig = plt.figure(figsize=(9, 8), facecolor="#f3f4f5")
    ax = fig.add_subplot(111, projection="3d", facecolor="#f3f4f5")
    collection = Poly3DCollection(triangles, facecolors=colors, edgecolors=(0.08, 0.10, 0.11, 0.20), linewidths=0.12)
    ax.add_collection3d(collection)
    flat = triangles.reshape(-1, 3)
    mins = flat.min(axis=0)
    maxs = flat.max(axis=0)
    center = (mins + maxs) / 2
    radius = max(maxs - mins) * 0.57
    ax.set_xlim(center[0] - radius, center[0] + radius)
    ax.set_ylim(center[1] - radius, center[1] + radius)
    ax.set_zlim(center[2] - radius, center[2] + radius)
    ax.set_box_aspect((1, 1, 1))
    ax.set_proj_type("ortho")
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()
    fig.tight_layout(pad=0)
    image_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(image_path, dpi=180, bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)


def intersection_volume(a: Shape, b: Shape) -> float:
    try:
        return shape_volume(a & b)
    except Exception:
        return 0.0


def generate(p: Params, output_dir: Path) -> dict:
    parts_dir = output_dir / "parts"
    gauges_dir = output_dir / "fit-gauges"
    assemblies_dir = output_dir / "assemblies"
    reports_dir = output_dir / "reports"
    previews_dir = output_dir / "previews"
    for directory in (parts_dir, gauges_dir, assemblies_dir, reports_dir, previews_dir):
        directory.mkdir(parents=True, exist_ok=True)

    main_shell = build_main_shell(p)
    front_module = build_front_module(p)
    rear_module = build_rear_module(p)
    top_lid = build_top_lid(p)
    front_crossbar = build_handle_crossbar(p, p.handle_anchor_front_y)
    rear_crossbar = build_handle_crossbar(p, p.handle_anchor_rear_y)
    tpu_pad = build_tpu_pad(p)
    tpu_strap = build_tpu_handle_strap(p)
    display_left = build_display_pod(p, -1)
    display_right = build_display_pod(p, 1)
    blank_left = build_display_blank(p, -1)
    blank_right = build_display_blank(p, 1)

    part_specs = [
        PartSpec("main_u_shell", main_shell, oriented(main_shell), 1, "PETG", "Print upright on the full base; use an 8-12 mm brim.", "Integrated base, side walls, device guides, rear rails, and reversible display rails."),
        PartSpec("front_140_module", front_module, oriented(front_module, Axis.X, 90), 1, "PETG", "Print front face down.", "140 mm fan frame, guard, provisional 124.5 mm hole pattern, and shell tongue."),
        PartSpec("rear_60_module", rear_module, oriented(rear_module, Axis.X, 90), 1, "PETG", "Print rear guard face down.", "Semi-open 60 mm assist with passive upper and lower bypass windows."),
        PartSpec("top_lid", top_lid, oriented(top_lid, Axis.X, 180), 1, "PETG", "Print the exterior top face down.", "Removable lid with two crossbar boss clearances."),
        PartSpec("handle_crossbar", front_crossbar, oriented(front_crossbar), 2, "PETG", "Print flat with the boss upward.", "Two identical load bars; install M4 heat-set inserts after printing."),
        PartSpec("handle_strap_tpu", tpu_strap, oriented(tpu_strap), 1, "TPU 95A or commercial strap", "Print flat, 100% infill, longitudinal perimeters.", "Prototype flexible handle; a rated commercial strap is preferred for regular transport."),
        PartSpec("tpu_device_pad", tpu_pad, oriented(tpu_pad), 4, "TPU 95A", "Print flat, 100% infill.", "Replaceable 1.2 mm device support pad."),
        PartSpec("display_pod_left", display_left, oriented(display_left, Axis.Y, -90), 1, "PETG", "Print the outer display face down.", "Optional left-side pod; fit the actual display PCB before production."),
        PartSpec("display_pod_right", display_right, oriented(display_right, Axis.Y, 90), 1, "PETG", "Print the outer display face down.", "Optional right-side mirror of the display pod."),
        PartSpec("display_blank_left", blank_left, oriented(blank_left, Axis.Y, -90), 1, "PETG", "Print outer face down.", "Use when the display is installed on the right."),
        PartSpec("display_blank_right", blank_right, oriented(blank_right, Axis.Y, 90), 1, "PETG", "Print outer face down.", "Use when the display is installed on the left."),
    ]

    report: dict = {
        "parameters": asdict(p),
        "print_envelope_limit_mm": [180.0, 180.0, 180.0],
        "parts": [],
        "fit_gauges": [],
        "collisions": {},
        "part_collisions": {},
        "warnings": [
            "Confirm both physical GB10 units with calipers before printing the main shell.",
            "Confirm the exact 140 mm and 60 mm fan hole spacing and frame thickness.",
            "Confirm rear vent and connector boundaries with the selected cables installed.",
            "Confirm the display PCB, screen window, encoder, and connector dimensions.",
            "The flat TPU strap is a prototype; use a load-rated commercial handle for frequent transport.",
        ],
    }

    oversized: list[str] = []
    invalid: list[str] = []
    non_manifold: list[str] = []
    for spec in part_specs:
        stl_path = parts_dir / f"{spec.name}.stl"
        step_path = parts_dir / f"{spec.name}.step"
        export_stl(spec.print_shape, stl_path, tolerance=0.02, angular_tolerance=0.15)
        export_step(spec.print_shape, step_path)
        bbox = bbox_record(spec.print_shape)
        mesh = stl_mesh_record(stl_path)
        size = bbox["size"]
        if any(float(value) > 180.01 for value in size):
            oversized.append(spec.name)
        if not spec.print_shape.is_valid() or len(spec.print_shape.solids()) != 1:
            invalid.append(spec.name)
        if mesh["non_manifold_edges"]:
            non_manifold.append(spec.name)
        report["parts"].append(
            {
                "name": spec.name,
                "quantity": spec.quantity,
                "material": spec.material,
                "print_orientation": spec.print_orientation,
                "notes": spec.notes,
                "stl": str(stl_path.relative_to(output_dir)),
                "step": str(step_path.relative_to(output_dir)),
                "valid_brep": bool(spec.print_shape.is_valid()),
                "solids": len(spec.print_shape.solids()),
                "volume_mm3": round(shape_volume(spec.print_shape), 2),
                "bbox": bbox,
                "mesh": mesh,
            }
        )

    gauges = {
        "gb10_pair_fit_gauge": build_pair_fit_gauge(p),
        "fan140_mount_gauge": build_fan_mount_gauge(p.front_fan_size, p.front_fan_hole_spacing, p.front_fan_hole_diameter),
        "fan60_mount_gauge": build_fan_mount_gauge(p.rear_fan_size, p.rear_fan_hole_spacing, p.rear_fan_hole_diameter),
    }
    for name, shape in gauges.items():
        print_shape = oriented(shape)
        stl_path = gauges_dir / f"{name}.stl"
        step_path = gauges_dir / f"{name}.step"
        export_stl(print_shape, stl_path, tolerance=0.02, angular_tolerance=0.15)
        export_step(print_shape, step_path)
        mesh = stl_mesh_record(stl_path)
        report["fit_gauges"].append(
            {
                "name": name,
                "stl": str(stl_path.relative_to(output_dir)),
                "step": str(step_path.relative_to(output_dir)),
                "bbox": bbox_record(print_shape),
                "valid_brep": bool(print_shape.is_valid()),
                "solids": len(print_shape.solids()),
                "mesh": mesh,
            }
        )
        if mesh["non_manifold_edges"]:
            non_manifold.append(name)

    printed_left = [main_shell, front_module, rear_module, top_lid, front_crossbar, rear_crossbar, display_left, blank_right]
    printed_right = [main_shell, front_module, rear_module, top_lid, front_crossbar, rear_crossbar, display_right, blank_left]
    handle_reference = build_handle_reference(p)
    device_references = build_device_references(p)
    fan_references = build_fan_references(p)

    assembly_left = Compound(children=[*printed_left, handle_reference])
    assembly_right = Compound(children=[*printed_right, handle_reference])
    fit_reference = Compound(children=[*printed_left, handle_reference, *device_references, *fan_references])

    export_step(assembly_left, assemblies_dir / "a_plus_left_display.step")
    export_stl(assembly_left, assemblies_dir / "a_plus_left_display.stl", tolerance=0.03, angular_tolerance=0.2)
    export_step(assembly_right, assemblies_dir / "a_plus_right_display.step")
    export_stl(assembly_right, assemblies_dir / "a_plus_right_display.stl", tolerance=0.03, angular_tolerance=0.2)
    export_step(fit_reference, assemblies_dir / "a_plus_fit_reference_with_devices.step")

    exploded_left_shapes = [
        main_shell,
        front_module.translate((0, -55, 0)),
        rear_module.translate((0, 48, 0)),
        top_lid.translate((0, 0, 62)),
        front_crossbar.translate((0, 0, 32)),
        rear_crossbar.translate((0, 0, 32)),
        display_left.translate((-42, 0, 0)),
        blank_right.translate((22, 0, 0)),
        handle_reference.translate((0, 0, 112)),
    ]
    exploded_left = Compound(children=exploded_left_shapes)
    export_step(exploded_left, assemblies_dir / "a_plus_exploded_left_display.step")
    export_stl(exploded_left, assemblies_dir / "a_plus_exploded_left_display.stl", tolerance=0.03, angular_tolerance=0.2)

    # Device-to-print collision should be zero; positive clearance is preserved
    # at the guides, front tongue, rear rails, crossbars, and lid.
    for index, device in enumerate(device_references, start=1):
        collisions = {}
        for name, shape in (
            ("main_u_shell", main_shell),
            ("front_140_module", front_module),
            ("rear_60_module", rear_module),
            ("top_lid", top_lid),
            ("front_handle_crossbar", front_crossbar),
            ("rear_handle_crossbar", rear_crossbar),
        ):
            collisions[name] = round(intersection_volume(device, shape), 5)
        report["collisions"][f"gb10_{index}"] = collisions

    collision_shapes = {
        "main_u_shell": main_shell,
        "front_140_module": front_module,
        "rear_60_module": rear_module,
        "top_lid": top_lid,
        "front_handle_crossbar": front_crossbar,
        "rear_handle_crossbar": rear_crossbar,
        "display_pod_left": display_left,
        "display_blank_right": blank_right,
    }
    checked_pairs = [
        ("main_u_shell", "front_140_module"),
        ("main_u_shell", "rear_60_module"),
        ("main_u_shell", "top_lid"),
        ("main_u_shell", "front_handle_crossbar"),
        ("main_u_shell", "rear_handle_crossbar"),
        ("main_u_shell", "display_pod_left"),
        ("main_u_shell", "display_blank_right"),
        ("top_lid", "front_handle_crossbar"),
        ("top_lid", "rear_handle_crossbar"),
        ("front_140_module", "top_lid"),
        ("rear_60_module", "top_lid"),
    ]
    for first, second in checked_pairs:
        report["part_collisions"][f"{first}__{second}"] = round(
            intersection_volume(collision_shapes[first], collision_shapes[second]),
            5,
        )

    report["checks"] = {
        "oversized_parts": oversized,
        "invalid_parts": invalid,
        "non_manifold_meshes": non_manifold,
        "all_parts_within_180mm": not oversized,
        "all_parts_valid": not invalid,
        "all_meshes_closed": not non_manifold,
        "device_collision_free": all(
            volume <= 0.01
            for device_collisions in report["collisions"].values()
            for volume in device_collisions.values()
        ),
        "assembly_collision_free": all(
            volume <= 0.01 for volume in report["part_collisions"].values()
        ),
    }

    (reports_dir / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    manifest = {
        "design": "dual-gb10-a-plus",
        "revision": "prototype-r1",
        "units": "mm",
        "parameters": report["parameters"],
        "parts": report["parts"],
        "fit_gauges": report["fit_gauges"],
        "assemblies": [
            "assemblies/a_plus_left_display.step",
            "assemblies/a_plus_left_display.stl",
            "assemblies/a_plus_right_display.step",
            "assemblies/a_plus_right_display.stl",
            "assemblies/a_plus_exploded_left_display.step",
            "assemblies/a_plus_exploded_left_display.stl",
            "assemblies/a_plus_fit_reference_with_devices.step",
        ],
        "validation": "reports/validation.json",
        "checks": report["checks"],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    guide_path = Path(__file__).with_name("README.md")
    (output_dir / "README.md").write_text(guide_path.read_text(encoding="utf-8"), encoding="utf-8")
    render_stl_preview(
        assemblies_dir / "a_plus_left_display.stl",
        previews_dir / "a_plus_left_display.png",
        elev=25,
        azim=-135,
    )
    render_stl_preview(
        assemblies_dir / "a_plus_exploded_left_display.stl",
        previews_dir / "a_plus_exploded_left_display.png",
        elev=24,
        azim=-128,
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = generate(Params(), args.output.resolve())
    print(json.dumps(report["checks"], indent=2))
    print(f"Generated CAD in {args.output.resolve()}")


if __name__ == "__main__":
    main()
