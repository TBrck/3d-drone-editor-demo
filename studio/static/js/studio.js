/* Parts & assembly studio: primitive editor, live preview, placement gizmo.
 *
 * The 3D view has two layers in the same scene: a read-only backdrop (the
 * real, published assembly, loaded via the exact same createViewer() the
 * main site uses) and one editable preview mesh for whichever custom part
 * is currently being created/edited. The preview's geometry always comes
 * from the server (POST /api/preview -> build_from_shape_spec -> a small
 * GLB) rather than an in-browser CSG engine, so it can never disagree with
 * what a real rebuild produces -- see studio/api.py's preview() docstring.
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { TransformControls } from 'three/addons/controls/TransformControls.js';
import { createViewer } from '/context/viewer.js';

let manifest = null;
let viewer = null;
let scene, camera, renderer, controls;
let previewGroup = null; // THREE.Group holding the loaded preview mesh
let gizmo = null;
let gizmoEnabled = false;

let editingKey = null; // null = creating a new part
let primitives = []; // [{id, type, dims:{}, transform:{translate_mm, rotate_deg}, booleanOp}]
let primitiveIdSeq = 0;
let previewDebounceTimer = null;

const glbLoader = new GLTFLoader();

// ------------------------------------------------------------------ boot --

async function boot() {
  const manifestResp = await fetch('/context/assets/manifest.json');
  manifest = await manifestResp.json();

  const canvas = document.getElementById('canvas');
  viewer = await createViewer({
    canvas,
    manifest,
    glbUrl: '/context/assets/drone.glb',
    onProgress: () => {},
  });
  ({ scene, camera, renderer, controls } = viewer._internal);

  populateSelect('f-material', manifest.materials);
  populateSelect('f-process', manifest.processes);

  wireStaticControls();
  await refreshPartsList();
}

function populateSelect(id, dict) {
  const el = document.getElementById(id);
  el.innerHTML = '';
  for (const key of Object.keys(dict)) {
    const opt = document.createElement('option');
    opt.value = key;
    opt.textContent = dict[key].name || key;
    el.appendChild(opt);
  }
}

// ------------------------------------------------------------ parts list --

async function refreshPartsList() {
  const resp = await fetch('/api/parts');
  const parts = await resp.json();
  const list = document.getElementById('parts-list');
  list.innerHTML = '';
  for (const spec of parts) {
    const li = document.createElement('li');
    li.dataset.key = spec.key;
    li.innerHTML = `<span>${spec.name}</span><span class="part-key">${spec.key}</span>`;
    li.addEventListener('click', () => loadPartIntoEditor(spec));
    if (spec.key === editingKey) li.classList.add('is-active');
    list.appendChild(li);
  }
}

// -------------------------------------------------------------- editing --

function wireStaticControls() {
  document.getElementById('new-part-btn').addEventListener('click', () => startNewPart());
  document.getElementById('cancel-btn').addEventListener('click', () => closeEditor());
  document.getElementById('save-btn').addEventListener('click', () => savePart());
  document.getElementById('delete-btn').addEventListener('click', () => deletePart());
  document.getElementById('rebuild-btn').addEventListener('click', () => rebuild());
  document.querySelectorAll('[data-gizmo-mode]').forEach((btn) => {
    btn.addEventListener('click', () => setGizmoMode(btn.dataset.gizmoMode));
  });

  document.querySelectorAll('[data-add-primitive]').forEach((btn) => {
    btn.addEventListener('click', () => addPrimitive(btn.dataset.addPrimitive));
  });

  for (const id of ['f-material', 'f-mass-override']) {
    document.getElementById(id).addEventListener('change', updateMassOverrideVisibility);
  }
  document.getElementById('f-material').addEventListener('change', updateMassOverrideVisibility);

  for (const id of ['f-pos-x', 'f-pos-y', 'f-pos-z', 'f-rot-x', 'f-rot-y', 'f-rot-z']) {
    document.getElementById(id).addEventListener('input', () => applyPlacementToPreview());
  }
}

function startNewPart() {
  editingKey = null;
  primitives = [];
  setGizmoMode('off');
  document.getElementById('editor-heading').textContent = 'New part';
  document.getElementById('delete-btn').classList.add('is-hidden');
  for (const id of ['f-key', 'f-name', 'f-summary', 'f-design-notes']) document.getElementById(id).value = '';
  document.getElementById('f-key').disabled = false;
  document.getElementById('f-quantity').value = 1;
  document.getElementById('f-critical').checked = false;
  document.getElementById('f-mass-override').value = '';
  for (const id of ['f-pos-x', 'f-pos-y', 'f-pos-z', 'f-rot-x', 'f-rot-y', 'f-rot-z']) {
    document.getElementById(id).value = 0;
  }
  renderPrimitiveList();
  updateMassOverrideVisibility();
  clearFormErrors();
  document.getElementById('editor-section').classList.remove('is-hidden');
  schedulePreview();
}

function loadPartIntoEditor(spec) {
  editingKey = spec.key;
  setGizmoMode('off');
  document.getElementById('editor-heading').textContent = `Edit: ${spec.name}`;
  document.getElementById('delete-btn').classList.remove('is-hidden');
  document.getElementById('f-key').value = spec.key;
  document.getElementById('f-key').disabled = true; // keys are immutable once saved
  document.getElementById('f-name').value = spec.name;
  document.getElementById('f-material').value = spec.material_key;
  document.getElementById('f-process').value = spec.process_key;
  document.getElementById('f-quantity').value = spec.quantity ?? 1;
  document.getElementById('f-critical').checked = !!spec.critical;
  document.getElementById('f-mass-override').value = spec.mass_override_g ?? '';
  document.getElementById('f-summary').value = spec.summary ?? '';
  document.getElementById('f-design-notes').value = (spec.design_notes ?? []).join('\n');

  const p = spec.placement ?? {};
  const pos = p.position_mm ?? [0, 0, 0];
  const rot = p.rotation_deg ?? [0, 0, 0];
  document.getElementById('f-pos-x').value = pos[0];
  document.getElementById('f-pos-y').value = pos[1];
  document.getElementById('f-pos-z').value = pos[2];
  document.getElementById('f-rot-x').value = rot[0];
  document.getElementById('f-rot-y').value = rot[1];
  document.getElementById('f-rot-z').value = rot[2];

  primitives = shapeTreeToPrimitives(spec.shape);
  renderPrimitiveList();
  updateMassOverrideVisibility();
  clearFormErrors();
  document.getElementById('editor-section').classList.remove('is-hidden');
  refreshPartsList();
  schedulePreview();
}

function closeEditor() {
  editingKey = null;
  document.getElementById('editor-section').classList.add('is-hidden');
  clearPreview();
  disableGizmo();
  refreshPartsList();
}

function updateMassOverrideVisibility() {
  const isCots = document.getElementById('f-material').value === 'cots';
  document.getElementById('f-mass-override-row').classList.toggle('is-hidden', !isCots);
}

// --------------------------------------------------------- primitive UI --

const PRIMITIVE_DEFAULTS = {
  box: { length_mm: 20, width_mm: 20, height_mm: 5 },
  cylinder: { radius_mm: 5, height_mm: 10 },
  sphere: { radius_mm: 5 },
};

function addPrimitive(type) {
  primitives.push({
    id: primitiveIdSeq++,
    type,
    dims: { ...PRIMITIVE_DEFAULTS[type] },
    translate_mm: [0, 0, 0],
    rotate_deg: [0, 0, 0],
    booleanOp: 'union',
  });
  renderPrimitiveList();
  schedulePreview();
}

function removePrimitive(id) {
  primitives = primitives.filter((p) => p.id !== id);
  renderPrimitiveList();
  schedulePreview();
}

function renderPrimitiveList() {
  const container = document.getElementById('primitive-list');
  container.innerHTML = '';
  primitives.forEach((prim, index) => {
    container.appendChild(renderPrimitiveCard(prim, index));
  });
}

function renderPrimitiveCard(prim, index) {
  const card = document.createElement('div');
  card.className = 'primitive-card';

  const head = document.createElement('div');
  head.className = 'primitive-card__head';
  const title = document.createElement('span');
  title.className = 'primitive-card__title';
  title.textContent = `${index + 1}. ${prim.type}`;
  const removeBtn = document.createElement('button');
  removeBtn.className = 'primitive-card__remove';
  removeBtn.textContent = '×';
  removeBtn.title = 'Remove';
  removeBtn.addEventListener('click', () => removePrimitive(prim.id));
  head.appendChild(title);
  head.appendChild(removeBtn);
  card.appendChild(head);

  if (index > 0) {
    const opRow = document.createElement('label');
    opRow.textContent = 'Combine with the shape so far';
    const opSelect = document.createElement('select');
    for (const op of ['union', 'subtract', 'intersect']) {
      const o = document.createElement('option');
      o.value = op;
      o.textContent = op;
      if (op === prim.booleanOp) o.selected = true;
      opSelect.appendChild(o);
    }
    opSelect.addEventListener('change', () => {
      prim.booleanOp = opSelect.value;
      schedulePreview();
    });
    opRow.appendChild(opSelect);
    card.appendChild(opRow);
  }

  const dimGrid = document.createElement('div');
  dimGrid.className = 'field-grid';
  for (const dimKey of Object.keys(PRIMITIVE_DEFAULTS[prim.type])) {
    dimGrid.appendChild(
      numberField(dimKey.replace('_mm', ' (mm)'), prim.dims[dimKey], (v) => {
        prim.dims[dimKey] = v;
        schedulePreview();
      })
    );
  }
  card.appendChild(dimGrid);

  const xformGrid = document.createElement('div');
  xformGrid.className = 'field-grid';
  ['X', 'Y', 'Z'].forEach((axis, i) => {
    xformGrid.appendChild(
      numberField(`translate ${axis} (mm)`, prim.translate_mm[i], (v) => {
        prim.translate_mm[i] = v;
        schedulePreview();
      })
    );
  });
  ['X', 'Y', 'Z'].forEach((axis, i) => {
    xformGrid.appendChild(
      numberField(`rotate ${axis} (deg)`, prim.rotate_deg[i], (v) => {
        prim.rotate_deg[i] = v;
        schedulePreview();
      })
    );
  });
  card.appendChild(xformGrid);

  return card;
}

function numberField(labelText, value, onChange) {
  const label = document.createElement('label');
  label.textContent = labelText;
  const input = document.createElement('input');
  input.type = 'number';
  input.step = 'any';
  input.value = value;
  input.addEventListener('input', () => onChange(parseFloat(input.value) || 0));
  label.appendChild(input);
  return label;
}

// --------------------------------------------------- shape tree building --

function primitiveToNode(prim) {
  return {
    op: prim.type,
    ...prim.dims,
    transform: { translate_mm: prim.translate_mm, rotate_deg: prim.rotate_deg },
  };
}

function buildShapeTree() {
  if (primitives.length === 0) return null;
  let acc = primitiveToNode(primitives[0]);
  for (let i = 1; i < primitives.length; i++) {
    acc = { op: primitives[i].booleanOp, children: [acc, primitiveToNode(primitives[i])] };
  }
  return acc;
}

/** The inverse of buildShapeTree(), for loading an existing part back into
 * the flat primitive-list UI. Only understands the left-leaning chain
 * buildShapeTree() itself produces (or an equally flat single primitive) --
 * a hand-edited custom_parts.json with a differently-shaped tree (e.g.
 * branching on both sides of a boolean) can still be *built* by the
 * server's interpreter, it just won't round-trip into this editor's UI;
 * the raw JSON is always the source of truth, this is only a convenience. */
