"""Render a timeline+MCQ quiz: events with date inputs + multi-correct MCQ
follow-ups. Correctly answered events populate a 4-lane visual timeline.

Spec.yaml schema (top-level keys):
  title, locale, description
  timeline.start_year, timeline.end_year
  lanes — ordered list of {id, label, color}
  ui — strings (button labels, prompts)
  events — list of:
    id, name, lane (matches a lane.id)
    period — one of:
        {start_year, end_year}                — for ranges (reigns, state durations)
        {year}                                 — for single-year events
        {year, month, day}                     — for fully-dated events (battles)
    follow_up — list of MCQ items:
        {q, options: [{text, correct: bool}, ...]}

Output:
  render_html(spec, path) — single self-contained HTML page.

UX flow:
  1. Student sees list of event cards on the left.
  2. Each card has date input(s) + "Proveri datum" button.
  3. Wrong date → shake + miss++ + retry.
  4. Correct date → bar/dot appears on timeline lane;
     follow-up MCQ section opens below the card.
  5. MCQ panel: checkboxes for each option + "Proveri" button.
     Rule: must select EXACTLY all correct options, no wrong ones.
     Wrong → shake + miss++ + retry. Correct → lock green.
  6. Total correct/miss tracked across all events + MCQ items.
"""
import json as _json
import math
import pathlib
import yaml


# ---------------------------------------------------------------------------
# Spec loading
# ---------------------------------------------------------------------------

def load_spec(path):
    """Load and validate spec. Adds computed fields."""
    path = pathlib.Path(path).resolve()
    with open(path) as f:
        spec = yaml.safe_load(f)
    spec["_spec_path"] = str(path)
    spec["_spec_dir"] = str(path.parent)
    # Validate lanes / events
    lane_ids = {l["id"] for l in spec["lanes"]}
    for ev in spec["events"]:
        if ev["lane"] not in lane_ids:
            raise ValueError(f"Event {ev['id']} ({ev.get('name')}) refers to "
                             f"unknown lane '{ev['lane']}'. Defined lanes: {lane_ids}")
        p = ev.get("period") or {}
        has_range = "start_year" in p and "end_year" in p
        has_year = "year" in p
        if not (has_range or has_year):
            raise ValueError(
                f"Event {ev['id']} ({ev.get('name')}) has no valid period. "
                "Need {start_year, end_year} OR {year} OR {year, month, day}.")
        ev["_date_form"] = (
            "range" if has_range else
            ("full" if all(k in p for k in ("year", "month", "day")) else "year")
        )
    return spec


def _ui_default():
    return {
        "header_title": "Vremenska osa",
        "header_subtitle": "Za svaki događaj upiši datum. Kad je tačno, događaj se pojavi na vremenskoj osi i otvoriće se pitanja.",
        "events_heading": "Pojmovi",
        "timeline_heading": "Vremenska osa",
        "btn_check_date": "Proveri datum",
        "btn_check_mcq": "Proveri odgovore",
        "btn_reset": "Počni ispočetka",
        "stat_correct": "Tačno",
        "stat_miss": "Greške",
        "placeholder_start": "od",
        "placeholder_end": "do",
        "placeholder_year": "godina",
        "placeholder_day": "dan",
        "placeholder_month": "mesec",
        "msg_date_correct": "Datum tačan!",
        "msg_date_wrong": "Datum pogrešan — pokušaj ponovo",
        "hint_correct_answer": "Tačan odgovor:",
        "msg_mcq_correct": "Tačno!",
        "msg_mcq_wrong": "Pogrešno — odaberi TAČNO sve tačne odgovore",
        "msg_win": "🎉 Sve rešeno! Ukupno grešaka: {miss}",
        "mcq_instruction": "Odaberi sve tačne odgovore (može biti više od jednog), pa klikni Proveri.",
        "label_event_name": "Događaj",
        "resume_indicator": "Nastavak prethodne sesije — tvoj progres je sačuvan.",
    }


def _ui(spec):
    out = dict(_ui_default())
    out.update(spec.get("ui") or {})
    return out


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

