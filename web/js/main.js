/* Bootstrap: load data, wire modules, hand over to the UI. */

import { createViewer } from './viewer.js';
import { mountUI } from './ui.js';
import { renderReports } from './report.js';

const SUPPORTED_SCHEMA_MAJOR = 1;

function setProgress(fraction, text) {
  const fill = document.getElementById('loader-fill');
  const label = document.getElementById('loader-text');
  if (fill) fill.style.width = `${Math.round(fraction * 100)}%`;
  if (label && text) label.textContent = text;
}

async function boot() {
  setProgress(0.05, 'Loading manifest…');
  const manifestResp = await fetch('assets/manifest.json');
  if (!manifestResp.ok) {
    throw new Error(`Could not load assets/manifest.json (HTTP ${manifestResp.status})`);
  }
  const manifest = await manifestResp.json();

  const major = parseInt(String(manifest.meta?.schema_version ?? '0').split('.')[0], 10);
  if (major !== SUPPORTED_SCHEMA_MAJOR) {
    throw new Error(
      `manifest schema ${manifest.meta?.schema_version} is not supported by this page ` +
      `(expects major version ${SUPPORTED_SCHEMA_MAJOR})`
    );
  }

  setProgress(0.15, 'Loading model…');
  const canvas = document.getElementById('canvas');
  const viewer = await createViewer({
    canvas,
    manifest,
    glbUrl: 'assets/drone.glb',
    onProgress: (loaded, total) => {
      if (total) setProgress(0.15 + 0.7 * (loaded / total), 'Loading model…');
    },
  });

  setProgress(0.9, 'Building interface…');
  mountUI({ viewer, manifest });
  renderReports(manifest, viewer);

  setProgress(1.0, 'Ready');
  const loader = document.getElementById('loader');
  if (loader) {
    loader.classList.add('is-done');
    setTimeout(() => loader.remove(), 450);
  }

  restoreFromHash(viewer, manifest);
}

function restoreFromHash(viewer, manifest) {
  if (!location.hash) return;
  const params = new URLSearchParams(location.hash.slice(1));
  const part = params.get('part');
  const explode = params.get('explode');
  if (explode !== null) {
    const v = Math.max(0, Math.min(100, parseFloat(explode))) / 100;
    viewer.setExplode(v);
    const slider = document.getElementById('explode');
    if (slider) slider.value = String(Math.round(v * 100));
  }
  if (part && manifest.parts[part]) {
    const firstInstance = manifest.instances.find((i) => i.part_key === part);
    if (firstInstance) {
      viewer.select(firstInstance.node_id);
      viewer.flyTo(firstInstance.node_id);
    }
  }
}

boot().catch((err) => {
  console.error(err);
  const t = document.getElementById('loader-text');
  if (t) {
    t.textContent = 'Could not load the model. See the browser console.';
    t.style.color = '#e5645f';
  }
  const bar = document.querySelector('.loader__bar');
  if (bar) bar.style.display = 'none';
});
