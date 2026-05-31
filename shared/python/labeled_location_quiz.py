"""Render labeled-location quiz outputs (interactive HTML + printable PDFs)
from a spec.yaml describing the quiz.

A "labeled-location quiz" is the pattern: a base map (or any base image)
with N labeled locations; the student matches the location to a numbered
term from a list. This module renders three outputs from one spec:

  render_html(spec, output_path)
    Self-contained interactive HTML page. Features:
      - Type term number into a box positioned over its location on the map.
      - Wrong input → shake + count miss + ask again. Right → lock green.
      - Per-box miss counter (badge) + total correct/miss in header.
      - localStorage persistence: refresh / accidental close keeps progress.
      - Mode selector: "Sve (N)" or random subset (20 / 10 / 5).
      - CSV export of results after completion.
      - @media print stylesheet: clean printable layout, no controls.
      - Zoom + pan on the map; input boxes stay at base size while map zooms.

  render_pdf(spec, output_path, answer=False)
    Printable PDF via matplotlib. answer=False = student worksheet (empty
    circles); answer=True = answer key (numbered circles).

Both rendering functions read the same spec dict (loaded from spec.yaml
via load_spec) and the same shared GeoJSON.

Quiz spec schema: see classroom/templates/labeled-location-quiz/spec.template.yaml.
"""
import json as _json
import math
import pathlib
import yaml

from projection import make_projection
from geojson_utils import load_geojson, iter_polygon_rings


# ---------------------------------------------------------------------------
# Spec loading
# ---------------------------------------------------------------------------

def load_spec(path):
    """Load and validate a quiz spec from a YAML file. Adds convenience
    entries (resolved geo_data path, lookup tables) and returns the dict."""
    path = pathlib.Path(path).resolve()
    with open(path) as f:
        spec = yaml.safe_load(f)

    geo_rel = spec["map"]["geo_data"]
    spec["map"]["_geo_data_resolved"] = str((path.parent / geo_rel).resolve())
    spec["_spec_path"] = str(path)
    spec["_spec_dir"] = str(path.parent)
    spec["_terms_by_id"] = {t["id"]: t for t in spec["terms"]}
    spec["_mountains"] = [
        (t["id"], t["geometry"]["polyline"])
        for t in spec["terms"]
        if t.get("geometry", {}).get("type") == "mountain"
    ]
    spec["_rivers"] = [
        (t["id"], t["geometry"]["polyline"])
        for t in spec["terms"]
        if t.get("geometry", {}).get("type") == "river"
    ]
    return spec


def _default_style():
    return {
        "colors": {
            "sea": "#cfe6f2",
            "land": "#f3ecd8",
            "border": "#8a8170",
            "coast": "#5b5446",
            "mountain": "#9c5a2c",
            "river": "#2f7fb5",
            "circle_edge": "#b1271f",
            "circle_fill": "#ffffff",
        }
    }


def _colors(spec):
    out = dict(_default_style()["colors"])
    out.update((spec.get("style") or {}).get("colors", {}))
    return out


def _ui_default():
    return {
        "header_title": "Quiz",
        "header_subtitle": "Enter the term number into the box at its location.",
        "list_heading": "Terms",
        "legend_mountains": "▲ mountains",
        "legend_rivers": "— rivers",
        "legend_circles": "▢ = location",
        "stat_correct": "Correct",
        "stat_miss": "Mistakes",
        "btn_reset": "Reset",
        "btn_export_csv": "Download results (CSV)",
        "mode_label": "Questions",
        "mode_all": "All ({n})",
        "mode_random": "{n} random",
        "msg_correct": "Correct!",
        "msg_wrong": "Wrong — try again",
        "msg_win": "Done! All correct ({total}/{total}) · total mistakes: {miss}",
        "resume_indicator": "Resumed previous session — your progress is restored.",
        "zoom_hint": "Zoom: + / − / wheel / dblclick · Drag to pan",
        "pdf_title_quiz": "Quiz",
        "pdf_title_answer": "Answer key",
        "pdf_legend_heading": "Terms:",
        "pdf_legend_symbols": "▲ mountains    — rivers    ○ location",
    }