_HTML_TPL = r"""<!DOCTYPE html>
<html lang="__LOCALE__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
 :root{--bg:#faf8f2;--ink:#2b2b2b;--muted:#6b6456;--edge:#b1271f;--accent:#1f7a3a;--border:#e6e0d2;--surface:#fff;--soft:#fefcf7;}
 *{box-sizing:border-box}
 body{margin:0;font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif;color:var(--ink);background:var(--bg);line-height:1.45}
 header{padding:14px 18px;background:var(--surface);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:50}
 h1{margin:0 0 4px;font-size:19px;color:#3a3528}
 .sub{font-size:13px;color:var(--muted);margin:0;max-width:980px}
 .bar{display:flex;gap:14px;flex-wrap:wrap;align-items:center;margin-top:10px;font-size:14px}
 .stat{background:#f3ecd8;border:1px solid #e1d8c2;border-radius:8px;padding:6px 12px}
 .stat b{font-size:16px}
 .ok{color:var(--accent)} .bad{color:var(--edge)}
 button{font:inherit;padding:7px 14px;border:1px solid var(--edge);background:var(--surface);color:var(--edge);border-radius:8px;cursor:pointer}
 button:hover{background:var(--edge);color:#fff}
 button.success{border-color:var(--accent);color:var(--accent)}
 button.success:hover{background:var(--accent);color:#fff}
 .resume-banner{display:none;margin-top:8px;background:#fffbe6;border:1px solid #f0d878;border-radius:8px;padding:6px 12px;font-size:13px;color:#7a5a00}
 .resume-banner.show{display:block}

 .layout{display:grid;grid-template-columns:minmax(360px, 480px) 1fr;align-items:flex-start;gap:0}
 .events-col{padding:14px 16px;border-right:1px solid var(--border);background:var(--surface);max-height:calc(100vh - var(--htop,0px));overflow:auto;position:sticky;top:var(--htop,0px)}
 .events-col h2{margin:0 0 12px;font-size:15px;color:#3a3528}
 .timeline-col{padding:16px;min-width:0}

 ol.events{list-style:none;padding:0;margin:0}
 .event{background:var(--soft);border:1px solid var(--border);border-radius:10px;padding:12px 14px;margin-bottom:10px;transition:border-color .15s,background .15s}
 .event.locked{background:#d8f0dd;border-color:var(--accent)}
 .event-head{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
 .event-name{font-weight:700;font-size:14px;color:#3a3528}
 .lane-chip{font-size:11px;padding:2px 8px;border-radius:10px;color:#fff;text-transform:uppercase;letter-spacing:0.5px;flex-shrink:0}
 .date-row{margin-top:10px;display:flex;align-items:center;gap:6px;flex-wrap:wrap;font-size:13px}
 .date-row input[type=number]{font:inherit;width:64px;padding:5px 7px;border:1px solid #b1271f;border-radius:6px;text-align:center;color:#3a3528;background:#fff}
 .date-row input[type=number].correct{border-color:var(--accent);background:#e8f5ec;color:var(--accent)}
 .date-row input[type=number].wrong{border-color:var(--edge);background:#fdd;animation:shake .3s}
 .date-row input[type=number]:read-only{background:#e8f5ec;border-color:var(--accent);color:var(--accent);cursor:default}
 .date-row .sep{color:var(--muted)}
 .date-row .miss-badge{background:var(--edge);color:#fff;font-size:11px;padding:1px 7px;border-radius:9px;display:none}
 .date-row .miss-badge.show{display:inline-block}
 .date-row .check-date{padding:5px 10px;font-size:12px}
 .date-hint{display:none;flex-basis:100%;font-size:12px;color:#7a5a00;background:#fffbe6;border:1px solid #f0d878;border-radius:6px;padding:4px 8px;margin-top:6px}
 .date-hint.show{display:block}
 .explanation{display:none;flex-basis:100%;font-size:12.5px;line-height:1.5;border-radius:6px;padding:7px 10px;margin-top:6px;border:1px solid #d8d2c2;background:#fefcf7;color:#3a3528}
 .explanation.show{display:block}
 .explanation.correct{background:#e8f5ec;border-color:#1f7a3a;color:#13602c}
 .explanation .badge-icon{display:inline-block;margin-right:6px;font-weight:700}
 .explanation.correct .badge-icon{color:#1f7a3a}
 .explanation:not(.correct) .badge-icon{color:#6b6456}
 @keyframes shake{0%,100%{transform:translateX(0)}25%{transform:translateX(-4px)}75%{transform:translateX(4px)}}

 .follow-up{display:none;margin-top:12px;border-top:1px dashed var(--border);padding-top:10px}
 .event.unlocked .follow-up{display:block}
 .mcq-intro{font-size:12px;color:var(--muted);margin:0 0 8px}
 .mcq-q{margin-bottom:12px;padding:10px;background:var(--surface);border:1px solid var(--border);border-radius:8px}
 .mcq-q.locked{background:#e8f5ec;border-color:var(--accent)}
 .mcq-q .q{font-size:13px;font-weight:600;color:#3a3528;margin:0 0 8px}
 .mcq-q ul{list-style:none;padding:0;margin:0 0 8px}
 .mcq-q li{padding:4px 0}
 .mcq-q label{display:flex;align-items:flex-start;gap:8px;font-size:13px;cursor:pointer;padding:5px 8px;border-radius:5px}
 .mcq-q label:hover{background:#f5efde}
 .mcq-q.locked label{cursor:default}
 .mcq-q.locked label:hover{background:transparent}
 .mcq-q label.correct{background:#d8f0dd;color:var(--accent);font-weight:600}
 .mcq-q label.incorrect-selected{background:#fdd;color:var(--edge)}
 .mcq-q input[type=checkbox]{margin-top:2px;cursor:pointer;flex-shrink:0}
 .mcq-q .actions{display:flex;align-items:center;gap:8px;margin-top:6px}
 .mcq-q .check-mcq{padding:4px 10px;font-size:12px}
 .mcq-q .miss-badge{background:var(--edge);color:#fff;font-size:11px;padding:1px 7px;border-radius:9px;display:none}
 .mcq-q .miss-badge.show{display:inline-block}
 .mcq-q.locked .actions{display:none}
 .mcq-q.locked .feedback-locked{display:inline-block;color:var(--accent);font-size:12px;font-weight:600}
 .feedback-locked{display:none}

 .timeline-col{display:flex;flex-direction:column;height:calc(100vh - var(--htop,0px));position:sticky;top:var(--htop,0px)}
 .timeline-col h2{margin:0 0 8px;font-size:15px;color:#3a3528;flex:0 0 auto;padding:0 4px}
 .timeline-wrap{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 8px 8px;flex:1 1 auto;min-height:0;display:flex;flex-direction:column}
 svg.timeline{width:100%;height:100%;flex:1 1 auto;min-height:0;display:block;background:#faf8f2;border-radius:6px}

 #msg{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);background:var(--edge);color:#fff;padding:10px 18px;border-radius:24px;font-size:14px;font-weight:600;opacity:0;transition:opacity .25s;pointer-events:none;z-index:99}
 #msg.show{opacity:1}
 .win{background:#d8f0dd;border-color:var(--accent);color:#13602c;font-weight:700;padding:6px 14px;border-radius:8px;display:none}

 @media (max-width:860px){
   .layout{grid-template-columns:1fr}
   .events-col{position:static;max-height:none;border-right:none;border-bottom:1px solid var(--border)}
   .timeline-wrap{position:static}
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
  <span class="stat win" id="win"></span>
 </div>
 <div id="resumeBanner" class="resume-banner">__RESUME_MSG__</div>
</header>

<div class="layout">
 <aside class="events-col">
  <h2>__EVENTS_HEAD__</h2>
  <ol class="events">__EVENTS_HTML__</ol>
 </aside>
 <main class="timeline-col">
  <div class="timeline-wrap">
   <h2>__TIMELINE_HEAD__</h2>
   <svg class="timeline" id="timeline" viewBox="0 0 __TL_W__ __TL_H__" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="none">
    __TIMELINE_BG__
   </svg>
  </div>
 </main>
</div>

<div id="msg"></div>

<script>
const ALL_EVENTS = __EVENTS_JSON__;
const LANES = __LANES_JSON__;
const TIMELINE = __TIMELINE_JSON__;
const STATE_KEY = 'classroom:' + window.location.pathname;
const STATE_VERSION = 1;
const MSG_DATE_CORRECT = __MSG_DATE_CORRECT__, MSG_DATE_WRONG = __MSG_DATE_WRONG__;
const MSG_MCQ_CORRECT = __MSG_MCQ_CORRECT__, MSG_MCQ_WRONG = __MSG_MCQ_WRONG__;
const MSG_WIN_TPL = __MSG_WIN__;
const HINT_LABEL = __HINT_LABEL__;

function formatCorrectDate(ev) {
  const p = ev.period;
  if (ev._date_form === 'range') return p.start_year + ' — ' + p.end_year;
  if (ev._date_form === 'full') return p.day + '. ' + p.month + '. ' + p.year + '.';
  return p.year;
}

function showExplanation(container, isCorrect) {
  const text = container.dataset.explanation;
  if (!text) return;
  const elClass = container.classList.contains('event') ? '.date-explanation' : '.mcq-explanation';
  const el = container.querySelector(':scope > ' + elClass) ||
             container.querySelector(':scope > .date-row > ' + elClass) ||
             container.querySelector(elClass);
  if (!el) return;
  const icon = isCorrect ? '✓' : 'ⓘ';
  el.innerHTML = '<span class="badge-icon">' + icon + '</span>' + text;
  el.classList.toggle('correct', !!isCorrect);
  el.classList.add('show');
}

const cCorrect = document.getElementById('cCorrect');
const cMiss = document.getElementById('cMiss');
const cTotal = document.getElementById('cTotal');
const msg = document.getElementById('msg');
const win = document.getElementById('win');
const resetBtn = document.getElementById('reset');
const resumeBanner = document.getElementById('resumeBanner');
const svg = document.getElementById('timeline');

let msgT = null;

function showMsg(t, ok) {
  msg.textContent = t;
  msg.style.background = ok ? '#1f7a3a' : '#b1271f';
  msg.classList.add('show');
  clearTimeout(msgT);
  msgT = setTimeout(() => msg.classList.remove('show'), 1400);
}

// --- timeline coordinate math ---
function yearToX(year) {
  const t = (year - TIMELINE.start_year) / (TIMELINE.end_year - TIMELINE.start_year);
  return TIMELINE.axis_x0 + t * (TIMELINE.axis_x1 - TIMELINE.axis_x0);
}
// Runtime sub-row assignment: per-lane, track which intervals have been placed
// in each sub-row. When a new event is placed, find the first sub-row where it
// doesn't overlap in time with any already-placed event; else create a new sub-row.
const placedSubRows = {};
LANES.forEach(l => placedSubRows[l.id] = []);

function eventInterval(ev) {
  // Extend each event's effective end by a label buffer (~22 years) so that
  // single-year events with adjacent years don't visually overlap with their
  // labels. The overlap algorithm then places them in different sub-rows.
  const LABEL_BUFFER_YEARS = 22;
  const p = ev.period;
  if ('start_year' in p) return [p.start_year, p.end_year + LABEL_BUFFER_YEARS];
  return [p.year, p.year + LABEL_BUFFER_YEARS];
}

function findOrCreateSubRow(laneId, start, end, eventId) {
  const rows = placedSubRows[laneId];
  for (let i = 0; i < rows.length; i++) {
    const overlaps = rows[i].some(iv => !(iv.end < start || iv.start > end));
    if (!overlaps) {
      rows[i].push({ start, end, eventId });
      return i;
    }
  }
  rows.push([{ start, end, eventId }]);
  return rows.length - 1;
}

function removeFromSubRows(eventId, laneId) {
  const rows = placedSubRows[laneId];
  for (let i = 0; i < rows.length; i++) {
    rows[i] = rows[i].filter(iv => iv.eventId !== eventId);
  }
}

function laneY(ev, subRow) {
  // Returns the y-coordinate for an event's placement on the timeline at a
  // specific sub-row index within its lane.
  for (let i = 0; i < LANES.length; i++) {
    if (LANES[i].id === ev.lane) {
      const top = TIMELINE.lane_tops[i];
      const pad = TIMELINE.lane_padding;
      const sh = TIMELINE.sub_row_height;
      return top + pad + subRow * sh + sh / 2;
    }
  }
  return TIMELINE.lane_y0;
}
function laneColor(laneId) {
  for (const l of LANES) if (l.id === laneId) return l.color;
  return '#999';
}

// --- draw event on timeline ---
function drawEventOnTimeline(ev) {
  const color = laneColor(ev.lane);
  const [iStart, iEnd] = eventInterval(ev);
  const subRow = findOrCreateSubRow(ev.lane, iStart, iEnd, ev.id);
  const y = laneY(ev, subRow);
  const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  g.setAttribute('data-event-id', ev.id);
  g.setAttribute('class', 'tl-event');
  if (ev._date_form === 'range') {
    const x1 = yearToX(ev.period.start_year);
    const x2 = yearToX(ev.period.end_year);
    const w = Math.max(2, x2 - x1);
    const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    rect.setAttribute('x', x1); rect.setAttribute('y', y - 10);
    rect.setAttribute('width', w); rect.setAttribute('height', 20);
    rect.setAttribute('fill', color); rect.setAttribute('rx', 4); rect.setAttribute('opacity', '0.85');
    g.appendChild(rect);
    const lbl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    lbl.setAttribute('x', x1 + w / 2); lbl.setAttribute('y', y + 4);
    lbl.setAttribute('text-anchor', 'middle'); lbl.setAttribute('fill', '#fff');
    lbl.setAttribute('font-size', '11'); lbl.setAttribute('font-weight', '700');
    lbl.setAttribute('font-family', 'system-ui, sans-serif');
    lbl.textContent = ev.name.length > w / 6 ? '' : ev.name;
    g.appendChild(lbl);
    // External label if name is too long for the bar
    if (!lbl.textContent) {
      const ext = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      ext.setAttribute('x', x1 + w + 4); ext.setAttribute('y', y + 4);
      ext.setAttribute('fill', color); ext.setAttribute('font-size', '11');
      ext.setAttribute('font-weight', '600'); ext.setAttribute('font-family', 'system-ui, sans-serif');
      ext.textContent = ev.name;
      g.appendChild(ext);
    }
  } else {
    const yr = ev.period.year;
    const x = yearToX(yr);
    const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    c.setAttribute('cx', x); c.setAttribute('cy', y); c.setAttribute('r', 6);
    c.setAttribute('fill', color); c.setAttribute('stroke', '#fff'); c.setAttribute('stroke-width', '1.5');
    g.appendChild(c);
    const lbl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    lbl.setAttribute('x', x + 8); lbl.setAttribute('y', y + 4);
    lbl.setAttribute('fill', color); lbl.setAttribute('font-size', '11');
    lbl.setAttribute('font-weight', '600'); lbl.setAttribute('font-family', 'system-ui, sans-serif');
    lbl.textContent = ev.name + ' (' + yr + ')';
    g.appendChild(lbl);
  }
  svg.appendChild(g);
}

function removeEventFromTimeline(eventId) {
  const g = svg.querySelector(`g.tl-event[data-event-id="${eventId}"]`);
  if (g) g.remove();
  // Clean up sub-row tracking for this event across all lanes
  for (const laneId of Object.keys(placedSubRows)) {
    removeFromSubRows(eventId, laneId);
  }
}

// --- date check ---
function checkDate(eventCard) {
  const evId = parseInt(eventCard.dataset.id);
  const ev = ALL_EVENTS.find(e => e.id === evId);
  if (!ev || eventCard.classList.contains('date-correct')) return;
  const inputs = eventCard.querySelectorAll('input[type=number]');
  const values = {};
  let allFilled = true;
  inputs.forEach(inp => {
    const v = inp.value.trim();
    if (v === '') { allFilled = false; return; }
    values[inp.dataset.field] = parseInt(v);
  });
  if (!allFilled) return;
  let correct = false;
  if (ev._date_form === 'range') {
    correct = values.start === ev.period.start_year && values.end === ev.period.end_year;
  } else if (ev._date_form === 'full') {
    correct = values.year === ev.period.year && values.month === ev.period.month && values.day === ev.period.day;
  } else {
    correct = values.year === ev.period.year;
  }
  const hint = eventCard.querySelector('.date-hint');
  if (correct) {
    inputs.forEach(inp => { inp.readOnly = true; inp.classList.remove('wrong'); inp.classList.add('correct'); });
    eventCard.classList.add('date-correct', 'unlocked');
    if (hint) { hint.classList.remove('show'); hint.textContent = ''; }
    drawEventOnTimeline(ev);
    showExplanation(eventCard, true);
    showMsg(MSG_DATE_CORRECT, true);
  } else {
    inputs.forEach(inp => { inp.classList.add('wrong'); });
    const badge = eventCard.querySelector('.date-row .miss-badge');
    const m = (parseInt(eventCard.dataset.dateMiss) || 0) + 1;
    eventCard.dataset.dateMiss = m;
    badge.textContent = m;
    badge.classList.add('show');
    // Show correct answer as hint so student can re-type it
    if (hint) {
      hint.textContent = HINT_LABEL + ' ' + formatCorrectDate(ev);
      hint.classList.add('show');
    }
    // Also show the explanation (without correct marker)
    showExplanation(eventCard, false);
    showMsg(MSG_DATE_WRONG, false);
    setTimeout(() => {
      inputs.forEach(inp => { inp.classList.remove('wrong'); inp.value = ''; });
      inputs[0]?.focus();
    }, 420);
  }
  recountAll();
  saveState();
}

// --- MCQ check ---
function checkMcq(mcqEl) {
  if (mcqEl.classList.contains('locked')) return;
  const evId = parseInt(mcqEl.closest('.event').dataset.id);
  const qIdx = parseInt(mcqEl.dataset.qIdx);
  const ev = ALL_EVENTS.find(e => e.id === evId);
  const q = ev.follow_up[qIdx];
  const selectedSet = new Set();
  mcqEl.querySelectorAll('input[type=checkbox]').forEach(cb => {
    if (cb.checked) selectedSet.add(parseInt(cb.dataset.optIdx));
  });
  const correctSet = new Set(q.options.map((o, i) => o.correct ? i : null).filter(i => i !== null));
  const isExact = selectedSet.size === correctSet.size &&
                   [...selectedSet].every(i => correctSet.has(i));
  if (isExact) {
    mcqEl.classList.add('locked');
    mcqEl.querySelectorAll('label').forEach(lbl => {
      const idx = parseInt(lbl.querySelector('input').dataset.optIdx);
      lbl.querySelector('input').disabled = true;
      if (correctSet.has(idx)) lbl.classList.add('correct');
    });
    showExplanation(mcqEl, true);
    showMsg(MSG_MCQ_CORRECT, true);
  } else {
    // Highlight wrong selections briefly
    mcqEl.querySelectorAll('label').forEach(lbl => {
      const cb = lbl.querySelector('input');
      const idx = parseInt(cb.dataset.optIdx);
      if (cb.checked && !correctSet.has(idx)) lbl.classList.add('incorrect-selected');
    });
    const m = (parseInt(mcqEl.dataset.miss) || 0) + 1;
    mcqEl.dataset.miss = m;
    const badge = mcqEl.querySelector('.miss-badge');
    badge.textContent = m; badge.classList.add('show');
    showExplanation(mcqEl, false);
    showMsg(MSG_MCQ_WRONG, false);
    setTimeout(() => {
      mcqEl.querySelectorAll('label').forEach(lbl => lbl.classList.remove('incorrect-selected'));
    }, 800);
  }
  recountAll();
  saveState();
}

// --- recount total correct/miss ---
function recountAll() {
  let correct = 0, miss = 0;
  for (const card of document.querySelectorAll('.event')) {
    if (card.classList.contains('date-correct')) correct++;
    miss += parseInt(card.dataset.dateMiss) || 0;
    for (const mcq of card.querySelectorAll('.mcq-q')) {
      if (mcq.classList.contains('locked')) correct++;
      miss += parseInt(mcq.dataset.miss) || 0;
    }
  }
  cCorrect.textContent = correct;
  cMiss.textContent = miss;
  const total = parseInt(cTotal.textContent);
  if (correct === total) {
    win.style.display = 'inline-block';
    win.textContent = MSG_WIN_TPL.replace('{miss}', miss);
  } else {
    win.style.display = 'none';
  }
}

// --- state save/restore ---
function saveState() {
  const state = { v: STATE_VERSION, events: {} };
  for (const card of document.querySelectorAll('.event')) {
    const id = parseInt(card.dataset.id);
    const e = { dc: card.classList.contains('date-correct'), dm: parseInt(card.dataset.dateMiss) || 0, mcq: {} };
    card.querySelectorAll('.mcq-q').forEach((mcq, idx) => {
      const qIdx = parseInt(mcq.dataset.qIdx);
      e.mcq[qIdx] = { c: mcq.classList.contains('locked'), m: parseInt(mcq.dataset.miss) || 0 };
    });
    state.events[id] = e;
  }
  try { localStorage.setItem(STATE_KEY, JSON.stringify(state)); } catch (e) {}
}
function loadState() {
  try {
    const s = localStorage.getItem(STATE_KEY);
    if (!s) return null;
    const obj = JSON.parse(s);
    if (obj.v !== STATE_VERSION) return null;
    return obj;
  } catch (e) { return null; }
}
function clearState() {
  try { localStorage.removeItem(STATE_KEY); } catch (e) {}
}
function applyState(state) {
  const toPlace = [];  // events to draw on timeline, will be sorted chronologically
  for (const card of document.querySelectorAll('.event')) {
    const id = parseInt(card.dataset.id);
    const ev = ALL_EVENTS.find(e => e.id === id);
    const s = state.events[id];
    if (!s) continue;
    card.dataset.dateMiss = s.dm || 0;
    if (s.dm > 0) {
      const b = card.querySelector('.date-row .miss-badge');
      b.textContent = s.dm; b.classList.add('show');
    }
    if (s.dc) {
      // Restore date inputs to correct values + lock + draw on timeline
      const inputs = card.querySelectorAll('input[type=number]');
      if (ev._date_form === 'range') {
        inputs.forEach(inp => {
          if (inp.dataset.field === 'start') inp.value = ev.period.start_year;
          if (inp.dataset.field === 'end') inp.value = ev.period.end_year;
        });
      } else if (ev._date_form === 'full') {
        inputs.forEach(inp => {
          if (inp.dataset.field === 'year') inp.value = ev.period.year;
          if (inp.dataset.field === 'month') inp.value = ev.period.month;
          if (inp.dataset.field === 'day') inp.value = ev.period.day;
        });
      } else {
        inputs.forEach(inp => { if (inp.dataset.field === 'year') inp.value = ev.period.year; });
      }
      inputs.forEach(inp => { inp.readOnly = true; inp.classList.add('correct'); });
      card.classList.add('date-correct', 'unlocked');
      toPlace.push(ev);
      showExplanation(card, true);
    } else if (s.dm > 0) {
      // Date was checked at least once but is not yet correct — show explanation as previously seen
      showExplanation(card, false);
    }
    // Restore MCQ states
    card.querySelectorAll('.mcq-q').forEach(mcq => {
      const qIdx = parseInt(mcq.dataset.qIdx);
      const ms = s.mcq?.[qIdx];
      if (!ms) return;
      mcq.dataset.miss = ms.m || 0;
      if (ms.m > 0) {
        const b = mcq.querySelector('.miss-badge');
        b.textContent = ms.m; b.classList.add('show');
      }
      if (ms.c) {
        const q = ev.follow_up[qIdx];
        const correctSet = new Set(q.options.map((o, i) => o.correct ? i : null).filter(i => i !== null));
        mcq.classList.add('locked');
        mcq.querySelectorAll('label').forEach(lbl => {
          const cb = lbl.querySelector('input');
          const idx = parseInt(cb.dataset.optIdx);
          cb.disabled = true;
          if (correctSet.has(idx)) { cb.checked = true; lbl.classList.add('correct'); }
        });
        showExplanation(mcq, true);
      } else if (ms.m > 0) {
        showExplanation(mcq, false);
      }
    });
  }
  // Place restored events on timeline in chronological order so sub-row
  // assignment is deterministic regardless of original answer order.
  toPlace.sort((a, b) => eventInterval(a)[0] - eventInterval(b)[0]);
  for (const ev of toPlace) drawEventOnTimeline(ev);
  resumeBanner.classList.add('show');
}

// --- wiring ---
document.querySelectorAll('.check-date').forEach(btn => {
  btn.addEventListener('click', () => checkDate(btn.closest('.event')));
});
document.querySelectorAll('.date-row input').forEach(inp => {
  inp.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); checkDate(inp.closest('.event')); } });
});
document.querySelectorAll('.check-mcq').forEach(btn => {
  btn.addEventListener('click', () => checkMcq(btn.closest('.mcq-q')));
});

resetBtn.addEventListener('click', () => {
  // Clear sub-row tracking so events can be re-placed fresh
  for (const laneId of Object.keys(placedSubRows)) placedSubRows[laneId] = [];
  for (const card of document.querySelectorAll('.event')) {
    card.classList.remove('date-correct', 'unlocked');
    card.dataset.dateMiss = '0';
    const b = card.querySelector('.date-row .miss-badge'); b.classList.remove('show'); b.textContent = '0';
    const hint = card.querySelector('.date-hint'); if (hint) { hint.classList.remove('show'); hint.textContent = ''; }
    card.querySelectorAll('input[type=number]').forEach(inp => { inp.value = ''; inp.readOnly = false; inp.classList.remove('correct', 'wrong'); });
    card.querySelectorAll('.mcq-q').forEach(mcq => {
      mcq.classList.remove('locked');
      mcq.dataset.miss = '0';
      const mb = mcq.querySelector('.miss-badge'); mb.classList.remove('show'); mb.textContent = '0';
      mcq.querySelectorAll('input[type=checkbox]').forEach(cb => { cb.checked = false; cb.disabled = false; });
      mcq.querySelectorAll('label').forEach(lbl => lbl.classList.remove('correct', 'incorrect-selected'));
      const me = mcq.querySelector('.mcq-explanation'); if (me) { me.classList.remove('show', 'correct'); me.innerHTML = ''; }
    });
    const de = card.querySelector('.date-explanation'); if (de) { de.classList.remove('show', 'correct'); de.innerHTML = ''; }
    const evId = parseInt(card.dataset.id);
    removeEventFromTimeline(evId);
  }
  resumeBanner.classList.remove('show');
  clearState();
  recountAll();
});

// --- init ---
function setHeaderTop() {
  const h = document.querySelector('header').offsetHeight;
  document.documentElement.style.setProperty('--htop', h + 'px');
}
window.addEventListener('resize', setHeaderTop);
setHeaderTop();
const saved = loadState();
if (saved) applyState(saved);
recountAll();
</script>
</body>
</html>"""


