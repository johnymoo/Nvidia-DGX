import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";

const params = new URLSearchParams(window.location.search);
const view = params.get("view") || "finished";

const C = {
  bg: 0xeef0f2,
  shell: 0x24272a,
  shellEdge: 0x34383c,
  black: 0x0d0f10,
  dark: 0x17191b,
  gold: 0xb99043,
  goldDark: 0x6f5426,
  glass: 0x071117,
  cyan: 0x79d5ff,
  blue: 0x258bd2,
  red: 0xe0553f,
  metal: 0x8b9399,
};

const scene = new THREE.Scene();
scene.background = new THREE.Color(C.bg);

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.08;
document.body.appendChild(renderer.domElement);

const camera = new THREE.PerspectiveCamera(34, window.innerWidth / window.innerHeight, 0.1, 2000);
const cameraBasePosition = new THREE.Vector3();
const cameraTarget = new THREE.Vector3();

function configureCamera(position, target) {
  cameraBasePosition.set(...position);
  cameraTarget.set(...target);
  applyResponsiveCamera();
}

function applyResponsiveCamera() {
  const aspect = window.innerWidth / window.innerHeight;
  const distanceScale = aspect < 0.8 ? 1.65 : 1;
  camera.position.copy(cameraTarget).add(
    cameraBasePosition.clone().sub(cameraTarget).multiplyScalar(distanceScale)
  );
  camera.fov = aspect < 0.8 ? 40 : 34;
  camera.aspect = aspect;
  camera.updateProjectionMatrix();
  camera.lookAt(cameraTarget);
}

function material(color, options = {}) {
  return new THREE.MeshStandardMaterial({
    color,
    roughness: options.roughness ?? 0.7,
    metalness: options.metalness ?? 0.05,
    transparent: (options.opacity ?? 1) < 1,
    opacity: options.opacity ?? 1,
    depthWrite: (options.opacity ?? 1) >= 1,
    side: options.side ?? THREE.FrontSide,
  });
}

function roundedBox(w, h, d, r, mat, position = [0, 0, 0]) {
  const mesh = new THREE.Mesh(new RoundedBoxGeometry(w, h, d, 5, r), mat);
  mesh.position.set(...position);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

function box(w, h, d, mat, position = [0, 0, 0]) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
  mesh.position.set(...position);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

function cylinder(radius, depth, mat, position = [0, 0, 0], axis = "z") {
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, depth, 48), mat);
  if (axis === "z") mesh.rotation.x = Math.PI / 2;
  if (axis === "x") mesh.rotation.z = Math.PI / 2;
  mesh.position.set(...position);
  mesh.castShadow = true;
  return mesh;
}

function screw(position, axis = "z") {
  const group = new THREE.Group();
  const head = cylinder(2.2, 1.2, material(C.metal, { metalness: 0.75, roughness: 0.3 }), position, axis);
  group.add(head);
  return group;
}

function makeWaveSlats(width, height, depth, mat, normal = "z") {
  const group = new THREE.Group();
  const rows = 18;
  for (let i = 0; i < rows; i += 1) {
    const y = -height / 2 + 6 + (i * (height - 12)) / (rows - 1);
    const slat = roundedBox(width - 10, 2.4, depth, 0.8, mat, [0, y, 0]);
    slat.rotation.z = 0.1 * Math.sin((i / (rows - 1)) * Math.PI * 2);
    group.add(slat);
  }
  if (normal === "y") group.rotation.x = -Math.PI / 2;
  return group;
}

