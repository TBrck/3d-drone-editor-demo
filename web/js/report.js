/* Renders the bill of materials, analysis and drawings views from the manifest. */

function fmt(n, digits = 1) {
  if (n === null || n === undefined) return '—';
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) node.appendChild(c);
  return node;
}

export function renderReports(manifest, viewer) {
  renderBom(manifest);
  renderAnalysis(manifest, viewer);
  renderDrawings(manifest);
  renderAbout(manifest);
}

function renderBom(manifest) {
  const root = document.getElementById('bom-root');
  if (!root) return;
  root.innerHTML = '';
  root.appendChild(el('h2', { text: 'Bill of materials' }));
  root.appendChild(
    el('p', {
      text: `${manifest.bom.rows.length} part types, ${manifest.instances.length} items, ` +
        `${fmt(manifest.bom.total_mass_g)} g all-up.`,
    })
  );

  const table = el('table');
  const thead = el('thead', {}, el('tr', {}, [
    el('th', { text: 'Part' }),
    el('th', { text: 'Material' }),
    el('th', { text: 'Process' }),
    el('th', { class: 'num', text: 'Qty' }),
    el('th', { class: 'num', text: 'Unit mass' }),
    el('th', { class: 'num', text: 'Total mass' }),
    el('th', { class: 'num', text: 'Share' }),
  ]));
  table.appendChild(thead);

  const tbody = el('tbody');
  for (const row of manifest.bom.rows) {
    const mat = manifest.materials[row.material_key];
    const proc = manifest.processes[row.process_key];
    const tr = el('tr', {}, [
      el('td', { text: row.name }),
      el('td', { text: mat ? mat.name : row.material_key }),
      el('td', { text: proc ? proc.name : row.process_key }),
      el('td', { class: 'num', text: String(row.qty) }),
      el('td', { class: 'num', text: `${fmt(row.unit_mass_g)} g` }),
      el('td', { class: 'num', text: `${fmt(row.total_mass_g)} g` }),
      el('td', { class: 'num', text: `${(row.mass_fraction * 100).toFixed(1)}%` }),
    ]);
    tbody.appendChild(tr);
  }
  const totalRow = el('tr', { class: 'total' }, [
    el('td', { text: 'Total' }),
    el('td', {}),
    el('td', {}),
    el('td', { class: 'num', text: String(manifest.instances.length) }),
    el('td', {}),
    el('td', { class: 'num', text: `${fmt(manifest.bom.total_mass_g)} g` }),
    el('td', { class: 'num', text: '100%' }),
  ]);
  tbody.appendChild(totalRow);
  table.appendChild(tbody);
  root.appendChild(table);
}

function sfClass(sf, target) {
  if (sf >= target * 1.25) return 'sf--ok';
  if (sf >= target) return 'sf--warn';
  return 'sf--bad';
}

