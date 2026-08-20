import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { DESIGN, buildDesign } from "./design.js";

const viewport = document.querySelector("#viewport");
const scene = new THREE.Scene();
scene.background = new THREE.Color(0xf2f3f4);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.outputColorSpace = THREE.SRGBColorSpace;
viewport.appendChild(renderer.domElement);

const perspective = new THREE.PerspectiveCamera(34, 1, 0.1, 5000);
const orthographic = new THREE.OrthographicCamera(-100, 100, 100, -100, 0.1, 5000);
let camera = perspective;
let controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;

scene.add(new THREE.HemisphereLight(0xffffff, 0x697078, 2.1));
const key = new THREE.DirectionalLight(0xffffff, 3.2);
key.position.set(-180, -220, 320);
key.castShadow = true;
scene.add(key);

const root = buildDesign();
scene.add(root);
const floor = new THREE.GridHelper(500, 50, 0xaeb3b8, 0xd5d8db);
floor.rotation.x = Math.PI / 2;
scene.add(floor);

const state = {
  mode: "assembled",
  explosion: 0,
  cameraView: "perspective",
  categoryVisibility: Object.fromEntries(
    Object.entries(DESIGN.categories).map(([id, config]) => [id, config.visible !== false]),
  ),
};
const directions = {
  perspective: [1.25, -1.55, 1.05],
  front: [0, -1, 0], rear: [0, 1, 0], left: [-1, 0, 0], right: [1, 0, 0],
  top: [0, 0, 1], bottom: [0, 0, -1],
};
let selectedPart = null;

function eachPart(callback) {
  root.traverse((object) => object.isGroup && object.userData.partId && callback(object));
}

function eachPartMesh(partGroup, callback) {
  partGroup.traverse((object) => object.isMesh && callback(object));
}

function applyParts() {
  eachPart((partGroup) => {
    const { category, basePosition, explode, enabled } = partGroup.userData;
    partGroup.visible = enabled && state.categoryVisibility[category] !== false;
    const factor = state.mode === "exploded" ? state.explosion : 0;
    partGroup.position.copy(basePosition).addScaledVector(explode, factor);
    const transparent = state.mode === "transparent" && category === "printed";
    eachPartMesh(partGroup, (mesh) => {
      mesh.material.transparent = transparent || category === "keepout" || category === "airflow";
      mesh.material.opacity = category === "keepout" ? 0.18 : category === "airflow" ? 0.4 : transparent ? 0.24 : 1;
      mesh.material.depthWrite = !(transparent || category === "keepout" || category === "airflow");
      mesh.material.side = transparent ? THREE.DoubleSide : THREE.FrontSide;
      mesh.material.emissive.set(partGroup === selectedPart ? 0x392018 : 0x000000);
    });
  });
}

function visibleBounds() {
  const box = new THREE.Box3();
  eachPart((partGroup) => {
    if (partGroup.visible) box.expandByObject(partGroup);
  });
  return box.isEmpty() ? new THREE.Box3().setFromObject(root) : box;
}

function fitCamera(view = state.cameraView) {
  const box = visibleBounds();
  const center = box.getCenter(new THREE.Vector3());
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  const radius = Math.max(sphere.radius * 1.2, 1);
  const direction = new THREE.Vector3(...directions[view]).normalize();
  const next = view === "perspective" ? perspective : orthographic;
  if (next !== camera) {
    controls.dispose();
    camera = next;
    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
  }
  const aspect = Math.max(viewport.clientWidth / viewport.clientHeight, 0.1);
  let distance = radius * 2.6;
  if (camera.isPerspectiveCamera) {
    const verticalFov = THREE.MathUtils.degToRad(camera.fov);
    const horizontalFov = 2 * Math.atan(Math.tan(verticalFov / 2) * aspect);
    distance = radius / Math.sin(Math.min(verticalFov, horizontalFov) / 2);
  }
  camera.position.copy(center).addScaledVector(direction, distance);
  camera.up.set(0, 0, 1);
  if (Math.abs(direction.z) > 0.9) camera.up.set(0, 1, 0);
  controls.target.copy(center);
  if (camera.isOrthographicCamera) {
    const halfWidth = aspect >= 1 ? radius * aspect : radius;
    const halfHeight = aspect >= 1 ? radius : radius / aspect;
    camera.left = -halfWidth;
    camera.right = halfWidth;
    camera.top = halfHeight;
    camera.bottom = -halfHeight;
  }
  camera.near = 0.1;
  camera.far = Math.max(distance + radius * 4, 100);
  camera.updateProjectionMatrix();
  controls.update();
}

