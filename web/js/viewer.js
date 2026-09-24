/* three.js scene: load, light, orbit, pick, explode, section, colour. */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const PROCESS_COLOURS = {
  cnc: 0xb8bdc4,
  sheet_metal: 0xc9ced4,
  composite_cut: 0x1b1e22,
  fdm: 0x3a3f45,
  injection: 0x2a2d31,
  stock: 0x23262b,
  purchased: 0x4a4f57,
};

export async function createViewer({ canvas, manifest, glbUrl, onProgress }) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.setClearColor(0x0e1013, 1);
  renderer.localClippingEnabled = true;

  // WebGL context loss is silent by design: no exception, no console
  // message, gl.* calls just become no-ops afterward. Without a listener
  // for it, the canvas simply goes black with nothing anywhere to debug --
  // confirmed against a real black-viewport report where the console
  // stayed completely empty across 30 reloads. Seen in practice on some
  // GPU/driver combinations under the burst of render passes
  // PMREMGenerator does a few lines down. Properly recovering a lost
  // context means re-uploading every texture/geometry/program; a reload is
  // simpler and reliable, so that's the response rather than in-place
  // restoration. Capped via sessionStorage so a machine with a genuinely
  // broken WebGL setup doesn't reload forever.
  const RELOAD_KEY = 'aeroframe_render_reload_count';
  const MAX_AUTO_RELOADS = 4;
  function recoverByReloading(reason, err) {
    clearTimeout(clearReloadCounterTimer); // a failure is in progress; don't let the clear race it
    const attempts = Number(sessionStorage.getItem(RELOAD_KEY) || '0');
    if (attempts >= MAX_AUTO_RELOADS) {
      console.error(
        `${reason}: still failing after ${MAX_AUTO_RELOADS} automatic reloads -- this looks ` +
          'like a persistent WebGL/driver issue on this machine, not a one-off glitch.',
        err
      );
      return;
    }
    sessionStorage.setItem(RELOAD_KEY, String(attempts + 1));
    console.error(
      `${reason} -- reloading (attempt ${attempts + 1}/${MAX_AUTO_RELOADS}) for a fresh WebGL context`,
      err
    );
    location.reload();
  }
  // Only clear the counter after the session has been rendering *stably*
  // for a while -- clearing it on the first successful frame was the bug in
  // an earlier version of this fix: a context loss minutes (or even just a
  // second) into an otherwise-fine session would wipe out the count from a
  // reload that was still in flight, turning the cap into an infinite
  // reload loop instead of stopping at MAX_AUTO_RELOADS (verified this
  // exact failure mode with a real WEBGL_lose_context call before fixing).
  let clearReloadCounterTimer = setTimeout(() => sessionStorage.removeItem(RELOAD_KEY), 5000);
  canvas.addEventListener('webglcontextlost', (event) => {
    event.preventDefault(); // required for the context to ever be restorable
    recoverByReloading('WebGL context lost', event);
  });

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(40, 1, 0.01, 100);
  camera.position.set(0.55, 0.4, 0.6);

  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

  const hemi = new THREE.HemisphereLight(0xffffff, 0x30343c, 1.1);
  scene.add(hemi);
  const key = new THREE.DirectionalLight(0xffffff, 2.4);
  key.position.set(2, 3, 2);
  scene.add(key);
  const rim = new THREE.DirectionalLight(0x99bbff, 0.6);
  rim.position.set(-2, 1, -2);
  scene.add(rim);

  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.minDistance = 0.15;
  controls.maxDistance = 3.0;
  controls.target.set(0, 0.05, 0);
  // Right-drag already pans (OrbitControls' default mouseButtons.RIGHT),
  // but that's not discoverable and awkward on a trackpad. Holding Shift
  // swaps the left button to pan too, without disturbing plain left-drag
  // orbit or the right-click convention for anyone who already uses it.
  // Reset on blur as well as keyup so a lost keyup (e.g. alt-tab while
  // Shift is held) can't leave the left button stuck in pan mode.
  window.addEventListener('keydown', (ev) => {
    if (ev.key === 'Shift') controls.mouseButtons.LEFT = THREE.MOUSE.PAN;
  });
  window.addEventListener('keyup', (ev) => {
    if (ev.key === 'Shift') controls.mouseButtons.LEFT = THREE.MOUSE.ROTATE;
  });
  window.addEventListener('blur', () => {
    controls.mouseButtons.LEFT = THREE.MOUSE.ROTATE;
  });

  const loader = new GLTFLoader();
  const gltf = await new Promise((resolve, reject) => {
    loader.load(
      glbUrl,
      resolve,
      (evt) => onProgress && onProgress(evt.loaded, evt.total),
      reject
    );
  });
  const root = gltf.scene;
  scene.add(root);

  const knownNodeIds = new Set(manifest.instances.map((i) => i.node_id));
  function nodeToPartKey(nodeId) {
    return (nodeId || '').split('__')[0];
  }

  // glTF import nests the actual mesh below the named node (verified against
  // this exact export pipeline), so identify a mesh's owning instance by
  // walking up through its ancestors until a name matches a known node_id.
  function findNodeId(mesh) {
    let o = mesh;
    while (o) {
      if (knownNodeIds.has(o.name)) return o.name;
      o = o.parent;
    }
    return null;
  }

  // node_id -> { mesh, home: {position, quaternion} }
  const nodes = new Map();
  root.traverse((obj) => {
    if (!obj.isMesh) return;
    const nodeId = findNodeId(obj);
    if (!nodeId) return;
    obj.userData.nodeId = nodeId;
    const mat = obj.material;
    if (mat) {
      mat.side = THREE.DoubleSide; // required for a clean cut face when sectioning
    }
    nodes.set(nodeId, {
      mesh: obj,
      home: { position: obj.position.clone(), quaternion: obj.quaternion.clone() },
      isolated: true,
    });
  });

  let selected = null;
  const selectCallbacks = [];
  const clipPlane = new THREE.Plane(new THREE.Vector3(1, 0, 0), 1000);
  let sectionAxis = null;
  let feaGroup = null;
  let feaHiddenNodeIds = null;

  function resize() {
    const w = canvas.clientWidth || canvas.parentElement.clientWidth;
    const h = canvas.clientHeight || canvas.parentElement.clientHeight;
    if (w === 0 || h === 0) return;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h, false);
  }
  new ResizeObserver(resize).observe(canvas.parentElement);
  resize();

  let raf = null;
  let renderFailures = 0;
  // An occasional genuine JS exception during render (distinct from the
  // silent context-loss case handled above) still gets a couple of cheap
  // in-place recompile attempts before falling back to the same reload path.
  const IN_PLACE_RETRY_LIMIT = 2;

  function renderLoop() {
    raf = requestAnimationFrame(renderLoop);
    controls.update();
    try {
      renderer.render(scene, camera);
      renderFailures = 0;
    } catch (err) {
      renderFailures += 1;
      if (renderFailures > IN_PLACE_RETRY_LIMIT) {
        cancelAnimationFrame(raf);
        recoverByReloading('renderLoop: render() kept throwing', err);
        return;
      }
      console.warn('renderLoop: render() threw, forcing a material recompile and retrying', err);
      scene.traverse((obj) => {
        if (obj.material) obj.material.needsUpdate = true;
      });
    }
  }
  renderLoop();

  // TEMPORARY diagnostic while tracking down an intermittent black-viewport
  // report: logs unconditionally a few seconds after load, whether or not
  // the drone is actually visible, so a failing session can be compared
  // against a working one using real numbers instead of a description.
  // Remove once that bug is confirmed fixed.
  setTimeout(() => {
    const gl = renderer.getContext();
    console.info('AeroFrame diag:', {
      canvasCssSize: [canvas.clientWidth, canvas.clientHeight],
      canvasDrawingBufferSize: [gl.drawingBufferWidth, gl.drawingBufferHeight],
      rendererDomElementSize: [renderer.domElement.width, renderer.domElement.height],
      devicePixelRatio: window.devicePixelRatio,
      rendererPixelRatio: renderer.getPixelRatio(),
      isContextLost: gl.isContextLost(),
      meshCount: nodes.size,
      sceneChildCount: scene.children.length,
      rootVisible: root.visible,
      cameraPositionX: camera.position.x,
      cameraPositionY: camera.position.y,
      cameraPositionZ: camera.position.z,
      cameraAspect: camera.aspect,
      rendererInfoCalls: renderer.info.render.calls,
      rendererInfoTriangles: renderer.info.render.triangles,
      rafActive: raf !== null,
    });
  }, 3000);

  function setEmissive(nodeId, color) {
    const n = nodes.get(nodeId);
    if (!n || !n.mesh.material || !n.mesh.material.emissive) return;
    n.mesh.material.emissive.copy(color);
  }

  // Eased camera/target animation shared by flyTo() and resetView().
  function animateCameraTo(targetPos, targetLookAt, ms) {
    if (ms <= 0) {
      // Dividing (now - t0) by ms unconditionally used to live here; t0 and
      // the first performance.now() read inside step() can land in the same
      // quantised timer tick (browsers deliberately coarsen its
      // resolution), making that division 0/0 = NaN, which lerpVectors then
      // baked permanently into camera.position with no error and no
      // recovery -- confirmed as the actual cause of an intermittent
      // black-viewport report. An instant jump is what ms=0 means anyway.
      camera.position.copy(targetPos);
      controls.target.copy(targetLookAt);
      return;
    }
    const startPos = camera.position.clone();
    const startTarget = controls.target.clone();
    const t0 = performance.now();
    function step() {
      const t = Math.min(1, (performance.now() - t0) / ms);
      const e = 1 - Math.pow(1 - t, 3);
      camera.position.lerpVectors(startPos, targetPos, e);
      controls.target.lerpVectors(startTarget, targetLookAt, e);
      if (t < 1) requestAnimationFrame(step);
    }
    step();
  }
  // Captured once, right after the initial flyTo(null, 0) call at the
  // bottom of this function -- see resetView() above.
  let defaultCameraPos = null;
  let defaultCameraTarget = null;

  const api = {
    setExplode(t) {
      for (const [, n] of nodes) {
        const inst = manifest.instances.find((i) => i.node_id === n.mesh.userData.nodeId);
        if (!inst) continue;
        const explodeDistM = (manifest.meta.explode_distance_mm ?? 120) / 1000;
        const dist = inst.explode_rank * explodeDistM * t;
        const [dx, dy, dz] = inst.explode_dir;
        // explode_dir is in CAD (Z-up) space; the glb root already carries the
        // Z-up -> Y-up axis fix, so map it the same way here.
        const move = new THREE.Vector3(dx, dz, -dy).multiplyScalar(dist);
        n.mesh.position.copy(n.home.position).add(move);
      }
    },

    setSection(axis, position) {
      if (!axis || axis === 'off') {
        sectionAxis = null;
        for (const [, n] of nodes) n.mesh.material && (n.mesh.material.clippingPlanes = null);
        return;
      }
      sectionAxis = axis;
      const normalMap = { x: [1, 0, 0], y: [0, 1, 0], z: [0, 0, 1] };
      clipPlane.normal.set(...normalMap[axis]);
      const box = new THREE.Box3().setFromObject(root);
      const size = box.getSize(new THREE.Vector3());
      const center = box.getCenter(new THREE.Vector3());
      const extent = { x: size.x, y: size.y, z: size.z }[axis];
      const c = { x: center.x, y: center.y, z: center.z }[axis];
      clipPlane.constant = -(c - extent / 2 + extent * position);
      for (const [, n] of nodes) {
        if (n.mesh.material) n.mesh.material.clippingPlanes = [clipPlane];
      }
    },

    setColourMode(mode) {
      for (const [nodeId, n] of nodes) {
        const partKey = nodeToPartKey(nodeId);
        const part = manifest.parts[partKey];
        if (!part || !n.mesh.material) continue;
        if (mode === 'process') {
          const hex = PROCESS_COLOURS[part.process_key] ?? 0x888888;
          n.mesh.material.color.setHex(hex);
        } else if (mode === 'material') {
          const mat = manifest.materials[part.material_key];
          if (mat) n.mesh.material.color.set(mat.colour);
        }
        // 'stress' mode is applied by showFea(), not here.
      }
    },

    select(nodeId) {
      if (selected) setEmissive(selected, new THREE.Color(0, 0, 0));
      selected = nodeId;
      if (nodeId) setEmissive(nodeId, new THREE.Color(0x1a3a5c));
      selectCallbacks.forEach((cb) => cb(nodeId));
    },

    isolate(partKeys) {
      const all = partKeys.length === 0;
      for (const [nodeId, n] of nodes) {
        const partKey = nodeToPartKey(nodeId);
        const on = all || partKeys.includes(partKey);
        n.isolated = on;
        if (n.mesh.material) n.mesh.material.opacity = on ? 1.0 : 0.06;
        if (n.mesh.material) n.mesh.material.transparent = !on;
      }
    },

    setVisible(nodeId, visible) {
      const n = nodes.get(nodeId);
      if (n) n.mesh.visible = visible;
    },

    flyTo(nodeId, ms = 600) {
      let box;
      if (nodeId && nodes.has(nodeId)) {
        box = new THREE.Box3().setFromObject(nodes.get(nodeId).mesh);
      } else {
        box = new THREE.Box3().setFromObject(root);
      }
      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3()).length();
      const dist = Math.max(size * 1.6, 0.08);
      const dir = new THREE.Vector3(0.6, 0.45, 0.65).normalize();
      const targetPos = center.clone().add(dir.multiplyScalar(dist));
      animateCameraTo(targetPos, center, ms);
    },

    // Jumps the orbit/pan/zoom state back to the framing captured right
    // after the very first flyTo(null, 0) at the bottom of createViewer --
    // deliberately a fixed snapshot, not a recomputed fit, so it stays the
    // same regardless of the current explode/section/isolate state (those
    // have their own controls and are left untouched here on purpose).
    resetView(ms = 600) {
      animateCameraTo(defaultCameraPos, defaultCameraTarget, ms);
    },

    async showFea(caseKey) {
      // Clear any existing overlay and restore whatever it hid.
      if (feaGroup) {
        scene.remove(feaGroup);
        feaGroup.traverse((o) => {
          if (o.geometry) o.geometry.dispose();
          if (o.material) o.material.dispose();
        });
        feaGroup = null;
      }
      if (feaHiddenNodeIds) {
        for (const nid of feaHiddenNodeIds) {
          const n = nodes.get(nid);
          if (n) n.mesh.visible = true;
        }
        feaHiddenNodeIds = null;
      }
      if (!caseKey) {
        const legendEl = document.getElementById('fea-legend');
        if (legendEl) legendEl.hidden = true;
        return;
      }

      const feaCase = (manifest.analysis.fea || []).find((f) => f.key === caseKey);
      if (!feaCase) return;

      // Hide every instance of the analysed part while its stress overlay
      // is showing — the FEA result glb is one representative solve, not
      // per-instance, so it stands in for all of them at once.
      feaHiddenNodeIds = [];
      for (const [nodeId, n] of nodes) {
        if (nodeToPartKey(nodeId) === feaCase.part_key) {
          n.mesh.visible = false;
          feaHiddenNodeIds.push(nodeId);
        }
      }

      let gltf;
      try {
        gltf = await new Promise((resolve, reject) => {
          loader.load(`assets/${feaCase.result_glb}`, resolve, undefined, reject);
        });
      } catch (err) {
        console.error('showFea: failed to load result glb', feaCase.result_glb, err);
        return;
      }
      const overlay = gltf.scene;
      overlay.traverse((o) => {
        if (o.isMesh && o.material) o.material.vertexColors = true;
      });

      // Position at the first instance of this part, using the exact same
      // mm-local -> vehicle -> glTF composition gltf.py applies on export
      // (axis fix -90 deg about X, then mm->m scale) so the overlay lands
      // exactly where the original geometry was.
      const inst = manifest.instances.find((i) => i.part_key === feaCase.part_key);
      if (inst) {
        const m = inst.transform_mm;
        const local = new THREE.Matrix4().set(
          m[0][0], m[0][1], m[0][2], m[0][3],
          m[1][0], m[1][1], m[1][2], m[1][3],
          m[2][0], m[2][1], m[2][2], m[2][3],
          m[3][0], m[3][1], m[3][2], m[3][3]
        );
        const axisFix = new THREE.Matrix4().set(
          1, 0, 0, 0,
          0, 0, 1, 0,
          0, -1, 0, 0,
          0, 0, 0, 1
        );
        const gltfScale = 0.001; // mm -> m, matches SPEC.export.gltf_scale
        const world = new THREE.Matrix4().multiplyMatrices(axisFix, local);
        world.premultiply(new THREE.Matrix4().makeScale(gltfScale, gltfScale, gltfScale));
        overlay.matrix.copy(world);
        overlay.matrixAutoUpdate = false;
      }

      scene.add(overlay);
      feaGroup = overlay;

      const legend = document.getElementById('fea-legend');
      const legendMin = document.getElementById('legend-min');
      const legendMax = document.getElementById('legend-max');
      if (legend && feaCase.legend) {
        legend.hidden = false;
        if (legendMin) legendMin.textContent = feaCase.legend.min_mpa.toFixed(0);
        if (legendMax) legendMax.textContent = `${feaCase.legend.max_mpa.toFixed(1)} MPa`;
      }
    },

    onSelect(cb) {
      selectCallbacks.push(cb);
    },

    dispose() {
      cancelAnimationFrame(raf);
      renderer.dispose();
    },

    // Exposed for ui.js hit-testing and hotspot projection.
    _internal: { scene, camera, renderer, controls, root, nodes, nodeToPartKey },
  };

  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  canvas.addEventListener('click', (ev) => {
    const rect = canvas.getBoundingClientRect();
    pointer.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);
    const hits = raycaster.intersectObject(root, true);
    if (hits.length > 0) {
      let obj = hits[0].object;
      while (obj && !obj.userData.nodeId) obj = obj.parent;
      api.select(obj ? obj.userData.nodeId : null);
    } else {
      api.select(null);
    }
  });

  api.flyTo(null, 0);
  defaultCameraPos = camera.position.clone();
  defaultCameraTarget = controls.target.clone();
  return api;
}