function renderAnalysis(manifest, viewer) {
  const root = document.getElementById('analysis-root');
  if (!root) return;
  root.innerHTML = '';
  root.appendChild(el('h2', { text: 'Analysis' }));

  const mass = manifest.analysis?.mass;
  if (mass) {
    root.appendChild(el('h3', { text: 'Mass properties' }));
    const dl = el('table');
    const body = el('tbody', {}, [
      row('All-up mass', `${fmt(mass.total_mass_g)} g`, `target ${fmt(mass.target_auw_g)} g`),
      row('Centre of gravity', `(${mass.cog_mm.map((v) => fmt(v, 1)).join(', ')}) mm`, ''),
      row('CoG offset from rotor axis', `${fmt(mass.cog_offset_from_rotor_axis_mm, 2)} mm`, ''),
      row('Structural mass fraction', `${(mass.structural_fraction * 100).toFixed(1)}%`, ''),
    ]);
    dl.appendChild(body);
    root.appendChild(dl);
  }

  const perf = manifest.analysis?.performance;
  root.appendChild(el('h3', { text: 'Performance' }));
  if (perf) {
    const dl = el('table');
    dl.appendChild(el('tbody', {}, [
      row('Thrust-to-weight', fmt(perf.thrust_to_weight, 2), ''),
      row('Hover throttle', `${(perf.hover_throttle * 100).toFixed(0)}%`, ''),
      row('Estimated hover endurance', `${fmt(perf.hover_endurance_min)} min`, '±20% estimate'),
      row('Disc loading', `${fmt(perf.disc_loading_n_m2)} N/m²`, ''),
    ]));
    root.appendChild(dl);
  } else {
    root.appendChild(el('p', { class: 'calc__note', text: 'Not yet computed in this build.' }));
  }

  root.appendChild(el('h3', { text: 'Hand calculations' }));
  const checks = manifest.analysis?.checks ?? [];
  if (checks.length === 0) {
    root.appendChild(el('p', { class: 'calc__note', text: 'Not yet computed in this build.' }));
  }
  for (const check of checks) {
    const sf = check.safety_factor;
    const card = el('div', { class: 'calc' }, [
      el('div', { class: 'calc__head' }, [
        el('strong', { text: check.title }),
        el('span', { class: `sf ${sfClass(sf, check.target_sf)}`, text: `SF ${fmt(sf, 2)}` }),
      ]),
      el('div', { class: 'calc__formula', text: check.formula }),
    ]);
    if (check.note) card.appendChild(el('p', { class: 'calc__note', text: check.note }));
    root.appendChild(card);
  }

  root.appendChild(el('h3', { text: 'Finite element results' }));
  const fea = manifest.analysis?.fea ?? [];
  if (fea.length === 0) {
    root.appendChild(el('p', { class: 'calc__note', text: 'Not yet computed in this build.' }));
  }
  for (const f of fea) {
    const sf = f.safety_factor;
    const target = 2.0; // FEA cases don't carry their own target_sf; 2.0 is a reasonable general floor
    const convergencePct = f.convergence_delta * 100;
    const convergenceNote =
      convergencePct > 10
        ? `Mesh convergence: ${convergencePct.toFixed(1)}% change between the nominal and ` +
          `refined mesh — above the ~10% target, so treat the peak stress as indicative, ` +
          `not final.`
        : `Mesh convergence: ${convergencePct.toFixed(1)}% change between the nominal and ` +
          `refined mesh — converged.`;

    const card = el('div', { class: 'calc' }, [
      el('div', { class: 'calc__head' }, [
        el('strong', { text: f.title }),
        el('span', { class: `sf ${sfClass(sf, target)}`, text: `SF ${fmt(sf, 2)}` }),
      ]),
      el('p', { text: f.description }),
      el('div', { class: 'calc__inputs' }, [
        el('span', { text: `Restraint: ${f.restraint}` }),
        el('span', { text: `Loading: ${f.loading}` }),
      ]),
      el('p', {
        text:
          `Peak von Mises ${fmt(f.max_von_mises_mpa)} MPa (yield ${fmt(f.yield_mpa)} MPa), ` +
          `max displacement ${fmt(f.max_displacement_mm, 3)} mm — ` +
          `${f.node_count.toLocaleString()} nodes, ${f.element_count.toLocaleString()} elements, ` +
          `${fmt(f.solve_seconds, 0)} s.`,
      }),
      el('p', { class: 'calc__note', text: convergenceNote }),
    ]);

    if (viewer) {
      const btn = el('button', { class: 'btn btn--ghost', text: 'View stress in 3D' });
      btn.addEventListener('click', () => {
        document.querySelector('.tab[data-view="model"]')?.click();
        document.querySelectorAll('[data-colour]').forEach((c) => c.classList.remove('is-active'));
        document.querySelector('[data-colour="stress"]')?.classList.add('is-active');
        viewer.showFea(f.key);
      });
      card.appendChild(btn);
    }

    root.appendChild(card);
  }

  const limitations = manifest.analysis?.limitations ?? [];
  if (limitations.length) {
    const box = el('div', { class: 'caveat' });
    box.appendChild(el('strong', { text: 'Limitations of this analysis' }));
    const ul = el('ul');
    for (const l of limitations) ul.appendChild(el('li', { text: l }));
    box.appendChild(ul);
    root.appendChild(box);
  }
}

function row(label, value, note) {
  return el('tr', {}, [
    el('td', { text: label }),
    el('td', { class: 'num', text: value }),
    el('td', { text: note }),
  ]);
}

function renderDrawings(manifest) {
  const root = document.getElementById('drawings-root');
  if (!root) return;
  root.innerHTML = '';
  root.appendChild(el('h2', { text: 'Drawings' }));

  const drawnParts = Object.values(manifest.parts).filter((p) => p.drawing);
  if (drawnParts.length === 0) {
    root.appendChild(
      el('p', { text: 'Dimensioned drawings are not yet published for this build.' })
    );
  }
  for (const part of drawnParts) {
    const mat = manifest.materials[part.material_key];
    const proc = manifest.processes[part.process_key];
    const stepLabel = `${part.name} (STEP)`;
    const stepPath = manifest.downloads?.[stepLabel];

    const card = el('div', { class: 'drawing-card' });
    const obj = document.createElement('object');
    obj.type = 'image/svg+xml';
    obj.data = `assets/${part.drawing}`;
    obj.style.width = '100%';
    obj.style.aspectRatio = '420 / 297';
    card.appendChild(obj);

    const caption = el('figcaption', {}, [
      document.createTextNode(
        `${part.name} — ${mat ? mat.name : part.material_key}, ` +
        `${proc ? proc.name : part.process_key}`
      ),
    ]);
    if (stepPath) {
      caption.appendChild(document.createTextNode(' · '));
      caption.appendChild(el('a', { href: `assets/${stepPath}`, text: 'Download STEP' }));
    }
    card.appendChild(caption);
    root.appendChild(card);
  }

  const downloads = manifest.downloads ?? {};
  if (Object.keys(downloads).length > 0) {
    root.appendChild(el('h3', { text: 'All downloads' }));
    for (const [label, path] of Object.entries(downloads)) {
      root.appendChild(el('p', {}, el('a', { href: `assets/${path}`, text: label })));
    }
  }
}

function renderAbout(manifest) {
  const downloadsEl = document.getElementById('about-downloads');
  const provenanceEl = document.getElementById('about-provenance');
  if (downloadsEl) {
    const downloads = manifest.downloads ?? {};
    downloadsEl.innerHTML = Object.keys(downloads).length
      ? Object.entries(downloads).map(([k, v]) => `<a href="assets/${v}">${k}</a>`).join(' · ')
      : 'STEP downloads are not yet published for this build.';
  }
  if (provenanceEl) {
    const meta = manifest.meta;
    provenanceEl.textContent =
      `Built from commit ${meta.git_commit} on ${meta.built_at}. ` +
      `build123d ${meta.tool_versions.build123d}, trimesh ${meta.tool_versions.trimesh}.`;
  }
}