def _render_event_card(ev, lanes_by_id, ui):
    """HTML for one event card with date inputs + follow-up MCQ panel."""
    lane = lanes_by_id[ev["lane"]]
    p = ev["period"]
    form = ev["_date_form"]
    if form == "range":
        date_inputs = (
            f'<input type="number" data-field="start" placeholder="{ui["placeholder_start"]}" inputmode="numeric" autocomplete="off">'
            f'<span class="sep">—</span>'
            f'<input type="number" data-field="end" placeholder="{ui["placeholder_end"]}" inputmode="numeric" autocomplete="off">'
        )
    elif form == "full":
        date_inputs = (
            f'<input type="number" data-field="day" placeholder="{ui["placeholder_day"]}" inputmode="numeric" autocomplete="off" min="1" max="31" style="width:50px">'
            f'<span class="sep">.</span>'
            f'<input type="number" data-field="month" placeholder="{ui["placeholder_month"]}" inputmode="numeric" autocomplete="off" min="1" max="12" style="width:50px">'
            f'<span class="sep">.</span>'
            f'<input type="number" data-field="year" placeholder="{ui["placeholder_year"]}" inputmode="numeric" autocomplete="off">'
        )
    else:
        date_inputs = (
            f'<input type="number" data-field="year" placeholder="{ui["placeholder_year"]}" inputmode="numeric" autocomplete="off">'
        )

    mcq_html = ""
    if ev.get("follow_up"):
        for q_idx, q in enumerate(ev["follow_up"]):
            opts_html = ""
            for o_idx, opt in enumerate(q["options"]):
                opts_html += (
                    f'<li><label>'
                    f'<input type="checkbox" data-opt-idx="{o_idx}">'
                    f'<span>{_escape(opt["text"])}</span>'
                    f'</label></li>'
                )
            q_expl = q.get("explanation", "")
            q_expl_attr = f' data-explanation="{_escape(q_expl)}"' if q_expl else ''
            mcq_html += (
                f'<div class="mcq-q" data-q-idx="{q_idx}" data-miss="0"{q_expl_attr}>'
                f'<p class="q">{_escape(q["q"])}</p>'
                f'<ul>{opts_html}</ul>'
                f'<div class="actions">'
                f'<button class="check-mcq">{ui["btn_check_mcq"]}</button>'
                f'<span class="miss-badge">0</span>'
                f'<span class="feedback-locked">✓ {ui["msg_mcq_correct"]}</span>'
                f'</div>'
                f'<div class="explanation mcq-explanation"></div>'
                f'</div>'
            )
        mcq_html = (
            f'<div class="follow-up">'
            f'<p class="mcq-intro">{ui["mcq_instruction"]}</p>'
            f'{mcq_html}'
            f'</div>'
        )

    date_expl = ev.get("date_explanation", "")
    date_expl_attr = f' data-explanation="{_escape(date_expl)}"' if date_expl else ''
    return (
        f'<li class="event" data-id="{ev["id"]}" data-date-miss="0"{date_expl_attr}>'
        f'<div class="event-head">'
        f'<span class="event-name">{_escape(ev["name"])}</span>'
        f'<span class="lane-chip" style="background:{lane["color"]}">{_escape(lane["label"])}</span>'
        f'</div>'
        f'<div class="date-row">'
        f'{date_inputs}'
        f'<button class="check-date">{ui["btn_check_date"]}</button>'
        f'<span class="miss-badge">0</span>'
        f'<span class="date-hint"></span>'
        f'<div class="explanation date-explanation"></div>'
        f'</div>'
        f'{mcq_html}'
        f'</li>'
    )


