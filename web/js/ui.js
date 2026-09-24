/* Panel, part tree, detail card, tabs, controls, deep links.
 *
 * All content comes from the manifest. There are no design strings in this
 * file — a number hard-coded here would silently stop matching the CAD the
 * first time a parameter changes.
 */

function fmt(n, digits = 1) {
  if (n === null || n === undefined) return '—';
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

export function mountUI({ viewer, manifest }) {
  mountTabs();
  mountTree(viewer, manifest);
  mountControls(viewer, manifest);
  mountDetail(viewer, manifest);
  mountStory(viewer, manifest);
  mountHash(viewer, manifest);
}

// ---------------------------------------------------------------- tabs ---

function mountTabs() {
  const tabs = document.querySelectorAll('.tab');
  const views = document.querySelectorAll('.view');
  tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      tabs.forEach((t) => t.classList.remove('is-active'));
      views.forEach((v) => v.classList.remove('is-active'));
      tab.classList.add('is-active');
      const view = tab.dataset.view;
      document.querySelector(`.view[data-view="${view}"]`)?.classList.add('is-active');
    });
  });
}

// ---------------------------------------------------------------- tree ---

function mountTree(viewer, manifest) {
  const root = document.getElementById('tree');
  if (!root) return;

  const byGroup = new Map();
  for (const inst of manifest.instances) {
    if (!byGroup.has(inst.group)) byGroup.set(inst.group, new Map());
    const byPart = byGroup.get(inst.group);
    if (!byPart.has(inst.part_key)) byPart.set(inst.part_key, []);
    byPart.get(inst.part_key).push(inst);
  }

  const groupOrder = ['arm_0', 'arm_1', 'arm_2', 'arm_3', 'frame'];
  const groupLabels = {
    arm_0: 'Arm 1', arm_1: 'Arm 2', arm_2: 'Arm 3', arm_3: 'Arm 4', frame: 'Frame',
  };

  for (const group of groupOrder) {
    const byPart = byGroup.get(group);
    if (!byPart) continue;
    const details = document.createElement('details');
    details.className = 'tree__group';
    details.open = group === 'frame';
    const summary = document.createElement('summary');
    summary.textContent = groupLabels[group] ?? group;
    details.appendChild(summary);

    for (const [partKey, instances] of byPart) {
      const part = manifest.parts[partKey];
      if (!part) continue;
      const mat = manifest.materials[part.material_key];
      const row = document.createElement('div');
      row.className = 'tree__item';
      row.dataset.partKey = partKey;

      const swatch = document.createElement('span');
      swatch.className = 'tree__swatch';
      swatch.style.background = mat ? mat.colour : '#888';
      row.appendChild(swatch);

      const name = document.createElement('span');
      name.className = 'tree__name';
      name.textContent = part.name;
      row.appendChild(name);

      const qty = document.createElement('span');
      qty.className = 'tree__qty';
      qty.textContent = `x${instances.length}`;
      row.appendChild(qty);

      row.addEventListener('click', () => {
        const firstNode = instances[0].node_id;
        viewer.select(firstNode);
        viewer.flyTo(firstNode);
        document.querySelectorAll('.tree__item').forEach((el) => el.classList.remove('is-selected'));
        row.classList.add('is-selected');
      });

      details.appendChild(row);
    }
    root.appendChild(details);
  }

  viewer.onSelect((nodeId) => {
    document.querySelectorAll('.tree__item').forEach((el) => el.classList.remove('is-selected'));
    if (!nodeId) return;
    const partKey = nodeId.split('__')[0];
    const row = root.querySelector(`.tree__item[data-part-key="${partKey}"]`);
    if (row) row.classList.add('is-selected');
  });
}

// ------------------------------------------------------------ controls ---

function mountControls(viewer, manifest) {
  document.getElementById('reset-view')?.addEventListener('click', () => viewer.resetView());

  const explode = document.getElementById('explode');
  if (explode) {
    let pending = false;
    explode.addEventListener('input', () => {
      if (pending) return;
      pending = true;
      requestAnimationFrame(() => {
        viewer.setExplode(Number(explode.value) / 100);
        pending = false;
      });
    });
  }

  const section = document.getElementById('section');
  const axisChips = document.querySelectorAll('[data-section-axis]');
  let currentAxis = 'off';
  axisChips.forEach((chip) => {
    chip.addEventListener('click', () => {
      axisChips.forEach((c) => c.classList.remove('is-active'));
      chip.classList.add('is-active');
      currentAxis = chip.dataset.sectionAxis;
      viewer.setSection(currentAxis === 'off' ? null : currentAxis, Number(section.value) / 100);
    });
  });
  if (section) {
    section.addEventListener('input', () => {
      if (currentAxis !== 'off') viewer.setSection(currentAxis, Number(section.value) / 100);
    });
  }

  const colourChips = document.querySelectorAll('[data-colour]');
  colourChips.forEach((chip) => {
    chip.addEventListener('click', () => {
      colourChips.forEach((c) => c.classList.remove('is-active'));
      chip.classList.add('is-active');
      const mode = chip.dataset.colour;
      if (mode === 'stress') {
        const firstCase = (manifest.analysis.fea || [])[0];
        if (firstCase) {
          viewer.showFea(firstCase.key);
        } else {
          viewer.setColourMode('material');
        }
      } else {
        viewer.showFea(null);
        viewer.setColourMode(mode);
      }
    });
  });
}