function makeFan(horizontal = false) {
  const group = new THREE.Group();
  const frameMat = material(C.dark, { roughness: 0.55 });
  const bladeMat = material(C.black, { roughness: 0.4 });
  const metalMat = material(C.metal, { metalness: 0.5, roughness: 0.35 });

  const edge = 9;
  group.add(roundedBox(140, edge, 25, 2.5, frameMat, [0, 65.5, 0]));
  group.add(roundedBox(140, edge, 25, 2.5, frameMat, [0, -65.5, 0]));
  group.add(roundedBox(edge, 122, 25, 2.5, frameMat, [65.5, 0, 0]));
  group.add(roundedBox(edge, 122, 25, 2.5, frameMat, [-65.5, 0, 0]));

  for (let i = 0; i < 9; i += 1) {
    const angle = (i / 9) * Math.PI * 2;
    const blade = roundedBox(48, 12, 3.2, 4, bladeMat, [34 * Math.cos(angle), 34 * Math.sin(angle), -1]);
    blade.rotation.z = angle + 0.45;
    group.add(blade);
  }
  group.add(cylinder(17, 8, bladeMat, [0, 0, -2], "z"));
  group.add(cylinder(4, 9, metalMat, [0, 0, -6], "z"));

  if (horizontal) group.rotation.x = -Math.PI / 2;
  return group;
}

function makeGuard() {
  const group = new THREE.Group();
  const guardMat = material(C.shellEdge, { roughness: 0.55, metalness: 0.1 });
  for (const radius of [24, 42, 60]) {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(radius, 1.7, 10, 64), guardMat);
    ring.castShadow = true;
    group.add(ring);
  }
  for (let i = 0; i < 8; i += 1) {
    const spoke = roundedBox(124, 2.8, 2.4, 1, guardMat, [0, 0, 0]);
    spoke.rotation.z = (i / 8) * Math.PI;
    group.add(spoke);
  }
  return group;
}

function makeFrontGrille() {
  const group = new THREE.Group();
  const borderMat = material(C.shellEdge, { roughness: 0.6 });
  const goldMat = material(C.gold, { metalness: 0.35, roughness: 0.45 });
  const slatMat = material(0x464c51, { metalness: 0.08, roughness: 0.5 });
  const blackMat = material(C.black);
  group.add(roundedBox(146, 146, 4, 5, blackMat));
  group.add(roundedBox(146, 7, 6, 2, borderMat, [0, 69.5, -1]));
  group.add(roundedBox(146, 7, 6, 2, borderMat, [0, -69.5, -1]));
  group.add(roundedBox(7, 132, 6, 2, borderMat, [69.5, 0, -1]));
  group.add(roundedBox(7, 132, 6, 2, borderMat, [-69.5, 0, -1]));
  const slats = makeWaveSlats(136, 132, 3, slatMat);
  slats.position.z = -3.6;
  group.add(slats);
  group.add(roundedBox(136, 2.2, 2, 0.8, goldMat, [0, 65, -5]));
  group.add(roundedBox(136, 2.2, 2, 0.8, goldMat, [0, -65, -5]));
  group.add(roundedBox(2.2, 128, 2, 0.8, goldMat, [65, 0, -5]));
  group.add(roundedBox(2.2, 128, 2, 0.8, goldMat, [-65, 0, -5]));
  return group;
}

function makeDevice(side, opacity = 1) {
  const group = new THREE.Group();
  const bodyMat = material(0x17191b, { roughness: 0.42, metalness: 0.08, opacity });
  const detailOpacity = opacity < 1 ? Math.max(opacity, 0.68) : 1;
  const goldMat = material(C.gold, { metalness: 0.45, roughness: 0.35, opacity: detailOpacity });
  const blackMat = material(C.black, { roughness: 0.5, opacity: detailOpacity });
  const x = side * 29.5;
  group.add(roundedBox(51, 150, 150, 4.5, bodyMat, [x, 75, 75]));

  const front = new THREE.Group();
  front.position.set(x, 75, -0.8);
  front.add(roundedBox(45, 144, 2.2, 3, goldMat));
  const frontSlats = makeWaveSlats(43, 140, 2.6, blackMat);
  frontSlats.position.z = -1.5;
  front.add(frontSlats);
  group.add(front);

  const innerX = side * 16.75;
  const outerX = side * 42.25;
  const rearVent = new THREE.Group();
  rearVent.position.set(innerX, 75, 150.9);
  rearVent.add(roundedBox(23, 144, 2.2, 2.5, goldMat));
  const ventSlats = makeWaveSlats(21, 138, 2.5, blackMat);
  ventSlats.position.z = 1.4;
  rearVent.add(ventSlats);
  group.add(rearVent);

  const ports = new THREE.Group();
  ports.position.set(outerX, 75, 151.2);
  ports.add(roundedBox(23, 144, 2.4, 2.5, goldMat));
  const portYs = [126, 109, 92, 73, 52, 29];
  const portWidths = [8, 8, 8, 13, 16, 17];
  portYs.forEach((py, i) => {
    ports.add(roundedBox(portWidths[i], i > 3 ? 12 : 8, 3.4, 1.2, blackMat, [0, py - 75, 2.1]));
  });
  group.add(ports);
  return group;
}