function resize() {
  const width = viewport.clientWidth;
  const height = viewport.clientHeight;
  renderer.setSize(width, height, false);
  perspective.aspect = width / height;
  perspective.updateProjectionMatrix();
  if (camera.isOrthographicCamera) fitCamera();
}

function selectPart(partGroup) {
  selectedPart = partGroup;
  const selected = document.querySelector("#selected-part");
  selected.textContent = partGroup
    ? `${partGroup.userData.label} · ${partGroup.userData.size.join(" × ")} ${DESIGN.units}`
    : "None";
  applyParts();
}

function createVisibilityControls() {
  const categoryRoot = document.querySelector("#category-controls");
  Object.entries(DESIGN.categories).forEach(([id, config]) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = state.categoryVisibility[id];
    input.addEventListener("change", () => {
      state.categoryVisibility[id] = input.checked;
      applyParts();
      fitCamera();
    });
    label.append(input, ` ${config.label ?? id}`);
    categoryRoot.append(label);
  });

  const partRoot = document.querySelector("#part-controls");
  eachPart((partGroup) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = true;
    input.addEventListener("change", () => {
      partGroup.userData.enabled = input.checked;
      applyParts();
      fitCamera();
    });
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = partGroup.userData.label;
    button.addEventListener("click", () => selectPart(partGroup));
    label.append(input, button);
    partRoot.append(label);
  });
}

document.querySelector("#design-name").textContent = DESIGN.name;
document.querySelector("#revision").textContent = `${DESIGN.revision} · ${DESIGN.units}`;
document.querySelector("#envelope").textContent = DESIGN.envelope.join(" × ") + ` ${DESIGN.units}`;
document.querySelector("#dimension-status").textContent = `${DESIGN.dimensions.verified}V / ${DESIGN.dimensions.provisional}P / ${DESIGN.dimensions.unknown}U`;
document.querySelector("#warnings").textContent = DESIGN.warnings.join(" · ");
createVisibilityControls();

document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => {
  state.mode = button.dataset.mode;
  document.querySelectorAll("[data-mode]").forEach((candidate) => candidate.classList.toggle("active", candidate === button));
  if (state.mode === "exploded" && state.explosion === 0) {
    state.explosion = 0.7;
    document.querySelector("#explode").value = String(state.explosion);
  }
  applyParts();
  fitCamera();
}));
document.querySelector("#explode").addEventListener("input", (event) => {
  state.explosion = Number(event.target.value);
  applyParts();
});
document.querySelector("#explode").addEventListener("change", () => fitCamera());
document.querySelector("#camera-view").addEventListener("change", (event) => {
  state.cameraView = event.target.value;
  fitCamera();
});
document.querySelector("#reset-view").addEventListener("click", () => fitCamera());

const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
renderer.domElement.addEventListener("pointerdown", (event) => {
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const hit = raycaster.intersectObject(root, true)[0];
  let partGroup = hit?.object;
  while (partGroup && !partGroup.userData.partId) partGroup = partGroup.parent;
  selectPart(partGroup?.userData.partId ? partGroup : null);
});

new ResizeObserver(resize).observe(viewport);
applyParts();
resize();
fitCamera();
renderer.setAnimationLoop(() => {
  controls.update();
  renderer.render(scene, camera);
});