function shapeTreeToPrimitives(node) {
  if (!node) return [];
  const isPrimitive = (n) => n.op in PRIMITIVE_DEFAULTS;
  const chain = [];
  let cursor = node;
  while (cursor && !isPrimitive(cursor)) {
    const [left, right] = cursor.children || [];
    if (!right) break;
    chain.unshift({ node: right, op: cursor.op });
    cursor = left;
  }
  const result = [];
  if (cursor && isPrimitive(cursor)) result.push(nodeToPrimitive(cursor, 'union'));
  for (const { node: n, op } of chain) result.push(nodeToPrimitive(n, op));
  return result;
}

function nodeToPrimitive(node, booleanOp) {
  const t = node.transform || {};
  const dims = {};
  for (const k of Object.keys(PRIMITIVE_DEFAULTS[node.op] || {})) dims[k] = node[k];
  return {
    id: primitiveIdSeq++,
    type: node.op,
    dims,
    translate_mm: t.translate_mm || [0, 0, 0],
    rotate_deg: t.rotate_deg || [0, 0, 0],
    booleanOp,
  };
}

// ----------------------------------------------------------- live preview --

function schedulePreview() {
  clearTimeout(previewDebounceTimer);
  previewDebounceTimer = setTimeout(updatePreview, 400);
}