function makeDisplayPod(opacity = 1) {
  const group = new THREE.Group();
  const podMat = material(C.shell, { opacity, roughness: 0.6 });
  group.add(roundedBox(12, 72, 82, 5, podMat, [-79, 112, 33]));

  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 384;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#071117";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#8bdcff";
  ctx.font = "600 39px ui-monospace, SFMono-Regular, Menlo, monospace";
  ["GB10-1  54 C", "GB10-2  57 C", "FAN   1180 RPM", "AUTO"].forEach((line, index) => {
    ctx.fillText(line, 28, 62 + index * 78);
  });
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const screen = new THREE.Mesh(
    new THREE.PlaneGeometry(62, 46),
    new THREE.MeshBasicMaterial({ map: texture })
  );
  screen.rotation.y = -Math.PI / 2;
  screen.position.set(-85.2, 121, 30);
  group.add(screen);
  group.add(cylinder(8, 5, material(C.black, { roughness: 0.38 }), [-86, 83, 50], "x"));
  return group;
}

function makeShell(opacity = 1) {
  const group = new THREE.Group();
  const shellMat = material(C.shell, { opacity, roughness: 0.72 });
  const edgeMat = material(C.shellEdge, { opacity, roughness: 0.62 });
  group.add(roundedBox(5, 192, 222, 2, shellMat, [-73.5, 96, 85]));
  group.add(roundedBox(5, 192, 222, 2, shellMat, [73.5, 96, 85]));
  group.add(roundedBox(152, 5, 222, 2, shellMat, [0, 2.5, 85]));
  group.add(roundedBox(152, 5, 104, 2, edgeMat, [0, 193, 22]));
  group.add(roundedBox(152, 43, 7, 2, edgeMat, [0, 171.5, -29]));
  group.add(roundedBox(9, 160, 7, 2, edgeMat, [-69, 80, -29]));
  group.add(roundedBox(9, 160, 7, 2, edgeMat, [69, 80, -29]));
  return group;
}

function makeFrontModule(showGrille = true) {
  const group = new THREE.Group();
  const fan = makeFan(false);
  fan.position.set(0, 75, -19);
  group.add(fan);
  if (showGrille) {
    const grille = makeFrontGrille();
    grille.position.set(0, 75, -34);
    group.add(grille);
  } else {
    const guard = makeGuard();
    guard.position.set(0, 75, -33);
    group.add(guard);
  }
  return group;
}

function makeTopExhaust(showGrille = true) {
  const group = new THREE.Group();
  const fan = makeFan(true);
  fan.position.set(0, 176, 145);
  group.add(fan);
  if (showGrille) {
    const shroudMat = material(C.shellEdge, { roughness: 0.62 });
    group.add(roundedBox(6, 32, 148, 2, shroudMat, [-73, 176, 145]));
    group.add(roundedBox(6, 32, 148, 2, shroudMat, [73, 176, 145]));
    group.add(roundedBox(142, 32, 6, 2, shroudMat, [0, 176, 74]));
    group.add(roundedBox(142, 32, 6, 2, shroudMat, [0, 176, 216]));
    group.add(roundedBox(148, 5, 7, 2, shroudMat, [0, 193, 76]));
    group.add(roundedBox(148, 5, 7, 2, shroudMat, [0, 193, 214]));
    group.add(roundedBox(7, 5, 132, 2, shroudMat, [-70.5, 193, 145]));
    group.add(roundedBox(7, 5, 132, 2, shroudMat, [70.5, 193, 145]));
    const slats = makeWaveSlats(138, 132, 3, material(0x464c51, { metalness: 0.08, roughness: 0.5 }), "y");
    slats.position.set(0, 193, 145);
    group.add(slats);
  }
  return group;
}