def _ui(spec):
    out = dict(_ui_default())
    out.update(spec.get("ui") or {})
    return out


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_HTML_TPL = r"""<!DOCTYPE html>
<html lang="__LOCALE__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
 :root{--sea:__SEA__;--land:__LAND__;--bord:__BORD__;--edge:__EDGE__;--ink:#2b2b2b;}
 *{box-sizing:border-box}
 body{margin:0;font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif;color:var(--ink);background:#faf8f2}
 header{padding:14px 18px;background:#fff;border-bottom:1px solid #e6e0d2;position:sticky;top:0;z-index:50}
 h1{margin:0 0 4px;font-size:19px;color:#3a3528}
 .sub{font-size:13px;color:#6b6456;margin:0;max-width:900px}
 .bar{display:flex;gap:14px;flex-wrap:wrap;align-items:center;margin-top:10px;font-size:14px}
 .stat{background:#f3ecd8;border:1px solid #e1d8c2;border-radius:8px;padding:6px 12px}
 .stat b{font-size:16px}
 .ok{color:#1f7a3a} .bad{color:#b1271f}
 button{font:inherit;padding:7px 14px;border:1px solid #b1271f;background:#fff;color:#b1271f;border-radius:8px;cursor:pointer}
 button:hover{background:#b1271f;color:#fff}
 button.secondary{border-color:#1f7a3a;color:#1f7a3a}
 button.secondary:hover{background:#1f7a3a;color:#fff}
 .mode-selector{display:inline-flex;gap:6px;align-items:center;font-size:13px;color:#3a3528}
 .mode-selector select{font:inherit;padding:4px 8px;border:1px solid #6b6456;border-radius:6px;background:#fff;color:#3a3528;cursor:pointer}
 .resume-banner{display:none;margin-top:8px;background:#fffbe6;border:1px solid #f0d878;border-radius:8px;padding:6px 12px;font-size:13px;color:#7a5a00}
 .resume-banner.show{display:block}
 .layout{display:flex;align-items:flex-start;gap:0;width:100%}
 .qcol{flex:0 0 360px;width:360px;padding:12px 14px;border-right:1px solid #e6e0d2;background:#fff;position:sticky;top:var(--htop,0px);max-height:calc(100vh - var(--htop,0px));overflow:auto}
 .qcol h2{font-size:14px;color:#3a3528;margin:0 0 8px}
 .mapcol{flex:1 1 auto;min-width:0;padding:0}
 #stageWrap{width:100%;overflow:hidden;position:relative;touch-action:none;cursor:grab}
 #stageWrap.grabbing{cursor:grabbing}
 .zoombar{position:absolute;right:12px;top:12px;z-index:30;display:flex;flex-direction:column;gap:6px}
 .zoombar button{width:40px;height:40px;padding:0;font-size:21px;line-height:1;font-weight:700;background:#fff;border:1px solid #6b6456;color:#3a3528;border-radius:9px;box-shadow:0 1px 3px rgba(0,0,0,.22);cursor:pointer}
 .zoombar button:hover{background:#f3ecd8;color:#3a3528}
 .zhint{position:absolute;left:12px;bottom:10px;z-index:30;background:rgba(255,255,255,.85);border:1px solid #e1d8c2;border-radius:8px;padding:4px 10px;font-size:12px;color:#6b6456;pointer-events:none}
 #stage{position:relative;width:__W__px;height:__H__px;transform-origin:top left}
 svg{position:absolute;inset:0;width:__W__px;height:__H__px;background:var(--sea);border:2px solid #6b6456;border-radius:6px}
 #overlay{position:absolute;inset:0;z-index:10;overflow:hidden;pointer-events:none}
 .cell{position:absolute;transform:translate(-50%,-50%) scale(var(--bs,1));transform-origin:center center}
 .cell.hidden{display:none}
 .ans{pointer-events:auto;width:28px;height:28px;border:2px solid var(--edge);border-radius:6px;background:#fff;text-align:center;font-size:13px;font-weight:700;color:var(--edge);padding:0;outline:none;box-shadow:0 1px 2px rgba(0,0,0,.15)}
 .ans:focus{border-color:#1f7a3a;box-shadow:0 0 0 3px rgba(31,122,58,.25)}
 .ans.correct{background:#d8f0dd;border-color:#1f7a3a;color:#1f7a3a;cursor:default}
 .ans.wrong{animation:shake .3s;background:#fdd;border-color:#b1271f}
 @keyframes shake{0%,100%{transform:translateX(0)}25%{transform:translateX(-4px)}75%{transform:translateX(4px)}}
 .miss{position:absolute;top:-9px;right:-9px;background:#b1271f;color:#fff;font-size:10px;font-weight:700;min-width:16px;height:16px;line-height:16px;text-align:center;border-radius:9px;padding:0 3px}
 ol.terms{list-style:none;padding:0;margin:0;columns:2;column-gap:16px;font-size:12px;line-height:1.45}
 ol.terms li{break-inside:avoid} ol.terms b{color:var(--edge)}
 ol.terms li.hidden{display:none}
 .keyline{font-size:11.5px;color:#6b6456;margin:10px 0 0;border-top:1px solid #eee;padding-top:8px;line-height:1.7}
 .keyline .m{color:__MTN_COL__;font-weight:700} .keyline .r{color:__RIV_COL__;font-weight:700}
 #msg{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);background:#b1271f;color:#fff;padding:10px 18px;border-radius:24px;font-size:14px;font-weight:600;opacity:0;transition:opacity .25s;pointer-events:none;z-index:99}
 #msg.show{opacity:1}
 .win{background:#d8f0dd;border-color:#1f7a3a;color:#13602c;font-weight:700}
 @media (max-width:760px){
   .layout{flex-direction:column}
   .qcol{flex:none;width:auto;position:static;max-height:none;border-right:none;border-bottom:1px solid #e6e0d2}
   .qcol ol.terms{columns:2;column-gap:22px}
   h1{font-size:17px}
   .ans{width:32px;height:32px;font-size:14px}
 }
 @media print {
   header .bar, .zoombar, .zhint, #msg, .resume-banner, button { display: none !important; }
   header { position: static; border-bottom: 1px solid #ccc }
   .qcol { position: static; max-height: none; overflow: visible; flex: 0 0 280px; width: 280px }
   #stageWrap { overflow: visible; cursor: auto; height: auto !important; }
   #stage { transform: none !important }
   body { background: white; -webkit-print-color-adjust: exact; print-color-adjust: exact }
   svg, .layout { break-inside: avoid }
   .ans { background: white; border-color: #999 }
   .ans.correct, .ans.wrong { background: white !important; border-color: #999 !important; color: #333 !important }
 }
</style>
</head>
<body>
<header>
 <h1>__HDR_TITLE__</h1>
 <p class="sub">__HDR_SUB__</p>
 <div class="bar">
  <span class="stat">__LBL_CORRECT__: <b class="ok" id="cCorrect">0</b> / <b id="cTotal">__TOTAL__</b></span>
  <span class="stat">__LBL_MISS__: <b class="bad" id="cMiss">0</b></span>
  <button id="reset">__BTN_RESET__</button>
  <button id="exportCsv" class="secondary" style="display:none">__BTN_CSV__</button>
  <label class="mode-selector">__MODE_LABEL__:
   <select id="mode">
    <option value="all">__MODE_ALL__</option>
    <option value="20">__MODE_20__</option>
    <option value="10">__MODE_10__</option>
    <option value="5">__MODE_5__</option>
   </select>
  </label>
  <span class="stat win" id="win" style="display:none"></span>
 </div>
 <div id="resumeBanner" class="resume-banner">__RESUME_MSG__</div>
</header>
<div class="layout">
 <aside class="qcol">
  <h2>__LIST_HEADING__</h2>
  <ol class="terms">__LEG__</ol>
  <p class="keyline"><span class="m">__LEG_MOUNTAINS__</span><br><span class="r">__LEG_RIVERS__</span><br>__LEG_CIRCLES__</p>
 </aside>
 <main class="mapcol">
  <div id="stageWrap">
   <div class="zoombar">
    <button id="zin" title="+">+</button>
    <button id="zout" title="−">−</button>
    <button id="zreset" title="⟳">⟳</button>
   </div>
   <div class="zhint">__ZHINT__</div>
   <div id="stage">
    <svg viewBox="0 0 __W__ __H__" xmlns="http://www.w3.org/2000/svg">
     <path d="__LAND_PATH__" fill="var(--land)" stroke="none"/>
     <path d="__STROKE__" fill="none" stroke="var(--bord)" stroke-width="0.6"/>
     __RIV__
     __MTN__
     __MARKS__
    </svg>
   </div>
   <div id="overlay">__BOXES__</div>
  </div>
 </main>
</div>
<div id="msg"></div>
<script>
const ALL_TERMS = __TERMS_JSON__;
const STATE_KEY = 'classroom:' + window.location.pathname;
const STATE_VERSION = 2;
const RANDOMIZE_NUMBERS = __RANDOMIZE_NUMBERS__;
const MSG_CORRECT = __MSG_CORRECT__, MSG_WRONG = __MSG_WRONG__, MSG_WIN_TPL = __MSG_WIN__;
const MODE_ALL_TPL = __MODE_ALL_TPL__, MODE_RANDOM_TPL = __MODE_RANDOM_TPL__;

const allInputs = [...document.querySelectorAll('.ans')];
const inputsById = new Map(allInputs.map(i => [parseInt(i.dataset.correct, 10), i]));
const legendItems = new Map([...document.querySelectorAll('ol.terms li')].map(li => [parseInt(li.dataset.id, 10), li]));
const cCorrect = document.getElementById('cCorrect');
const cMiss = document.getElementById('cMiss');
const cTotal = document.getElementById('cTotal');
const msg = document.getElementById('msg');
const win = document.getElementById('win');
const resetBtn = document.getElementById('reset');
const exportBtn = document.getElementById('exportCsv');
const modeSelect = document.getElementById('mode');
const resumeBanner = document.getElementById('resumeBanner');

let currentMode = 'all';
let visibleIds = ALL_TERMS.map(t => t.id);
let currentMapping = null;  // { c2d: {canonId: displayNum}, d2c: {displayNum: canonId} }
let msgT = null;

const legendList = document.querySelector('ol.terms');

function generateMapping(canonicalIds) {
  const arr = [...canonicalIds];
  if (RANDOMIZE_NUMBERS) {
    for (let i = arr.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [arr[i], arr[j]] = [arr[j], arr[i]];
    }
  }
  const c2d = {}, d2c = {};
  arr.forEach((canonId, idx) => {
    c2d[canonId] = idx + 1;
    d2c[idx + 1] = canonId;
  });
  return { c2d, d2c };
}

function applyMapping(mapping) {
  currentMapping = mapping;
  // Update each input's expected answer to its display number
  for (const inp of allInputs) {
    const canonId = parseInt(inp.dataset.id, 10);
    const display = mapping.c2d[canonId];
    inp.dataset.correct = display ? String(display) : '';
  }
  // Reorder legend by display number and rewrite the <b>N.</b> prefix
  const items = [...legendList.children];
  items.sort((a, b) => {
    const da = mapping.c2d[parseInt(a.dataset.id, 10)] || 9999;
    const db = mapping.c2d[parseInt(b.dataset.id, 10)] || 9999;
    return da - db;
  });
  legendList.append(...items);
  for (const li of items) {
    const canonId = parseInt(li.dataset.id, 10);
    const display = mapping.c2d[canonId];
    if (display) {
      const b = li.querySelector('b');
      if (b) b.textContent = display + '.';
    }
  }
}

function setSelectOptions() {
  // Fill {n} placeholders for the mode selector options
  modeSelect.options[0].textContent = MODE_ALL_TPL.replace('{n}', ALL_TERMS.length);
  for (let i = 1; i < modeSelect.options.length; i++) {
    const n = parseInt(modeSelect.options[i].value, 10);
    if (n >= ALL_TERMS.length) {
      modeSelect.options[i].style.display = 'none';
    } else {
      modeSelect.options[i].textContent = MODE_RANDOM_TPL.replace('{n}', n);
    }
  }
}

function showMsg(t, ok) {
  msg.textContent = t;
  msg.style.background = ok ? '#1f7a3a' : '#b1271f';
  msg.classList.add('show');
  clearTimeout(msgT);
  msgT = setTimeout(() => msg.classList.remove('show'), 1400);
}

function applyVisibility(ids) {
  const set = new Set(ids);
  visibleIds = ids;
  for (const inp of allInputs) {
    const id = parseInt(inp.dataset.correct, 10);
    inp.parentElement.classList.toggle('hidden', !set.has(id));
  }
  for (const [id, li] of legendItems) {
    li.classList.toggle('hidden', !set.has(id));
  }
  cTotal.textContent = ids.length;
}

function recountCorrectMiss() {
  let correct = 0, miss = 0;
  for (const id of visibleIds) {
    const inp = inputsById.get(id);
    if (!inp) continue;
    if (inp.classList.contains('correct')) correct++;
    miss += parseInt(inp.dataset.miss, 10) || 0;
  }
  cCorrect.textContent = correct;
  cMiss.textContent = miss;
  if (correct === visibleIds.length && visibleIds.length > 0) {
    showWin(correct, miss);
  } else {
    win.style.display = 'none';
    exportBtn.style.display = 'none';
  }
}

function showWin(correct, miss) {
  win.style.display = 'inline-block';
  win.textContent = MSG_WIN_TPL.replace(/\{total\}/g, correct).replace('{miss}', miss);
  exportBtn.style.display = 'inline-block';
}

function check(inp) {
  if (inp.parentElement.classList.contains('hidden')) return;
  if (inp.classList.contains('correct')) return;
  const v = inp.value.trim();
  if (v === '') return;
  if (parseInt(v, 10) === parseInt(inp.dataset.correct, 10)) {
    inp.classList.remove('wrong');
    inp.classList.add('correct');
    inp.readOnly = true;
    showMsg(MSG_CORRECT, true);
    recountCorrectMiss();
  } else {
    const m = (parseInt(inp.dataset.miss, 10) || 0) + 1;
    inp.dataset.miss = m;
    const badge = inp.parentElement.querySelector('.miss');
    badge.textContent = m;
    badge.style.display = 'block';
    inp.classList.add('wrong');
    showMsg(MSG_WRONG, false);
    recountCorrectMiss();
    setTimeout(() => {
      inp.classList.remove('wrong');
      inp.value = '';
      inp.focus();
    }, 420);
  }
  saveState();
}

// --- state persistence ---
function saveState() {
  const answers = {};
  for (const inp of allInputs) {
    answers[inp.dataset.id] = {  // keyed by canonical id, not display number
      v: inp.value,
      c: inp.classList.contains('correct'),
      m: parseInt(inp.dataset.miss, 10) || 0
    };
  }
  const state = {
    v: STATE_VERSION,
    mode: currentMode,
    visible: visibleIds,
    mapping: currentMapping ? currentMapping.c2d : null,
    answers
  };
  try { localStorage.setItem(STATE_KEY, JSON.stringify(state)); } catch (e) {}
}

function loadState() {
  try {
    const s = localStorage.getItem(STATE_KEY);
    if (!s) return null;
    const obj = JSON.parse(s);
    if (!obj || obj.v !== STATE_VERSION) return null;
    return obj;
  } catch (e) {
    return null;
  }
}

function clearState() {
  try { localStorage.removeItem(STATE_KEY); } catch (e) {}
}

function applyAnswers(answers) {
  for (const inp of allInputs) {
    const a = answers[inp.dataset.id];  // keyed by canonical id
    inp.value = '';
    inp.readOnly = false;
    inp.classList.remove('correct', 'wrong');
    inp.dataset.miss = '0';
    const badge = inp.parentElement.querySelector('.miss');
    badge.style.display = 'none';
    badge.textContent = '0';
    if (!a) continue;
    if (a.v) inp.value = a.v;
    if (a.c) {
      inp.classList.add('correct');
      inp.readOnly = true;
    }
    if (a.m && a.m > 0) {
      inp.dataset.miss = String(a.m);
      badge.textContent = a.m;
      badge.style.display = 'block';
    }
  }
}

// --- mode (N-random) ---
function shuffleIds(n) {
  const all = ALL_TERMS.map(t => t.id);
  for (let i = all.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [all[i], all[j]] = [all[j], all[i]];
  }
  return all.slice(0, n).sort((a, b) => a - b);
}

function setMode(mode, opts) {
  opts = opts || {};
  currentMode = mode;
  let ids;
  if (mode === 'all') {
    ids = ALL_TERMS.map(t => t.id);
  } else {
    const n = parseInt(mode, 10);
    ids = opts.restoreIds || shuffleIds(n);
  }
  applyVisibility(ids);
  const mapping = opts.restoreMapping || generateMapping(ids);
  applyMapping(mapping);
  if (!opts.restoreIds && !opts.restoreMapping) {
    // mode change resets answers
    applyAnswers({});
  }
  recountCorrectMiss();
}

modeSelect.addEventListener('change', () => {
  setMode(modeSelect.value, {});
  saveState();
});

// --- CSV export ---
function exportCSV() {
  const lines = ['canonical_id,display_number,name,correct,miss_count'];
  for (const t of ALL_TERMS) {
    if (!visibleIds.includes(t.id)) continue;
    const inp = inputsById.get(t.id);
    const display = inp.dataset.correct || '';
    const correct = inp.classList.contains('correct') ? 'yes' : 'no';
    const miss = inp.dataset.miss || '0';
    const name = '"' + t.name.replace(/"/g, '""') + '"';
    lines.push(t.id + ',' + display + ',' + name + ',' + correct + ',' + miss);
  }
  const csv = lines.join('\n') + '\n';
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'rezultati-' + new Date().toISOString().slice(0, 10) + '.csv';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
exportBtn.addEventListener('click', exportCSV);

// --- input handlers ---
allInputs.forEach(inp => {
  inp.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); check(inp); } });
  inp.addEventListener('blur', () => check(inp));
});

resetBtn.addEventListener('click', () => {
  // Always re-shuffle numbering on reset (if randomization is enabled)
  // and within the same mode (pick fresh random subset for N-mode).
  if (currentMode !== 'all') {
    const n = parseInt(currentMode, 10);
    setMode(currentMode, { restoreIds: shuffleIds(n) });
  } else {
    setMode('all', {});
  }
  resumeBanner.classList.remove('show');
  clearState();
});

// --- map zoom / pan ---
const stage = document.getElementById('stage');
const wrap = document.getElementById('stageWrap');
const cells = [...document.querySelectorAll('.cell')];
const MW = __W__, MH = __H__, ZMAX = 6, ZMIN = 1;
let baseFit = 1, zoom = 1, panX = 0, panY = 0;

function computeFit() {
  const top = wrap.getBoundingClientRect().top;
  const availW = wrap.clientWidth;
  const availH = Math.max(240, window.innerHeight - top - 14);
  baseFit = Math.min(availW / MW, availH / MH);
}
function clampPan() {
  const vw = wrap.clientWidth, vh = baseFit * MH;
  const cw = MW * baseFit * zoom, ch = MH * baseFit * zoom;
  panX = cw <= vw ? (vw - cw) / 2 : Math.min(0, Math.max(vw - cw, panX));
  panY = ch <= vh ? (vh - ch) / 2 : Math.min(0, Math.max(vh - ch, panY));
}
function apply() {
  clampPan();
  const sc = baseFit * zoom;
  stage.style.transform = 'translate(' + panX + 'px,' + panY + 'px) scale(' + sc + ')';
  document.documentElement.style.setProperty('--bs', baseFit);
  for (const c of cells) {
    c.style.left = (panX + (+c.dataset.sx) * sc) + 'px';
    c.style.top  = (panY + (+c.dataset.sy) * sc) + 'px';
  }
}
function fit() { computeFit(); wrap.style.height = (baseFit * MH) + 'px'; apply(); }
function zoomAt(cx, cy, factor) {
  const nz = Math.min(ZMAX, Math.max(ZMIN, zoom * factor));
  if (nz === zoom) return;
  const s = baseFit;
  const ux = (cx - panX) / (s * zoom), uy = (cy - panY) / (s * zoom);
  zoom = nz;
  panX = cx - ux * s * zoom; panY = cy - uy * s * zoom;
  apply();
}
function centerZoom(factor) { zoomAt(wrap.clientWidth / 2, wrap.clientHeight / 2, factor); }
document.getElementById('zin').addEventListener('click', () => centerZoom(1.4));
document.getElementById('zout').addEventListener('click', () => centerZoom(1 / 1.4));
document.getElementById('zreset').addEventListener('click', () => { zoom = 1; panX = 0; panY = 0; fit(); });
wrap.addEventListener('wheel', e => {
  e.preventDefault();
  const r = wrap.getBoundingClientRect();
  zoomAt(e.clientX - r.left, e.clientY - r.top, e.deltaY < 0 ? 1.15 : 1 / 1.15);
}, { passive: false });
wrap.addEventListener('dblclick', e => {
  if (e.target.closest('.ans')) return;
  const r = wrap.getBoundingClientRect();
  zoomAt(e.clientX - r.left, e.clientY - r.top, 1.6);
});
const ptrs = new Map();
let dragStart = null, lastDist = 0;
function midRel() {
  const r = wrap.getBoundingClientRect();
  const a = [...ptrs.values()];
  return { x: (a[0].x + a[1].x) / 2 - r.left, y: (a[0].y + a[1].y) / 2 - r.top };
}
function dist() {
  const a = [...ptrs.values()];
  return Math.hypot(a[0].x - a[1].x, a[0].y - a[1].y);
}
wrap.addEventListener('pointerdown', e => {
  if (e.target.closest('.ans') || e.target.closest('.zoombar')) return;
  e.preventDefault();
  ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
  try { wrap.setPointerCapture(e.pointerId); } catch (_) {}
  if (ptrs.size === 1) { dragStart = { x: e.clientX, y: e.clientY, px: panX, py: panY }; wrap.classList.add('grabbing'); }
  else if (ptrs.size === 2) { dragStart = null; lastDist = dist(); }
});
wrap.addEventListener('pointermove', e => {
  if (!ptrs.has(e.pointerId)) return;
  ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (ptrs.size >= 2) {
    const d = dist();
    if (lastDist > 0) { const m = midRel(); zoomAt(m.x, m.y, d / lastDist); }
    lastDist = d;
  } else if (dragStart) {
    panX = dragStart.px + (e.clientX - dragStart.x);
    panY = dragStart.py + (e.clientY - dragStart.y);
    apply();
  }
});
function endPtr(e) {
  ptrs.delete(e.pointerId);
  if (ptrs.size < 2) lastDist = 0;
  if (ptrs.size === 0) { dragStart = null; wrap.classList.remove('grabbing'); }
}
wrap.addEventListener('pointerup', endPtr);
wrap.addEventListener('pointercancel', endPtr);

// --- init ---
function setHeaderTop() {
  const h = document.querySelector('header').offsetHeight;
  document.documentElement.style.setProperty('--htop', h + 'px');
}

setSelectOptions();

// Restore state if present
const saved = loadState();
if (saved) {
  modeSelect.value = saved.mode || 'all';
  let restoreMapping = null;
  if (saved.mapping) {
    const d2c = {};
    for (const [c, d] of Object.entries(saved.mapping)) d2c[d] = parseInt(c, 10);
    restoreMapping = { c2d: saved.mapping, d2c };
  }
  setMode(saved.mode || 'all', { restoreIds: saved.visible, restoreMapping });
  applyAnswers(saved.answers || {});
  recountCorrectMiss();
  resumeBanner.classList.add('show');
} else {
  setMode('all', {});
}

window.addEventListener('resize', () => { setHeaderTop(); fit(); });
setHeaderTop();
fit();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def render_html(spec, output_path, map_width_px=1160.0):
    """Render the interactive HTML quiz to `output_path`."""
    colors = _colors(spec)
    ui = _ui(spec)
    extent_lon = tuple(spec["map"]["extent"]["lon"])
    extent_lat = tuple(spec["map"]["extent"]["lat"])
    mid_lat = spec["map"]["mid_lat_for_aspect"]
    px, W, H = make_projection(extent_lon, extent_lat, mid_lat, map_width_px)

    # Country geometry → SVG paths
    geo = load_geojson(spec["map"]["_geo_data_resolved"])
    land_paths = []
    stroke_paths = []
    for ring, is_exterior in iter_polygon_rings(geo["features"], extent_lon, extent_lat, padding=6):
        pts = [f"{x:.1f},{y:.1f}" for x, y in (px(lon, lat) for lon, lat in ring)]
        d = "M" + " L".join(pts) + "Z"
        stroke_paths.append(d)
        if is_exterior:
            land_paths.append(d)

    def polyline_str(pts):
        return " ".join(f"{px(lo, la)[0]:.1f},{px(lo, la)[1]:.1f}" for lo, la in pts)

    mtn_svg = "".join(
        f'<polyline points="{polyline_str(p)}" fill="none" stroke="{colors["mountain"]}" '
        f'stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>'
        for _, p in spec["_mountains"]
    )
    mtn_marks = ""
    for _, pts in spec["_mountains"]:
        for lo, la in pts:
            x, y = px(lo, la)
            mtn_marks += (
                f'<path d="M{x-3:.1f},{y+3:.1f} L{x:.1f},{y-3:.1f} '
                f'L{x+3:.1f},{y+3:.1f} Z" fill="{colors["mountain"]}"/>'
            )
    riv_svg = "".join(
        f'<polyline points="{polyline_str(p)}" fill="none" stroke="{colors["river"]}" '
        f'stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>'
        for _, p in spec["_rivers"]
    )

    boxes = ""
    for t in spec["terms"]:
        lon, lat = t["label_at"]
        x, y = px(lon, lat)
        boxes += (
            f'<div class="cell" data-sx="{x:.1f}" data-sy="{y:.1f}">'
            f'<input class="ans" data-id="{t["id"]}" data-correct="{t["id"]}" data-miss="0" '
            f'maxlength="3" inputmode="numeric" autocomplete="off" aria-label="number">'
            f'<span class="miss" style="display:none">0</span></div>'
        )

    leg_rows = "".join(
        f'<li data-id="{t["id"]}"><b>{t["id"]}.</b> {t["name"]}</li>'
        for t in spec["terms"]
    )

    # Terms JSON for client-side use (id + name for CSV export)
    terms_json = _json.dumps(
        [{"id": t["id"], "name": t["name"]} for t in spec["terms"]],
        ensure_ascii=False
    )

    repl = {
        "__LOCALE__": spec.get("locale", "en"),
        "__TITLE__": ui.get("header_title", spec.get("title", "Quiz")),
        "__SEA__": colors["sea"], "__LAND__": colors["land"],
        "__BORD__": colors["border"], "__EDGE__": colors["circle_edge"],
        "__MTN_COL__": colors["mountain"], "__RIV_COL__": colors["river"],
        "__W__": f"{W:.0f}", "__H__": f"{H:.0f}",
        "__LAND_PATH__": " ".join(land_paths),
        "__STROKE__": " ".join(stroke_paths),
        "__RIV__": riv_svg, "__MTN__": mtn_svg, "__MARKS__": mtn_marks,
        "__BOXES__": boxes, "__LEG__": leg_rows,
        "__HDR_TITLE__": ui["header_title"],
        "__HDR_SUB__": ui["header_subtitle"],
        "__LBL_CORRECT__": ui["stat_correct"],
        "__LBL_MISS__": ui["stat_miss"],
        "__BTN_RESET__": ui["btn_reset"],
        "__BTN_CSV__": ui["btn_export_csv"],
        "__MODE_LABEL__": ui["mode_label"],
        "__MODE_ALL__": ui["mode_all"].replace("{n}", str(len(spec["terms"]))),
        "__MODE_20__": ui["mode_random"].replace("{n}", "20"),
        "__MODE_10__": ui["mode_random"].replace("{n}", "10"),
        "__MODE_5__": ui["mode_random"].replace("{n}", "5"),
        "__LIST_HEADING__": ui["list_heading"],
        "__LEG_MOUNTAINS__": ui["legend_mountains"],
        "__LEG_RIVERS__": ui["legend_rivers"],
        "__LEG_CIRCLES__": ui["legend_circles"],
        "__ZHINT__": ui["zoom_hint"],
        "__RESUME_MSG__": ui["resume_indicator"],
        "__TOTAL__": str(len(spec["terms"])),
        "__TERMS_JSON__": terms_json,
        "__RANDOMIZE_NUMBERS__": "true" if spec.get("randomize_numbers", True) else "false",
        "__MSG_CORRECT__": _json.dumps(ui["msg_correct"]),
        "__MSG_WRONG__": _json.dumps(ui["msg_wrong"]),
        "__MSG_WIN__": _json.dumps(ui["msg_win"]),
        "__MODE_ALL_TPL__": _json.dumps(ui["mode_all"]),
        "__MODE_RANDOM_TPL__": _json.dumps(ui["mode_random"]),
    }
    html = _HTML_TPL
    for k, v in repl.items():
        html = html.replace(k, v)

    pathlib.Path(output_path).write_text(html, encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# PDF rendering (matplotlib) — unchanged from prior version
# ---------------------------------------------------------------------------

def render_pdf(spec, output_path, answer=False):
    """Render a printable PDF (or PNG, by file extension) of the quiz.
    answer=False produces the student worksheet; answer=True the answer key.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle
    from matplotlib.collections import LineCollection
    import numpy as np

    colors = _colors(spec)
    ui = _ui(spec)
    extent_lon = tuple(spec["map"]["extent"]["lon"])
    extent_lat = tuple(spec["map"]["extent"]["lat"])
    mid_lat = spec["map"]["mid_lat_for_aspect"]
    aspect = 1.0 / math.cos(math.radians(mid_lat))

    geo = load_geojson(spec["map"]["_geo_data_resolved"])
    land_polys = []
    border_lines = []
    for ring, is_exterior in iter_polygon_rings(geo["features"], extent_lon, extent_lat, padding=5):
        arr = np.array(ring)
        if is_exterior:
            land_polys.append(arr)
        border_lines.append(arr)

    fig = plt.figure(figsize=(16.5, 8.7), dpi=200)
    axm = fig.add_axes([0.005, 0.04, 0.70, 0.92])
    axl = fig.add_axes([0.71, 0.02, 0.285, 0.96]); axl.axis("off")

    axm.set_facecolor(colors["sea"])
    for arr in land_polys:
        axm.fill(arr[:, 0], arr[:, 1], facecolor=colors["land"], edgecolor="none", zorder=1)
    lc = LineCollection(border_lines, colors=colors["border"], linewidths=0.5, zorder=2)
    axm.add_collection(lc)
    for _, pts in spec["_mountains"]:
        a = np.array(pts)
        axm.plot(a[:, 0], a[:, 1], color=colors["mountain"], lw=2.6, solid_capstyle="round", zorder=3)
        axm.plot(a[:, 0], a[:, 1], color=colors["mountain"], marker="^", ms=4, lw=0, zorder=3)
    for _, pts in spec["_rivers"]:
        a = np.array(pts)
        axm.plot(a[:, 0], a[:, 1], color=colors["river"], lw=1.8, solid_capstyle="round", zorder=3)
    axm.set_xlim(*extent_lon); axm.set_ylim(*extent_lat)
    axm.set_aspect(aspect)
    axm.set_xticks([]); axm.set_yticks([])
    for s in axm.spines.values():
        s.set_edgecolor("#6b6456"); s.set_linewidth(1.2)

    r = 0.95
    for t in spec["terms"]:
        lon, lat = t["label_at"]
        c = Circle((lon, lat), r, facecolor=colors["circle_fill"],
                   edgecolor=colors["circle_edge"], lw=1.4, zorder=5)
        axm.add_patch(c)
        if answer:
            axm.text(lon, lat, str(t["id"]), ha="center", va="center",
                     fontsize=6.8, fontweight="bold", color=colors["circle_edge"], zorder=6)

    title = ui["pdf_title_answer" if answer else "pdf_title_quiz"]
    axm.set_title(title, fontsize=15, fontweight="bold", color="#3a3528", pad=8)

    axl.text(0.0, 0.99, ui["pdf_legend_heading"],
             fontsize=10.5, fontweight="bold", va="top", color="#3a3528",
             transform=axl.transAxes)
    n = len(spec["terms"])
    col_split = (n + 1) // 2
    y0, dy = 0.955, 0.0445
    for i, t in enumerate(spec["terms"]):
        col = 0 if i < col_split else 1
        row = i if i < col_split else i - col_split
        x = 0.0 if col == 0 else 0.52
        y = y0 - row * dy
        axl.text(x, y, f"{t['id']}.", fontsize=8.6, fontweight="bold",
                 va="top", color=colors["circle_edge"], transform=axl.transAxes)
        axl.text(x + 0.045, y, t["name"], fontsize=8.3, va="top",
                 color="#2b2b2b", transform=axl.transAxes)
    axl.text(0.0, 0.03, ui["pdf_legend_symbols"],
             fontsize=8, va="bottom", color="#555", transform=axl.transAxes)

    fig.savefig(output_path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output_path