async function updatePreview() {
  const shape = buildShapeTree();
  if (!shape) {
    clearPreview();
    return;
  }
  let resp;
  try {
    resp = await fetch('/api/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ shape }),
    });
  } catch (e) {
    return; // network hiccup -- leave the last good preview in place
  }
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    showFormNote(body.error || 'Preview failed');
    return;
  }
  clearFormErrors();
  const buffer = await resp.arrayBuffer();
  glbLoader.parse(buffer, '', (gltf) => {
    clearPreview();
    previewGroup = gltf.scene;
    previewGroup.traverse((o) => {
      if (o.isMesh) {
        o.material = new THREE.MeshStandardMaterial({ color: 0x4da3ff, metalness: 0.2, roughness: 0.5 });
      }
    });
    scene.add(previewGroup);
    applyPlacementToPreview();
    if (gizmo) gizmo.attach(previewGroup);
  });
}

function clearPreview() {
  if (previewGroup) {
    scene.remove(previewGroup);
    previewGroup.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) o.material.dispose();
    });
    previewGroup = null;
  }
}

function currentPlacement() {
  return {
    position_mm: [
      parseFloat(document.getElementById('f-pos-x').value) || 0,
      parseFloat(document.getElementById('f-pos-y').value) || 0,
      parseFloat(document.getElementById('f-pos-z').value) || 0,
    ],
    rotation_deg: [
      parseFloat(document.getElementById('f-rot-x').value) || 0,
      parseFloat(document.getElementById('f-rot-y').value) || 0,
      parseFloat(document.getElementById('f-rot-z').value) || 0,
    ],
  };
}