function makeDuct(opacity = 0.32) {
  const group = new THREE.Group();
  const hotMat = material(C.red, { opacity, roughness: 0.45, side: THREE.DoubleSide });
  group.add(roundedBox(56, 148, 34, 5, hotMat, [0, 76, 167]));
  group.add(roundedBox(142, 18, 138, 5, hotMat, [0, 157, 145]));
  return group;
}

function makeCable(side) {
  const x = side * 44;
  const curve = new THREE.CatmullRomCurve3([
    new THREE.Vector3(x, 75, 153),
    new THREE.Vector3(side * 58, 72, 174),
    new THREE.Vector3(side * 62, 58, 205),
    new THREE.Vector3(side * 70, 50, 225),
  ]);
  const tube = new THREE.Mesh(
    new THREE.TubeGeometry(curve, 36, 2.8, 10, false),
    material(C.black, { roughness: 0.55 })
  );
  tube.castShadow = true;
  return tube;
}

function arrow(from, to, color) {
  const start = new THREE.Vector3(...from);
  const end = new THREE.Vector3(...to);
  const direction = end.clone().sub(start);
  const length = direction.length();
  direction.normalize();
  return new THREE.ArrowHelper(direction, start, length, color, Math.min(13, length * 0.22), 6);
}

function flowArrow(from, to, color) {
  const group = new THREE.Group();
  const start = new THREE.Vector3(...from);
  const end = new THREE.Vector3(...to);
  const direction = end.clone().sub(start);
  const length = direction.length();
  direction.normalize();
  const shaftLength = Math.max(2, length - 13);
  const flowMat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.9 });
  const shaft = new THREE.Mesh(new THREE.CylinderGeometry(2.8, 2.8, shaftLength, 16), flowMat);
  shaft.position.copy(start).add(direction.clone().multiplyScalar(shaftLength / 2));
  shaft.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction);
  group.add(shaft);
  const head = new THREE.Mesh(new THREE.ConeGeometry(7, 13, 20), flowMat);
  head.position.copy(end).add(direction.clone().multiplyScalar(-6.5));
  head.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction);
  group.add(head);
  return group;
}

function addFasteners(group) {
  const frontZ = -36.5;
  [[-67, 12], [67, 12], [-67, 148], [67, 148]].forEach(([x, y]) => group.add(screw([x, y, frontZ])));
  [[-74.5, 15, 12], [-74.5, 145, 12], [-74.5, 15, 190], [-74.5, 145, 190]].forEach((p) => group.add(screw(p, "x")));
}

function buildFinished() {
  const root = new THREE.Group();
  root.add(makeShell(1));
  root.add(makeDevice(-1));
  root.add(makeDevice(1));
  root.add(makeFrontModule(true));
  root.add(makeTopExhaust(true));
  root.add(makeDisplayPod(1));
  addFasteners(root);
  scene.add(root);
  configureCamera([-300, 245, -330], [0, 83, 82]);
}

function buildCutaway() {
  const root = new THREE.Group();
  root.add(makeShell(0.12));
  root.add(makeDevice(-1, 0.42));
  root.add(makeDevice(1, 0.42));
  root.add(makeFrontModule(false));
  root.add(makeTopExhaust(false));
  root.add(makeDuct(0.16));
  root.add(makeCable(-1));
  root.add(makeCable(1));

  [-31, 31].forEach((x) => {
    root.add(flowArrow([x, 50, -70], [x, 50, 135], C.blue));
    root.add(flowArrow([x, 105, -70], [x, 105, 135], C.blue));
  });
  [-16, 16].forEach((x) => {
    root.add(flowArrow([x, 58, 138], [x, 58, 169], 0xff3b25));
    root.add(flowArrow([x, 63, 165], [x, 151, 165], 0xff3b25));
    root.add(flowArrow([x, 153, 145], [x, 220, 145], 0xff3b25));
  });
  scene.add(root);
  configureCamera([-420, 235, -130], [0, 88, 82]);
}

