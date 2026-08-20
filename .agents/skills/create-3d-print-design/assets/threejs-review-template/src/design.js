import * as THREE from "three";

export const DESIGN = {
  name: "Replace with project name",
  revision: "R0",
  units: "mm",
  envelope: [160, 120, 80],
  dimensions: { verified: 3, provisional: 2, unknown: 1 },
  categories: {
    printed: { label: "Printed parts", visible: true },
    purchased: { label: "Purchased parts", visible: true },
    keepout: { label: "Keep-outs", visible: false },
    airflow: { label: "Airflow", visible: false },
    cable: { label: "Cables", visible: true },
  },
  warnings: ["Sample geometry: replace src/design.js before review"],
};

function part(id, size, position, color, category = "printed", explode = [0, 0, 0]) {
  const group = new THREE.Group();
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(...size),
    new THREE.MeshStandardMaterial({ color, roughness: 0.72, metalness: 0.03 }),
  );
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  group.add(mesh);
  group.position.set(...position);
  group.userData = {
    partId: id,
    label: id,
    category,
    size,
    enabled: true,
    basePosition: group.position.clone(),
    explode: new THREE.Vector3(...explode),
  };
  return group;
}

export function buildDesign() {
  const root = new THREE.Group();
  root.name = "design-root";
  root.add(part("base", [160, 120, 8], [0, 0, 4], 0x31363b, "printed", [0, 0, -35]));
  root.add(part("left-wall", [8, 120, 72], [-76, 0, 44], 0x42484e, "printed", [-45, 0, 0]));
  root.add(part("right-wall", [8, 120, 72], [76, 0, 44], 0x42484e, "printed", [45, 0, 0]));
  root.add(part("reference-object", [110, 80, 55], [0, 0, 35], 0x1f8a70, "purchased", [0, 0, 18]));
  root.add(part("service-keepout", [130, 35, 60], [0, 78, 38], 0xe85d3f, "keepout", [0, 45, 0]));
  root.add(part("airflow-path", [18, 160, 12], [0, 0, 44], 0x2f91d0, "airflow", [0, 0, 28]));
  root.add(part("power-cable", [8, 45, 8], [48, 66, 24], 0x131516, "cable", [18, 30, 0]));
  return root;
}