/** Vehicle-space (mm, CAD Z-up) position/rotation -> this viewer's Y-up
 * metres scene graph. Mirrors viewer.js's own axis-fix + mm->m convention
 * (see AeroFrame's export/gltf.py _AXIS_FIX docstring for why this
 * specific mapping) so the preview lines up with the read-only backdrop. */
function applyPlacementToPreview() {
  if (!previewGroup) return;
  const { position_mm, rotation_deg } = currentPlacement();
  const [x, y, z] = position_mm;
  previewGroup.position.set(x / 1000, z / 1000, -y / 1000);
  const [rx, ry, rz] = rotation_deg.map((d) => (d * Math.PI) / 180);
  previewGroup.rotation.set(rx, rz, -ry, 'XZY');
}

function showFormNote(message) {
  const box = document.getElementById('form-errors');
  box.classList.remove('is-hidden');
  box.innerHTML = `<p>${message}</p>`;
}

function clearFormErrors() {
  const box = document.getElementById('form-errors');
  box.classList.add('is-hidden');
  box.innerHTML = '';
}

// ----------------------------------------------------------------- gizmo --

function setGizmoMode(mode) {
  document.querySelectorAll('[data-gizmo-mode]').forEach((btn) => {
    btn.classList.toggle('btn', btn.dataset.gizmoMode === mode);
    btn.classList.toggle('btn--ghost', btn.dataset.gizmoMode !== mode);
  });
  if (mode === 'off') {
    disableGizmo();
    return;
  }
  if (!previewGroup) return;
  if (!gizmo) {
    gizmo = new TransformControls(camera, renderer.domElement);
    gizmo.addEventListener('dragging-changed', (ev) => {
      controls.enabled = !ev.value;
    });
    gizmo.addEventListener('objectChange', () => syncFieldsFromGizmo());
    gizmo.attach(previewGroup);
    scene.add(gizmo.getHelper ? gizmo.getHelper() : gizmo);
    gizmoEnabled = true;
  }
  gizmo.setMode(mode);
}