function buildExploded() {
  const root = new THREE.Group();
  const shellMat = material(C.shell, { roughness: 0.72 });

  const frontGrille = makeFrontGrille();
  frontGrille.position.set(0, 85, -175);
  root.add(frontGrille);

  const frontFan = makeFan(false);
  frontFan.position.set(0, 85, -110);
  root.add(frontFan);

  const plenumMat = material(C.shellEdge);
  root.add(roundedBox(146, 8, 18, 2, plenumMat, [0, 157, -58]));
  root.add(roundedBox(146, 8, 18, 2, plenumMat, [0, 13, -58]));
  root.add(roundedBox(8, 136, 18, 2, plenumMat, [-69, 85, -58]));
  root.add(roundedBox(8, 136, 18, 2, plenumMat, [69, 85, -58]));

  const base = roundedBox(150, 8, 220, 3, shellMat, [0, -26, 90]);
  root.add(base);

  const leftDevice = makeDevice(-1);
  leftDevice.position.x = -38;
  leftDevice.position.y = 10;
  root.add(leftDevice);
  const rightDevice = makeDevice(1);
  rightDevice.position.x = 38;
  rightDevice.position.y = 10;
  root.add(rightDevice);

  root.add(roundedBox(5, 154, 155, 2, material(C.dark), [0, 85, 76]));

  const leftShell = roundedBox(5, 160, 222, 2, shellMat, [-135, 82, 85]);
  const rightShell = roundedBox(5, 160, 222, 2, shellMat, [135, 82, 85]);
  root.add(leftShell, rightShell);

  const duct = makeDuct(0.78);
  duct.position.z = 55;
  root.add(duct);

  const topFan = makeFan(true);
  topFan.position.set(0, 270, 145);
  root.add(topFan);

  const topSlats = makeWaveSlats(138, 132, 3, material(C.goldDark), "y");
  topSlats.position.set(0, 318, 145);
  root.add(topSlats);

  root.add(roundedBox(152, 7, 222, 3, shellMat, [0, 355, 85]));

  const display = makeDisplayPod(1);
  display.position.x = -90;
  display.position.y = 20;
  root.add(display);

  scene.add(root);
  configureCamera([-520, 410, -580], [0, 150, 65]);
}

if (view === "cutaway") buildCutaway();
else if (view === "exploded") buildExploded();
else buildFinished();

const hemi = new THREE.HemisphereLight(0xffffff, 0x92989d, 2.1);
scene.add(hemi);
const key = new THREE.DirectionalLight(0xffffff, 4.2);
key.position.set(-260, 420, -320);
key.castShadow = true;
key.shadow.mapSize.set(2048, 2048);
key.shadow.camera.near = 1;
key.shadow.camera.far = 1000;
key.shadow.camera.left = -400;
key.shadow.camera.right = 400;
key.shadow.camera.top = 400;
key.shadow.camera.bottom = -400;
scene.add(key);
const fill = new THREE.DirectionalLight(0xd8e7f2, 2.2);
fill.position.set(300, 190, 240);
scene.add(fill);
const rim = new THREE.DirectionalLight(0xfff0d8, 1.5);
rim.position.set(160, 300, -280);
scene.add(rim);

const floor = new THREE.Mesh(
  new THREE.PlaneGeometry(1400, 1400),
  new THREE.ShadowMaterial({ color: 0x53606a, opacity: 0.16 })
);
floor.rotation.x = -Math.PI / 2;
floor.position.y = view === "exploded" ? -55 : -3;
floor.receiveShadow = true;
scene.add(floor);

function render() {
  renderer.render(scene, camera);
}

window.addEventListener("resize", () => {
  applyResponsiveCamera();
  renderer.setSize(window.innerWidth, window.innerHeight);
  render();
});

render();
window.__GB10_RENDER_READY__ = true;