// -------------------------------------------------------------- detail ---

function mountDetail(viewer, manifest) {
  const panel = document.getElementById('detail');
  const closeBtn = document.getElementById('detail-close');
  if (!panel) return;

  closeBtn?.addEventListener('click', () => viewer.select(null));

  viewer.onSelect((nodeId) => {
    if (!nodeId) {
      panel.hidden = true;
      return;
    }
    const partKey = nodeId.split('__')[0];
    const part = manifest.parts[partKey];
    if (!part) {
      panel.hidden = true;
      return;
    }
    const mat = manifest.materials[part.material_key];
    const proc = manifest.processes[part.process_key];

    document.getElementById('detail-name').textContent = part.name;
    document.getElementById('detail-summary').textContent = part.summary;

    const specs = document.getElementById('detail-specs');
    specs.innerHTML = '';
    const rows = [
      ['Material', mat ? mat.name : part.material_key],
      ['Process', proc ? proc.name : part.process_key],
      ['Quantity', String(part.quantity)],
      ['Unit mass', `${fmt(part.unit_mass_g)} g`],
      ['Total mass', `${fmt(part.total_mass_g)} g`],
      ['Tolerance', proc ? `± ${fmt(proc.typical_tolerance_mm, 2)} mm` : '—'],
    ];
    for (const [k, v] of rows) {
      const dt = document.createElement('dt');
      dt.textContent = k;
      const dd = document.createElement('dd');
      dd.textContent = v;
      specs.appendChild(dt);
      specs.appendChild(dd);
    }

    const notes = document.getElementById('detail-notes');
    notes.innerHTML = '';
    for (const note of part.design_notes) {
      const li = document.createElement('li');
      li.textContent = note;
      notes.appendChild(li);
    }

    panel.hidden = false;
  });
}

// --------------------------------------------------------------- story ---

function mountStory(viewer, manifest) {
  const story = manifest.story ?? [];
  const el = document.getElementById('story');
  const titleEl = document.getElementById('story-title');
  const bodyEl = document.getElementById('story-body');
  const dotsEl = document.getElementById('story-dots');
  const prevBtn = document.getElementById('story-prev');
  const nextBtn = document.getElementById('story-next');
  const exitBtn = document.getElementById('story-exit');
  if (!el || story.length === 0) {
    if (el) el.classList.add('is-hidden');
    return;
  }

  let index = 0;
  let manualOverride = false;

  dotsEl.innerHTML = '';
  story.forEach(() => {
    const dot = document.createElement('i');
    dotsEl.appendChild(dot);
  });

  function render() {
    const step = story[index];
    titleEl.textContent = step.title;
    bodyEl.textContent = step.body;
    [...dotsEl.children].forEach((d, i) => d.classList.toggle('is-active', i === index));
    prevBtn.disabled = index === 0;
    nextBtn.textContent = index === story.length - 1 ? 'Explore freely' : 'Next';

    viewer.isolate(step.isolate ?? []);
    viewer.setExplode(step.explode ?? 0);
    const slider = document.getElementById('explode');
    if (slider) slider.value = String(Math.round((step.explode ?? 0) * 100));

    const colourChips = document.querySelectorAll('[data-colour]');
    if (step.show_fea) {
      const firstCase = (manifest.analysis.fea || [])[0];
      if (firstCase) {
        colourChips.forEach((c) => c.classList.remove('is-active'));
        document.querySelector('[data-colour="stress"]')?.classList.add('is-active');
        viewer.showFea(firstCase.key);
      }
    } else {
      viewer.showFea(null);
      const mode = step.colour_by ?? 'material';
      colourChips.forEach((c) => c.classList.toggle('is-active', c.dataset.colour === mode));
      viewer.setColourMode(mode);
    }

    viewer.flyTo(null);
  }

  prevBtn.addEventListener('click', () => {
    index = Math.max(0, index - 1);
    render();
  });
  nextBtn.addEventListener('click', () => {
    if (index === story.length - 1) {
      el.classList.add('is-hidden');
      return;
    }
    index += 1;
    render();
  });
  exitBtn.addEventListener('click', () => el.classList.add('is-hidden'));

  render();
}

// ---------------------------------------------------------------- hash ---

function mountHash(viewer, manifest) {
  let timeout = null;
  function write() {
    clearTimeout(timeout);
    timeout = setTimeout(() => {
      const explode = document.getElementById('explode');
      const params = new URLSearchParams();
      if (explode && Number(explode.value) > 0) params.set('explode', explode.value);
      history.replaceState(null, '', params.toString() ? `#${params}` : location.pathname);
    }, 300);
  }
  document.getElementById('explode')?.addEventListener('input', write);
  viewer.onSelect((nodeId) => {
    const params = new URLSearchParams(location.hash.slice(1));
    if (nodeId) params.set('part', nodeId.split('__')[0]);
    else params.delete('part');
    history.replaceState(null, '', params.toString() ? `#${params}` : location.pathname);
  });
}