function disableGizmo() {
  if (gizmo) {
    scene.remove(gizmo.getHelper ? gizmo.getHelper() : gizmo);
    gizmo.dispose();
    gizmo = null;
  }
  gizmoEnabled = false;
}

/** Gizmo drag -> placement fields, inverse of applyPlacementToPreview(). */
function syncFieldsFromGizmo() {
  if (!previewGroup) return;
  const x_mm = previewGroup.position.x * 1000;
  const z_mm = previewGroup.position.y * 1000;
  const y_mm = -previewGroup.position.z * 1000;
  document.getElementById('f-pos-x').value = x_mm.toFixed(2);
  document.getElementById('f-pos-y').value = y_mm.toFixed(2);
  document.getElementById('f-pos-z').value = z_mm.toFixed(2);
  // Rotation gizmo drags are read back via the same 'XZY' Euler order used
  // to set them, so the round trip is exact for rotations the gizmo itself
  // produced (translate mode, the default, never touches rotation at all).
  const e = previewGroup.rotation;
  document.getElementById('f-rot-x').value = ((e.x * 180) / Math.PI).toFixed(2);
  document.getElementById('f-rot-y').value = ((-e.z * 180) / Math.PI).toFixed(2);
  document.getElementById('f-rot-z').value = ((e.y * 180) / Math.PI).toFixed(2);
}

// ------------------------------------------------------------ save/delete --

function collectSpec() {
  const designNotes = document
    .getElementById('f-design-notes')
    .value.split('\n')
    .map((s) => s.trim())
    .filter(Boolean);
  const materialKey = document.getElementById('f-material').value;
  const massOverrideRaw = document.getElementById('f-mass-override').value;

  return {
    key: document.getElementById('f-key').value.trim(),
    name: document.getElementById('f-name').value.trim(),
    material_key: materialKey,
    process_key: document.getElementById('f-process').value,
    quantity: parseInt(document.getElementById('f-quantity').value, 10) || 1,
    critical: document.getElementById('f-critical').checked,
    mass_override_g: massOverrideRaw === '' ? null : parseFloat(massOverrideRaw),
    summary: document.getElementById('f-summary').value.trim(),
    design_notes: designNotes,
    shape: buildShapeTree(),
    placement: { group: 'custom', ...currentPlacement(), explode_dir: [0, 0, 1], explode_rank: 1 },
  };
}

async function savePart() {
  const spec = collectSpec();
  if (!spec.shape) {
    showFormNote('Add at least one primitive first.');
    return;
  }
  const isEdit = editingKey !== null;
  const url = isEdit ? `/api/parts/${editingKey}` : '/api/parts';
  const method = isEdit ? 'PUT' : 'POST';
  const resp = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(spec),
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({ errors: [{ field: '', message: 'Save failed' }] }));
    renderFormErrors(body.errors || []);
    return;
  }
  clearFormErrors();
  await refreshPartsList();
  closeEditor();
}

async function deletePart() {
  if (!editingKey) return;
  if (!confirm(`Delete ${editingKey}? This also removes any exported downloads/drawings for it.`)) return;
  await fetch(`/api/parts/${editingKey}`, { method: 'DELETE' });
  closeEditor();
}

function renderFormErrors(errors) {
  const box = document.getElementById('form-errors');
  box.classList.remove('is-hidden');
  if (errors.length === 0) {
    box.innerHTML = '<p>Save failed.</p>';
    return;
  }
  const items = errors.map((e) => `<li><strong>${e.field}:</strong> ${e.message}</li>`).join('');
  box.innerHTML = `<ul>${items}</ul>`;
}

// -------------------------------------------------------------- rebuild --

async function rebuild() {
  const output = document.getElementById('rebuild-output');
  output.classList.remove('is-hidden');
  output.textContent = 'Rebuilding...';
  const resp = await fetch('/api/rebuild', { method: 'POST' });
  const body = await resp.json();
  output.textContent = (body.stdout || '') + (body.stderr || '') || (body.ok ? 'Done.' : 'Rebuild failed.');
}

boot();