def _escape(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;'))


def _event_interval(ev):
    """Return (start_year, effective_end_year) for an event for overlap testing.
    The effective end year is extended by a 'label buffer' to account for
    the horizontal space the event's text label occupies in the rendered SVG —
    otherwise single-year events with adjacent years (e.g., 1389 and 1396)
    would be placed in the same sub-row even though their labels overlap visually."""
    LABEL_BUFFER_YEARS = 22
    p = ev["period"]
    if "start_year" in p:
        return p["start_year"], p["end_year"] + LABEL_BUFFER_YEARS
    return p["year"], p["year"] + LABEL_BUFFER_YEARS


def _assign_subrows(events):
    """Greedy bin-packing: assign each event a sub-row index within its lane,
    so events that overlap in time are stacked vertically.
    Returns (sub_row_by_event_id, max_subrows_by_lane)."""
    by_lane = {}
    for ev in events:
        by_lane.setdefault(ev["lane"], []).append(ev)
    sub_row_map = {}
    max_subrows = {}
    for lane, evs in by_lane.items():
        evs_sorted = sorted(evs, key=lambda e: _event_interval(e)[0])
        sub_rows_end = []  # last end_year per sub_row
        for ev in evs_sorted:
            start, end = _event_interval(ev)
            placed = False
            for i in range(len(sub_rows_end)):
                # Allow placement if existing end < new start (no overlap)
                if sub_rows_end[i] < start:
                    sub_row_map[ev["id"]] = i
                    sub_rows_end[i] = end
                    placed = True
                    break
            if not placed:
                sub_row_map[ev["id"]] = len(sub_rows_end)
                sub_rows_end.append(end)
        max_subrows[lane] = max(1, len(sub_rows_end))
    return sub_row_map, max_subrows


def _render_timeline_bg(timeline, lanes, ui):
    """Render the static timeline scaffolding: lane backgrounds + year axis.
    Uses timeline['lane_tops'] (list of y-positions per lane) and
    timeline['lane_heights'] (list of heights per lane) for dynamic per-lane size."""
    tl = timeline
    parts = []
    # Lane background strips + labels
    for i, l in enumerate(lanes):
        y = tl["lane_tops"][i]
        h = tl["lane_heights"][i]
        # Lane row background (alternating tint)
        parts.append(
            f'<rect x="{tl["axis_x0"]}" y="{y}" '
            f'width="{tl["axis_x1"] - tl["axis_x0"]}" height="{h}" '
            f'fill="{"#f5efde" if i % 2 == 0 else "#faf8f2"}"/>'
        )
        # Lane label (left edge, vertically centered in the lane)
        parts.append(
            f'<text x="{tl["axis_x0"] - 8}" y="{y + h/2 + 4}" '
            f'text-anchor="end" fill="{l["color"]}" font-size="13" font-weight="700" '
            f'font-family="system-ui, sans-serif">{_escape(l["label"])}</text>'
        )
    # Year axis (bottom — past last lane)
    axis_y = tl["lane_tops"][-1] + tl["lane_heights"][-1] + 4
    parts.append(
        f'<line x1="{tl["axis_x0"]}" y1="{axis_y}" x2="{tl["axis_x1"]}" y2="{axis_y}" '
        f'stroke="#6b6456" stroke-width="1"/>'
    )
    # Year tick marks every 50 years
    step = 50 if (tl["end_year"] - tl["start_year"]) <= 600 else 100
    yr = (tl["start_year"] // step) * step
    if yr < tl["start_year"]: yr += step
    while yr <= tl["end_year"]:
        t = (yr - tl["start_year"]) / (tl["end_year"] - tl["start_year"])
        x = tl["axis_x0"] + t * (tl["axis_x1"] - tl["axis_x0"])
        parts.append(f'<line x1="{x:.1f}" y1="{axis_y}" x2="{x:.1f}" y2="{axis_y + 5}" stroke="#6b6456"/>')
        parts.append(
            f'<text x="{x:.1f}" y="{axis_y + 18}" text-anchor="middle" '
            f'fill="#6b6456" font-size="11" font-family="system-ui, sans-serif">{yr}</text>'
        )
        yr += step
    return "".join(parts)


def render_html(spec, output_path):
    """Render the timeline-mcq quiz HTML to output_path."""
    ui = _ui(spec)
    lanes = spec["lanes"]
    lanes_by_id = {l["id"]: l for l in lanes}
    events = spec["events"]

    # Compute the worst-case sub-row count across ALL lanes (used to size all
    # lanes equally). Runtime JS does the actual placement; this just ensures
    # the canvas has enough vertical space if all events get placed.
    _, max_subrows = _assign_subrows(events)
    max_subrows_across_lanes = max(max_subrows.values()) if max_subrows else 1

    # Compute timeline canvas dimensions
    tl_width = 1100
    lane_label_pad = 90
    axis_x0 = lane_label_pad
    axis_x1 = tl_width - 12
    sub_row_height = 28          # height per sub-row within a lane
    lane_padding = 6             # vertical padding inside each lane
    lane_y0 = 12
    axis_height = 28

    # All lanes get the SAME height (= max needed across any lane), so the
    # 4 traka are visually uniform regardless of how many events live in each.
    uniform_lane_height = max_subrows_across_lanes * sub_row_height + 2 * lane_padding
    lane_heights = [uniform_lane_height for _ in lanes]
    lane_tops = []
    cursor_y = lane_y0
    for _ in lanes:
        lane_tops.append(cursor_y)
        cursor_y += uniform_lane_height
    tl_height = cursor_y + axis_height

    timeline = {
        "start_year": spec["timeline"]["start_year"],
        "end_year": spec["timeline"]["end_year"],
        "axis_x0": axis_x0,
        "axis_x1": axis_x1,
        "lane_y0": lane_y0,
        "lane_tops": lane_tops,
        "lane_heights": lane_heights,
        "sub_row_height": sub_row_height,
        "lane_padding": lane_padding,
    }

    # Events HTML
    events_html = "".join(_render_event_card(ev, lanes_by_id, ui) for ev in events)

    # Timeline background SVG
    timeline_bg = _render_timeline_bg(timeline, lanes, ui)

    # Total points: 1 per correct date + 1 per correct MCQ
    total_points = len(events) + sum(len(ev.get("follow_up") or []) for ev in events)

    # Strip internal fields before JSON serialization (keep clean for browser)
    events_for_js = []
    for ev in events:
        events_for_js.append({
            "id": ev["id"],
            "name": ev["name"],
            "lane": ev["lane"],
            "period": ev["period"],
            "_date_form": ev["_date_form"],
            "follow_up": ev.get("follow_up", []),
        })

    repl = {
        "__LOCALE__": spec.get("locale", "en"),
        "__TITLE__": ui["header_title"],
        "__HDR_TITLE__": ui["header_title"],
        "__HDR_SUB__": ui["header_subtitle"],
        "__EVENTS_HEAD__": ui["events_heading"],
        "__TIMELINE_HEAD__": ui["timeline_heading"],
        "__LBL_CORRECT__": ui["stat_correct"],
        "__LBL_MISS__": ui["stat_miss"],
        "__BTN_RESET__": ui["btn_reset"],
        "__RESUME_MSG__": ui["resume_indicator"],
        "__EVENTS_HTML__": events_html,
        "__TIMELINE_BG__": timeline_bg,
        "__TL_W__": str(tl_width),
        "__TL_H__": str(tl_height),
        "__TOTAL__": str(total_points),
        "__EVENTS_JSON__": _json.dumps(events_for_js, ensure_ascii=False),
        "__LANES_JSON__": _json.dumps(lanes, ensure_ascii=False),
        "__TIMELINE_JSON__": _json.dumps(timeline, ensure_ascii=False),
        "__MSG_DATE_CORRECT__": _json.dumps(ui["msg_date_correct"]),
        "__MSG_DATE_WRONG__": _json.dumps(ui["msg_date_wrong"]),
        "__HINT_LABEL__": _json.dumps(ui["hint_correct_answer"]),
        "__MSG_MCQ_CORRECT__": _json.dumps(ui["msg_mcq_correct"]),
        "__MSG_MCQ_WRONG__": _json.dumps(ui["msg_mcq_wrong"]),
        "__MSG_WIN__": _json.dumps(ui["msg_win"]),
    }
    html = _HTML_TPL
    for k, v in repl.items():
        html = html.replace(k, v)
    pathlib.Path(output_path).write_text(html, encoding="utf-8")
    return output_path
