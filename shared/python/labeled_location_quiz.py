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
        "header_subtitle_drag": "Drag each term from the list onto its location on the map.",
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
        "toggle_features": "Mountains + rivers",
        "toggle_borders": "Borders",
        "toggle_bw": "B&W",
        "toggle_drag": "Drag mode",
        "msg_correct": "Correct!",
        "msg_wrong": "Wrong — try again",
        "msg_win": "Done! All correct ({total}/{total}) · total mistakes: {miss}",
        "resume_indicator": "Resumed previous session — your progress is restored.",
        "zoom_hint": "Zoom: + / − / wheel / dblclick · Drag to pan",
        "pdf_title_quiz": "Quiz",
        "pdf_title_answer": "Answer key",
        "pdf_legend_heading": "Terms:",
        "pdf_legend_symbols": "▲ mountains    — rivers    ○ location",
        "panel_close": "Zatvori",
        "panel_placeholder": "Opis uskoro.",
        "panel_source_label": "Izvor:",
        "panel_hint_heading": "Hint",
        "panel_hint_prompt": "Hint se otkriva sa svakom greškom — pokušaj da postaviš pojam.",
        "panel_hints_done": "Svi hintovi iskorišćeni — evo opisa:",
        "panel_no_hint": "Nema hinta za ovaj pojam (još).",
        "mode_switch_label": "Mod",
        "mode_learn": "Učenje",
        "mode_test": "Test",
        "stat_bonus": "Bonus",
        "btn_proveri": "Proveri",
        "q_correct": "Tačno!",
        "q_wrong": "Pogrešno — pokušaj ponovo",
        "bonus_label": "Bonus",
        "bonus_locked": "Reši sva 3 pitanja da otključaš bonus.",
        "test_no_questions": "Nema test-pitanja za ovaj pojam.",
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
 :root{--sea:__SEA__;--land:__LAND__;--bord:__BORD__;--edge:__EDGE__;--mtn-col:__MTN_COL__;--riv-col:__RIV_COL__;--ink:#2b2b2b;}
 *{box-sizing:border-box}
 body{margin:0;font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif;color:var(--ink);background:#faf8f2}
 header{padding:14px 18px;background:#fff;border-bottom:1px solid #e6e0d2;position:sticky;top:0;z-index:50}
 h1{margin:0 0 4px;font-size:19px;color:#3a3528}
 .sub{font-size:13px;color:#6b6456;margin:0;max-width:900px}
 body:not(.drag-mode) .sub-drag{display:none}
 body.drag-mode .sub-number{display:none}
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
 /* Info side panel (third column) — opens when a term is solved or its marker clicked */
 .panelcol{flex:0 0 340px;width:340px;padding:14px 16px;border-left:1px solid #e6e0d2;background:#fff;position:sticky;top:var(--htop,0px);max-height:calc(100vh - var(--htop,0px));overflow:auto}
 .layout:not(.panel-open) .panelcol{display:none}
 .panelhead{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:8px;border-bottom:1px solid #eee;padding-bottom:8px}
 .panelhead h2{margin:0;font-size:16px;color:#3a3528}
 .panelhead .vrsta{display:inline-block;margin-top:4px;font-size:11.5px;color:#6b6456;background:#f3ecd8;border:1px solid #e1d8c2;border-radius:10px;padding:1px 8px;text-transform:capitalize}
 .panel-x{border:none;background:transparent;color:#6b6456;font-size:22px;line-height:1;padding:0 4px;cursor:pointer}
 .panel-x:hover{background:transparent;color:#b1271f}
 .panelbody{font-size:13px;line-height:1.55;color:#2b2b2b}
 .panelbody h4{font-size:12.5px;color:#3a3528;margin:12px 0 4px}
 .panelbody p{margin:0 0 8px} .panelbody ul{margin:0 0 8px;padding-left:18px} .panelbody li{margin:2px 0}
 .panelbody ol.hints{margin:4px 0 8px;padding-left:20px} .panelbody ol.hints li{margin:6px 0;line-height:1.5}
 .panelbody .placeholder{color:#9b9387;font-style:italic}
 .panelfoot{margin-top:12px;border-top:1px solid #eee;padding-top:8px;font-size:11px;color:#6b6456}
 .panelfoot a{color:#6b6456}
 .cell:has(.ans.correct){cursor:pointer}
 /* Demo term (Srbija): gray legend item + small-caps badge; click runs the demo */
 ol.terms li.demo-item{color:#777;font-style:italic}
 ol.terms li.demo-item b{color:#9a9a9a}
 .demo-badge{font-variant:small-caps;font-style:normal;font-size:10px;letter-spacing:.05em;color:#fff;background:#9a9a9a;border-radius:6px;padding:0 6px;margin-left:5px}
 body.drag-mode ol.terms li.demo-item{cursor:pointer;background:#f0f0f0;border:1px dashed #c9c9c9}
 body.drag-mode ol.terms li.demo-item:hover{background:#e8e8e8}
 .cell[data-demo] .ans{border-color:#9a9a9a;color:#777}
 .cell[data-demo] .ans.correct{background:#e4e4e4;border-color:#777;color:#555}
 body.demo-running ol.terms{pointer-events:none}
 /* Demo overlay: animated pointer + speech bubble */
 #demoCursor{position:fixed;z-index:300;pointer-events:none;font-size:26px;line-height:1;transition:left .8s cubic-bezier(.4,0,.2,1),top .8s cubic-bezier(.4,0,.2,1);filter:drop-shadow(0 1px 2px rgba(0,0,0,.45))}
 #demoBubble{position:fixed;z-index:301;max-width:280px;background:#2b2b2b;color:#fff;font-size:13px;line-height:1.45;padding:10px 13px;border-radius:10px;box-shadow:0 4px 16px rgba(0,0,0,.35);transition:left .6s,top .6s}
 #demoBubble .demo-step{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#ffd27a;margin-bottom:3px}
 #demoBubble .demo-ctrls{margin-top:9px;display:flex;gap:8px;justify-content:flex-end}
 #demoBubble button{font:inherit;font-size:12px;padding:4px 12px;border-radius:7px;cursor:pointer;border:1px solid #fff;background:#fff;color:#2b2b2b}
 #demoBubble button.demo-skip{background:transparent;color:#ccc;border-color:#666}
 /* Mode switch (Učenje / Test) */
 .mode-switch{display:inline-flex;align-items:center;gap:6px;font-size:13px;color:#3a3528}
 .ms-btn{font:inherit;padding:5px 12px;border:1px solid #6b6456;background:#fff;color:#3a3528;cursor:pointer;min-width:6em;text-align:center}
 .ms-btn:first-of-type{border-radius:8px 0 0 8px} .ms-btn:last-of-type{border-radius:0 8px 8px 0;border-left:none}
 .ms-btn:hover{background:#f3ecd8;color:#3a3528}
 .ms-btn.active{background:#3a3528;color:#fff;border-color:#3a3528}
 /* Učenje mod: bez statistike (tačno / greške / pobeda / izvoz) — ovde se uči, ne boduje */
 body:not(.test-mode) #statCorrect, body:not(.test-mode) #statMiss,
 body:not(.test-mode) #win, body:not(.test-mode) #exportCsv { display: none !important; }
 /* Test-mode quiz inside the panel */
 .quiz .q,.quiz .bonus{border:1px solid #e1d8c2;border-radius:8px;padding:9px 11px;margin:0 0 10px;background:#fcfaf4}
 .quiz .q-head{margin-bottom:7px}
 .quiz .q-tezina{display:inline-block;font-size:10.5px;text-transform:uppercase;letter-spacing:.04em;color:#6b6456;background:#f3ecd8;border:1px solid #e1d8c2;border-radius:9px;padding:1px 7px;margin-right:6px}
 .quiz .q-txt{font-weight:600;font-size:13px}
 .quiz .opt{display:flex;gap:7px;align-items:flex-start;font-size:12.5px;line-height:1.4;padding:3px 0;cursor:pointer}
 .quiz .opt input{margin-top:2px}
 .quiz .q-proveri{margin-top:7px;padding:4px 12px;font-size:12.5px}
 .quiz .q-status{margin-left:8px;font-size:12px;font-weight:600}
 .quiz .q-status.ok{color:#1f7a3a} .quiz .q-status.bad{color:#b1271f}
 .quiz .q.solved{background:#eef7f0;border-color:#bfe0c8}
 .quiz .q.solved .opt input{pointer-events:none}
 .quiz .opt.reveal-correct{color:#1f7a3a;font-weight:600}
 .quiz .bonus{background:#fff7e6;border-color:#f0d878}
 .quiz .bonus.locked .opt input,.quiz .bonus.locked .q-proveri{pointer-events:none;opacity:.5}
 .quiz .bonus .q-tezina{background:#fce9b8;border-color:#f0d878;color:#7a5a00}
 .quiz .bonus-lock-msg{font-size:11.5px;color:#7a5a00;margin-top:6px}
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

 /* Geometry (mountains/rivers) hidden by default; each term's geometry is
    revealed (drawn) only when that term is correctly placed. Borders never show. */
 svg .feat-mtn, svg .feat-mtn-mark, svg .feat-riv { display: none }
 svg .feat-mtn.revealed, svg .feat-mtn-mark.revealed, svg .feat-riv.revealed { display: inline }
 svg .border-path { display: none }

 /* Drag mode: pre-placed cells are hidden until dropped. Legend items
    become draggable; placed-but-wrong cells become re-draggable. */
 body.drag-mode .cell:not(.drag-placed) { display: none }
 body.drag-mode .cell { pointer-events: auto; cursor: grab }
 body.drag-mode .cell .ans { pointer-events: none }
 body.drag-mode .cell.dragging { opacity: 0.35; cursor: grabbing }
 body.drag-mode ol.terms li { cursor: grab; padding: 2px 6px; border-radius: 4px; user-select: none; -webkit-user-select: none }
 body.drag-mode ol.terms li:hover { background: #f3ecd8 }
 body.drag-mode ol.terms li.dragging { opacity: 0.35 }
 body.drag-mode ol.terms li.placed { text-decoration: line-through; color: #9b9387; cursor: default; background: transparent }
 body.drag-mode ol.terms li.placed:hover { background: transparent }
 body.drag-mode #stageWrap { cursor: crosshair }
 body.drag-mode #stageWrap.grabbing { cursor: grabbing }
 .ans.wrong-placed { background: #fdd; border-color: #b1271f; color: #b1271f }
 .drag-ghost {
   position: fixed; z-index: 200; pointer-events: none;
   width: 32px; height: 32px; border: 2px solid var(--edge);
   border-radius: 6px; background: #fff; color: var(--edge);
   font-size: 13px; font-weight: 700; line-height: 28px; text-align: center;
   transform: translate(-50%, -50%); box-shadow: 0 2px 8px rgba(0,0,0,.3);
   opacity: 0.9;
 }

 /* Black & white mode: grayscale palette + subtle gradient on sea */
 body.bw {
   --sea: #d4d4d4; --land: #f2f2f2; --bord: #5a5a5a; --edge: #1a1a1a;
   --mtn-col: #404040; --riv-col: #707070;
 }
 body.bw svg {
   background: linear-gradient(180deg, #b8b8b8 0%, #dcdcdc 60%, #e8e8e8 100%) !important;
 }
 body.bw .ans { box-shadow: 0 1px 2px rgba(0,0,0,.25) }
 body.bw .ans.correct { background: #e8e8e8; border-color: #000; color: #000 }
 body.bw .ans.wrong { background: #d8d8d8 }
 body.bw .stat.win { background: #e0e0e0; color: #000; border-color: #000 }
 body.bw #msg { background: #1a1a1a !important }

 @media (max-width:760px){
   .layout{flex-direction:column}
   .qcol{flex:none;width:auto;position:static;max-height:none;border-right:none;border-bottom:1px solid #e6e0d2}
   .qcol ol.terms{columns:2;column-gap:22px}
   .panelcol{flex:none;width:auto;position:static;max-height:none;border-left:none;border-top:1px solid #e6e0d2}
   h1{font-size:17px}
   .ans{width:32px;height:32px;font-size:14px}
 }
 @media print {
   header .bar, .zoombar, .zhint, #msg, .resume-banner, button, .panelcol { display: none !important; }
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
 <p class="sub sub-number">__HDR_SUB__</p>
 <p class="sub sub-drag">__HDR_SUB_DRAG__</p>
 <div class="bar">
  <span class="mode-switch">__MODE_SWITCH_LABEL__:
   <button type="button" id="modeLearn" class="ms-btn active">__MODE_LEARN__</button><button type="button" id="modeTest" class="ms-btn">__MODE_TEST__</button>
  </span>
  <span class="stat" id="statCorrect">__LBL_CORRECT__: <b class="ok" id="cCorrect">0</b> / <b id="cTotal">__TOTAL__</b></span>
  <span class="stat" id="statMiss">__LBL_MISS__: <b class="bad" id="cMiss">0</b></span>
  <span class="stat bonus-stat" id="bonusStat" style="display:none">__LBL_BONUS__: <b class="ok" id="cBonus">0</b> / <b id="cBonusTotal">0</b></span>
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
     <path class="border-path" d="__STROKE__" fill="none" stroke="var(--bord)" stroke-width="0.6"/>
     __RIV__
     __MTN__
     __MARKS__
    </svg>
   </div>
   <div id="overlay">__BOXES__</div>
  </div>
 </main>
 <aside class="panelcol" id="panelcol" aria-hidden="true">
  <div class="panelhead">
   <div><h2 id="panelTitle"></h2><span class="vrsta" id="panelVrsta" style="display:none"></span></div>
   <button class="panel-x" id="panelClose" title="__PANEL_CLOSE__" aria-label="__PANEL_CLOSE__">&times;</button>
  </div>
  <div class="panelbody" id="panelBody"></div>
  <div class="panelfoot" id="panelFoot" style="display:none"></div>
 </aside>
</div>
<div id="msg"></div>
<script>
const ALL_TERMS = __TERMS_JSON__;
const STATE_KEY = 'classroom:' + window.location.pathname;
const STATE_VERSION = 4;
const RANDOMIZE_NUMBERS = __RANDOMIZE_NUMBERS__;
// Projection constants for screen-pixel ↔ lon/lat conversion (drag mode only)
const PROJ_LON0 = __PROJ_LON0__, PROJ_LAT1 = __PROJ_LAT1__;
const PROJ_SX = __PROJ_SX__, PROJ_SY = __PROJ_SY__;
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
const layoutEl = document.querySelector('.layout');
const panelTitle = document.getElementById('panelTitle');
const panelVrsta = document.getElementById('panelVrsta');
const panelBody = document.getElementById('panelBody');
const panelFoot = document.getElementById('panelFoot');
const panelClose = document.getElementById('panelClose');

// Demo terms (Srbija) are excluded from scoring, visibility and numbering.
const QUIZ_TERMS = ALL_TERMS.filter(t => !t.demo);
const DEMO_TERM = ALL_TERMS.find(t => t.demo) || null;

let currentMode = 'all';
let visibleIds = QUIZ_TERMS.map(t => t.id);
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
    if (DEMO_TERM && canonId === DEMO_TERM.id) continue;  // demo marker stays "0"
    const display = mapping.c2d[canonId];
    inp.dataset.correct = display ? String(display) : '';
  }
  // Reorder legend by display number and rewrite the <b>N.</b> prefix
  const items = [...legendList.children];
  items.sort((a, b) => {
    const da = a.dataset.demo ? -1 : (mapping.c2d[parseInt(a.dataset.id, 10)] || 9999);
    const db = b.dataset.demo ? -1 : (mapping.c2d[parseInt(b.dataset.id, 10)] || 9999);
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
  modeSelect.options[0].textContent = MODE_ALL_TPL.replace('{n}', QUIZ_TERMS.length);
  for (let i = 1; i < modeSelect.options.length; i++) {
    const n = parseInt(modeSelect.options[i].value, 10);
    if (n >= QUIZ_TERMS.length) {
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
    if (li.dataset.demo) continue;       // demo item visibility handled separately
    li.classList.toggle('hidden', !set.has(id));
  }
  cTotal.textContent = ids.length;
}

// During the demo, the demo term (Srbija) is counted too, so the counters
// visibly react to its placements/answers; otherwise it is excluded.
function countedIds() {
  if (DEMO_TERM && document.body.classList.contains('demo-running')) {
    return visibleIds.concat([DEMO_TERM.id]);
  }
  return visibleIds;
}

function recountCorrectMiss() {
  const ids = countedIds();   // includes the demo term during the demo (→ 43), else 42
  let correct = 0, miss = 0;
  for (const id of ids) {
    const inp = inputsById.get(id);
    if (!inp) continue;
    if (inp.classList.contains('correct')) correct++;
    miss += parseInt(inp.dataset.miss, 10) || 0;
  }
  cCorrect.textContent = correct;
  cTotal.textContent = ids.length;
  cMiss.textContent = miss;
  if (correct === ids.length && ids.length > 0) {
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

// --- info side panel (full description when solved; progressive hints while wrong) ---
const PANEL_PLACEHOLDER = __PANEL_PLACEHOLDER__;
const PANEL_SOURCE_LBL = __PANEL_SOURCE_LBL__;
const PANEL_HINT_HEADING = __PANEL_HINT_HEADING__;
const PANEL_HINT_PROMPT = __PANEL_HINT_PROMPT__;
const PANEL_HINTS_DONE = __PANEL_HINTS_DONE__;
const PANEL_NO_HINT = __PANEL_NO_HINT__;

function panelSetVrsta(d) {
  if (d && d.vrsta) {
    panelVrsta.textContent = d.vrsta.replace(/_/g, ' ');
    panelVrsta.style.display = 'inline-block';
  } else {
    panelVrsta.style.display = 'none';
  }
}
function panelSetFoot(d) {
  if (d && d.sources && d.sources.length) {
    panelFoot.innerHTML = PANEL_SOURCE_LBL + ' ' + d.sources.map(s =>
      s.url ? '<a href="' + s.url + '" target="_blank" rel="noopener">' + s.naziv + '</a>' : s.naziv
    ).join(', ');
    panelFoot.style.display = 'block';
  } else {
    panelFoot.style.display = 'none';
  }
}
function panelOpenEl() {
  const was = layoutEl.classList.contains('panel-open');
  layoutEl.classList.add('panel-open');
  document.getElementById('panelcol').setAttribute('aria-hidden', 'false');
  if (!was) fit();   // re-fit the map to the narrower column so it stays fully visible
}

// Render the panel according to the term's current state:
//   solved            → full description (Sažetak + činjenice + vrsta + izvor)
//   unsolved + hints  → first `miss` hints (subtle → concrete); once hints run
//                       out, the next miss reveals the full description
//   unsolved + none   → quiet "no hint" placeholder
function showPanelFor(canonId) {
  const term = ALL_TERMS.find(t => t.id === canonId);
  if (!term) return;
  if (isTestMode()) { showTestPanel(canonId, term); return; }
  const d = term.desc;
  const inp = inputsById.get(canonId);
  const solved = inp && inp.classList.contains('correct');
  const miss = inp ? (parseInt(inp.dataset.miss, 10) || 0) : 0;
  const hints = (d && d.hints) ? d.hints : [];
  panelTitle.textContent = term.name;

  if (solved) {
    panelSetVrsta(d);
    panelBody.innerHTML = (d && d.html) ? d.html : '<p class="placeholder">' + PANEL_PLACEHOLDER + '</p>';
    panelSetFoot(d);
    panelOpenEl();
    return;
  }
  if (hints.length) {
    if (miss === 0) {
      panelVrsta.style.display = 'none';
      panelBody.innerHTML = '<p class="placeholder">' + PANEL_HINT_PROMPT + '</p>';
      panelFoot.style.display = 'none';
    } else if (miss > hints.length) {
      panelSetVrsta(d);
      panelBody.innerHTML = '<p class="placeholder">' + PANEL_HINTS_DONE + '</p>' + ((d && d.html) ? d.html : '');
      panelSetFoot(d);
    } else {
      panelVrsta.style.display = 'none';
      const shown = hints.slice(0, miss);
      panelBody.innerHTML = '<h4>' + PANEL_HINT_HEADING + '</h4><ol class="hints">' +
        shown.map(h => '<li>' + h + '</li>').join('') + '</ol>';
      panelFoot.style.display = 'none';
    }
    panelOpenEl();
    return;
  }
  panelVrsta.style.display = 'none';
  panelBody.innerHTML = '<p class="placeholder">' + PANEL_NO_HINT + '</p>';
  panelFoot.style.display = 'none';
  panelOpenEl();
}

// Auto-open the panel on a wrong attempt only when the term actually has hints
// (terms without hints stay quiet — only shake + miss badge).
function maybeHintPanel(canonId) {
  if (isTestMode()) return;  // no hints in test mode (wrong location still counts)
  const t = ALL_TERMS.find(t => t.id === canonId);
  if (t && t.desc && t.desc.hints && t.desc.hints.length) showPanelFor(canonId);
}

function closePanel() {
  const was = layoutEl.classList.contains('panel-open');
  layoutEl.classList.remove('panel-open');
  document.getElementById('panelcol').setAttribute('aria-hidden', 'true');
  if (was) fit();    // panel closed → restore the map to full width
}

panelClose.addEventListener('click', closePanel);

// Click any marker on the map to open its panel (full text if solved, else hints).
document.getElementById('overlay').addEventListener('click', e => {
  const cell = e.target.closest('.cell');
  if (!cell) return;
  const inp = cell.querySelector('.ans');
  if (inp) showPanelFor(parseInt(inp.dataset.id, 10));
});

// --- test mode (Učenje / Test) ---
const BTN_PROVERI = __BTN_PROVERI__;
const Q_CORRECT = __Q_CORRECT__, Q_WRONG = __Q_WRONG__;
const BONUS_LABEL = __BONUS_LABEL__, BONUS_LOCKED = __BONUS_LOCKED__;
const TEST_NO_Q = __TEST_NO_Q__;
const modeLearn = document.getElementById('modeLearn');
const modeTest = document.getElementById('modeTest');
const bonusStat = document.getElementById('bonusStat');
const cBonus = document.getElementById('cBonus');
const cBonusTotal = document.getElementById('cBonusTotal');

function isTestMode() { return document.body.classList.contains('test-mode'); }
function esc(s) { return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

// Per-term quiz progress: canonId → { solved: bool[], bonus: bool }
const quizProgress = new Map();
function getQP(canonId) {
  let p = quizProgress.get(canonId);
  if (!p) {
    const t = ALL_TERMS.find(x => x.id === canonId);
    const n = (t && t.quiz && t.quiz.questions) ? t.quiz.questions.length : 0;
    p = { solved: new Array(n).fill(false), bonus: false };
    quizProgress.set(canonId, p);
  }
  return p;
}

function optionsMatch(selectedSet, options) {
  for (let i = 0; i < options.length; i++) {
    if (!!options[i].c !== selectedSet.has(i)) return false;
  }
  return true;
}

function optsHTML(options, solved) {
  return options.map((o, oi) => {
    const checked = (solved && o.c) ? ' checked' : '';
    const cls = (solved && o.c) ? ' reveal-correct' : '';
    const dis = solved ? ' disabled' : '';
    return '<label class="opt' + cls + '"><input type="checkbox" data-oi="' + oi + '"' +
      checked + dis + '> ' + esc(o.t) + '</label>';
  }).join('');
}

function questionHTML(q, qi, solved) {
  return '<div class="q' + (solved ? ' solved' : '') + '" data-qi="' + qi + '">' +
    '<div class="q-head"><span class="q-tezina">' + esc(q.tezina || '') + '</span> ' +
    '<span class="q-txt">' + esc(q.pitanje) + '</span></div>' +
    optsHTML(q.options, solved) +
    '<div><button type="button" class="q-proveri"' + (solved ? ' style="display:none"' : '') + '>' +
    BTN_PROVERI + '</button>' +
    '<span class="q-status ' + (solved ? 'ok' : '') + '">' + (solved ? Q_CORRECT : '') + '</span></div></div>';
}

function bonusHTML(bonus, unlocked, solved) {
  let h = '<div class="bonus' + (unlocked ? '' : ' locked') + '" data-bonus>' +
    '<div class="q-head"><span class="q-tezina">' + BONUS_LABEL + '</span> ' +
    '<span class="q-txt">' + esc(bonus.pitanje) + '</span></div>' +
    optsHTML(bonus.options, solved) +
    '<div><button type="button" class="q-proveri" data-bonus-btn' + (solved ? ' style="display:none"' : '') + '>' +
    BTN_PROVERI + '</button>' +
    '<span class="q-status ' + (solved ? 'ok' : '') + '">' + (solved ? Q_CORRECT : '') + '</span></div>';
  if (!unlocked) h += '<div class="bonus-lock-msg">' + BONUS_LOCKED + '</div>';
  return h + '</div>';
}

function renderQuiz(canonId, quiz) {
  const p = getQP(canonId);
  const allSolved = p.solved.length > 0 && p.solved.every(Boolean);
  let h = '<div class="quiz" data-canon="' + canonId + '">';
  quiz.questions.forEach((q, qi) => { h += questionHTML(q, qi, p.solved[qi]); });
  if (quiz.bonus) h += bonusHTML(quiz.bonus, allSolved, p.bonus);
  return h + '</div>';
}

// Test-mode panel: questions appear only after the term is correctly located.
function showTestPanel(canonId, term) {
  panelTitle.textContent = term.name;
  panelVrsta.style.display = 'none';
  panelFoot.style.display = 'none';
  const inp = inputsById.get(canonId);
  const solved = inp && inp.classList.contains('correct');
  if (!solved) return;  // don't reveal questions before correct placement
  if (!term.quiz || !term.quiz.questions || !term.quiz.questions.length) {
    panelBody.innerHTML = '<p class="placeholder">' + TEST_NO_Q + '</p>';
    panelOpenEl();
    return;
  }
  panelBody.innerHTML = renderQuiz(canonId, term.quiz);
  panelOpenEl();
}

function markBlockSolved(block, options) {
  block.classList.add('solved');
  const inputs = [...block.querySelectorAll('input[type=checkbox]')];
  inputs.forEach((c, i) => {
    c.checked = !!options[i].c;
    c.disabled = true;
    const lbl = c.closest('.opt');
    if (lbl && options[i].c) lbl.classList.add('reveal-correct');
  });
  const pv = block.querySelector('.q-proveri');
  if (pv) pv.style.display = 'none';
  const st = block.querySelector('.q-status');
  st.className = 'q-status ok';
  st.textContent = Q_CORRECT;
}

function maybeUnlockBonus(canonId) {
  const p = getQP(canonId);
  if (p.solved.length > 0 && p.solved.every(Boolean)) {
    const b = panelBody.querySelector('.bonus');
    if (b) {
      b.classList.remove('locked');
      const m = b.querySelector('.bonus-lock-msg');
      if (m) m.remove();
    }
  }
}

function recountBonus() {
  if (!isTestMode()) { bonusStat.style.display = 'none'; return; }
  let solved = 0, total = 0;
  for (const id of countedIds()) {
    const t = ALL_TERMS.find(x => x.id === id);
    if (t && t.quiz && t.quiz.bonus) {
      total++;
      const p = quizProgress.get(id);
      if (p && p.bonus) solved++;
    }
  }
  cBonus.textContent = solved;
  cBonusTotal.textContent = total;
  bonusStat.style.display = total > 0 ? 'inline-block' : 'none';
}

// Per-question "Proveri" — exact-set match required; any deviation = +1 mistake.
panelBody.addEventListener('click', e => {
  const btn = e.target.closest('.q-proveri');
  if (!btn) return;
  const quizEl = panelBody.querySelector('.quiz');
  if (!quizEl) return;
  const canonId = parseInt(quizEl.dataset.canon, 10);
  const term = ALL_TERMS.find(t => t.id === canonId);
  if (!term || !term.quiz) return;
  const isBonus = btn.hasAttribute('data-bonus-btn');
  const block = btn.closest(isBonus ? '.bonus' : '.q');
  if (block.classList.contains('locked')) return;
  const options = isBonus
    ? term.quiz.bonus.options
    : term.quiz.questions[parseInt(block.dataset.qi, 10)].options;
  const selected = new Set([...block.querySelectorAll('input[type=checkbox]')]
    .filter(c => c.checked).map(c => parseInt(c.dataset.oi, 10)));
  const status = block.querySelector('.q-status');
  if (optionsMatch(selected, options)) {
    const p = getQP(canonId);
    if (isBonus) { p.bonus = true; markBlockSolved(block, options); }
    else { p.solved[parseInt(block.dataset.qi, 10)] = true; markBlockSolved(block, options); maybeUnlockBonus(canonId); }
    recountBonus();
    saveState();
  } else {
    status.className = 'q-status bad';
    status.textContent = Q_WRONG;
    if (!isBonus) {
      // wrong answer counts as a mistake on the term (same counter as bad location)
      const inp = inputsById.get(canonId);
      const m = (parseInt(inp.dataset.miss, 10) || 0) + 1;
      inp.dataset.miss = m;
      const badge = inp.parentElement.querySelector('.miss');
      badge.textContent = m;
      badge.style.display = 'block';
      recountCorrectMiss();
    }
    saveState();
  }
});

function setTestMode(on, opts) {
  opts = opts || {};
  document.body.classList.toggle('test-mode', on);
  modeTest.classList.toggle('active', on);
  modeLearn.classList.toggle('active', !on);
  closePanel();
  if (!opts.restore) {
    // Switching modes resets the board (different scoring model).
    quizProgress.clear();
    if (currentMode !== 'all') setMode(currentMode, { restoreIds: shuffleIds(parseInt(currentMode, 10)) });
    else setMode('all', {});
    resumeBanner.classList.remove('show');
  }
  recountBonus();
  saveState();
}
modeLearn.addEventListener('click', () => { if (isTestMode()) setTestMode(false, {}); });
modeTest.addEventListener('click', () => { if (!isTestMode()) setTestMode(true, {}); });

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
    revealGeometry(parseInt(inp.dataset.id, 10));
    showPanelFor(parseInt(inp.dataset.id, 10));
    recountCorrectMiss();
  } else {
    const m = (parseInt(inp.dataset.miss, 10) || 0) + 1;
    inp.dataset.miss = m;
    const badge = inp.parentElement.querySelector('.miss');
    badge.textContent = m;
    badge.style.display = 'block';
    inp.classList.add('wrong');
    showMsg(MSG_WRONG, false);
    maybeHintPanel(parseInt(inp.dataset.id, 10));
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
    const cell = inp.parentElement;
    const a = {
      v: inp.value,
      c: inp.classList.contains('correct'),
      m: parseInt(inp.dataset.miss, 10) || 0
    };
    // Drag placement (only relevant in drag mode for placed cells)
    if (cell.classList.contains('drag-placed')) {
      a.dp = true;
      a.px = parseFloat(cell.dataset.sx);
      a.py = parseFloat(cell.dataset.sy);
    }
    const qp = quizProgress.get(parseInt(inp.dataset.id, 10));
    if (qp && (qp.bonus || qp.solved.some(Boolean))) {
      a.qz = qp.solved.slice();
      a.bn = qp.bonus;
    }
    answers[inp.dataset.id] = a;
  }
  const state = {
    v: STATE_VERSION,
    mode: currentMode,
    testMode: isTestMode(),
    demoDone: demoDone,
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
  quizProgress.clear();
  hideAllGeometry();
  for (const inp of allInputs) {
    const a = answers[inp.dataset.id];  // keyed by canonical id
    const cell = inp.parentElement;
    inp.value = '';
    inp.readOnly = false;
    inp.classList.remove('correct', 'wrong', 'wrong-placed');
    inp.dataset.miss = '0';
    const badge = cell.querySelector('.miss');
    badge.style.display = 'none';
    badge.textContent = '0';
    // Reset drag-placed state and snap back to canonical position
    cell.classList.remove('drag-placed', 'dragging');
    cell.dataset.sx = cell.dataset.canonSx;
    cell.dataset.sy = cell.dataset.canonSy;
    if (!a) continue;
    if (a.v) inp.value = a.v;
    if (a.c) {
      inp.classList.add('correct');
      inp.readOnly = true;
      revealGeometry(parseInt(inp.dataset.id, 10));
    }
    if (a.m && a.m > 0) {
      inp.dataset.miss = String(a.m);
      badge.textContent = a.m;
      badge.style.display = 'block';
    }
    // Restore drag placement if present in saved state
    if (a.dp) {
      cell.classList.add('drag-placed');
      cell.dataset.sx = String(a.px);
      cell.dataset.sy = String(a.py);
      if (!a.c) inp.classList.add('wrong-placed');
    }
    // Restore test-mode quiz progress
    if (a.qz) {
      const qp = getQP(parseInt(inp.dataset.id, 10));
      qp.solved = a.qz.slice();
      qp.bonus = !!a.bn;
    }
  }
  // Restore legend "placed" strikethrough for correctly drag-placed items
  for (const [id, li] of legendItems) {
    const a = answers[id];
    li.classList.toggle('placed', !!(a && a.dp && a.c));
  }
}

// --- mode (N-random) ---
function shuffleIds(n) {
  const all = QUIZ_TERMS.map(t => t.id);
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
    ids = QUIZ_TERMS.map(t => t.id);
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
  recountBonus();
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

// --- fixed view: no features/borders, color, always drag mode ---
// Mountains/rivers are hidden until a term is correctly placed, then its own
// geometry is drawn on the map.
document.body.classList.add('drag-mode');

function revealGeometry(canonId) {
  for (const el of document.querySelectorAll('svg [data-term="' + canonId + '"]')) {
    el.classList.add('revealed');
  }
}
function hideAllGeometry() {
  for (const el of document.querySelectorAll('svg .revealed')) {
    el.classList.remove('revealed');
  }
}

// --- drag system (active only when body.drag-mode) ---
// Default fallback (used only if a term has no `accept` field): ~3° around label_at,
// which corresponds to roughly 40px at the default unzoomed scale.
const DEFAULT_ACCEPT_RADIUS_DEG = 3.0;
let dragGhost = null;
let dragSourceCanonId = null;

// --- geometry helpers ---
function pointInPolygon(lon, lat, polygon) {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i][0], yi = polygon[i][1];
    const xj = polygon[j][0], yj = polygon[j][1];
    const intersect = ((yi > lat) !== (yj > lat)) &&
                      (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}
function distanceToSegment(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1, dy = y2 - y1;
  if (dx === 0 && dy === 0) return Math.hypot(px - x1, py - y1);
  const t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)));
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}
function distanceToPolyline(lon, lat, polyline) {
  let minDist = Infinity;
  for (let i = 0; i < polyline.length - 1; i++) {
    const d = distanceToSegment(lon, lat,
      polyline[i][0], polyline[i][1], polyline[i+1][0], polyline[i+1][1]);
    if (d < minDist) minDist = d;
  }
  return minDist;
}
function screenToLonLat(clientX, clientY) {
  const r = wrap.getBoundingClientRect();
  const sc = baseFit * zoom;
  const baseX = (clientX - r.left - panX) / sc;
  const baseY = (clientY - r.top - panY) / sc;
  // Inverse of px(lon,lat) = ((lon - LON0) * SX, (LAT1 - lat) * SY)
  return [baseX / PROJ_SX + PROJ_LON0, PROJ_LAT1 - baseY / PROJ_SY];
}

// Per-term acceptance check: returns true if the drop point (lon, lat) is
// inside the term's accept area. Any single criterion passing = accepted.
function isDropAcceptable(term, lon, lat) {
  if (!term) return false;
  const acc = term.accept;
  if (acc) {
    if (acc.polygon && pointInPolygon(lon, lat, acc.polygon)) return true;
    if (acc.bbox) {
      const [lon0, lat0, lon1, lat1] = acc.bbox;
      if (lon >= lon0 && lon <= lon1 && lat >= lat0 && lat <= lat1) return true;
    }
    if (acc.radius_deg != null && term.label_at) {
      const dx = lon - term.label_at[0], dy = lat - term.label_at[1];
      if (Math.hypot(dx, dy) <= acc.radius_deg) return true;
    }
    if (acc.buffer_deg != null && term.geometry && term.geometry.polyline) {
      if (distanceToPolyline(lon, lat, term.geometry.polyline) <= acc.buffer_deg) return true;
    }
    return false;  // accept defined but none passed
  }
  // No accept field — fall back to default radius around label_at
  if (term.label_at) {
    const dx = lon - term.label_at[0], dy = lat - term.label_at[1];
    return Math.hypot(dx, dy) <= DEFAULT_ACCEPT_RADIUS_DEG;
  }
  return false;
}

function startDrag(clientX, clientY, displayLabel, sourceElement) {
  if (!document.body.classList.contains('drag-mode')) return;
  closePanel();   // taking the next term hides the info panel so the whole map shows
  dragGhost = document.createElement('div');
  dragGhost.className = 'drag-ghost';
  dragGhost.textContent = displayLabel;
  dragGhost.style.left = clientX + 'px';
  dragGhost.style.top = clientY + 'px';
  document.body.appendChild(dragGhost);
  sourceElement.classList.add('dragging');
}

function endDragCleanup() {
  if (dragGhost) {
    dragGhost.remove();
    dragGhost = null;
  }
  for (const el of document.querySelectorAll('.dragging')) el.classList.remove('dragging');
  dragSourceCanonId = null;
}

function tryDragDrop(canonicalId, clientX, clientY) {
  const cell = inputsById.get(canonicalId).parentElement;
  const inp = cell.querySelector('.ans');
  if (inp.classList.contains('correct')) return;
  const r = wrap.getBoundingClientRect();
  if (clientX < r.left || clientX > r.right || clientY < r.top || clientY > r.bottom) {
    return;  // dropped outside map — abort
  }
  const sc = baseFit * zoom;
  const baseX = (clientX - r.left - panX) / sc;
  const baseY = (clientY - r.top - panY) / sc;
  const [lon, lat] = screenToLonLat(clientX, clientY);
  const term = ALL_TERMS.find(t => t.id === canonicalId);
  const accepted = isDropAcceptable(term, lon, lat);
  applyDrop(canonicalId, accepted, baseX, baseY);
}

// Apply a placement result (used by real drops and by the demo). baseX/baseY are
// map-pixel coords where the marker should sit.
function applyDrop(canonicalId, accepted, baseX, baseY) {
  const cell = inputsById.get(canonicalId).parentElement;
  const inp = cell.querySelector('.ans');
  if (inp.classList.contains('correct')) return;
  cell.classList.add('drag-placed');
  cell.dataset.sx = String(baseX);
  cell.dataset.sy = String(baseY);
  inp.value = inp.dataset.correct;
  if (accepted) {
    inp.classList.remove('wrong-placed');
    inp.classList.add('correct');
    inp.readOnly = true;
    const li = legendItems.get(canonicalId);
    if (li) li.classList.add('placed');
    showMsg(MSG_CORRECT, true);
    revealGeometry(canonicalId);
    showPanelFor(canonicalId);
  } else {
    inp.classList.add('wrong-placed');
    const m = (parseInt(inp.dataset.miss, 10) || 0) + 1;
    inp.dataset.miss = m;
    const badge = cell.querySelector('.miss');
    badge.textContent = m;
    badge.style.display = 'block';
    showMsg(MSG_WRONG, false);
    maybeHintPanel(canonicalId);
  }
  apply();
  recountCorrectMiss();
  saveState();
}

// pointerdown on a legend item starts drag
legendList.addEventListener('pointerdown', e => {
  if (!document.body.classList.contains('drag-mode')) return;
  const li = e.target.closest('li');
  if (!li || li.classList.contains('placed')) return;
  if (li.dataset.demo) { e.preventDefault(); startDemo(); return; }  // Srbija → run demo
  e.preventDefault();
  const canonId = parseInt(li.dataset.id, 10);
  dragSourceCanonId = canonId;
  const display = currentMapping ? currentMapping.c2d[canonId] : canonId;
  startDrag(e.clientX, e.clientY, display, li);
});

// pointerdown on a placed-wrong cell starts re-drag
document.getElementById('overlay').addEventListener('pointerdown', e => {
  if (!document.body.classList.contains('drag-mode')) return;
  const cell = e.target.closest('.cell.drag-placed');
  if (!cell) return;
  const inp = cell.querySelector('.ans');
  if (inp.classList.contains('correct')) return;
  e.preventDefault();
  e.stopPropagation();
  const canonId = parseInt(inp.dataset.id, 10);
  dragSourceCanonId = canonId;
  const display = inp.dataset.correct || '?';
  startDrag(e.clientX, e.clientY, display, cell);
});

document.addEventListener('pointermove', e => {
  if (!dragGhost) return;
  dragGhost.style.left = e.clientX + 'px';
  dragGhost.style.top = e.clientY + 'px';
});

document.addEventListener('pointerup', e => {
  if (dragSourceCanonId !== null) {
    tryDragDrop(dragSourceCanonId, e.clientX, e.clientY);
  }
  endDragCleanup();
});

document.addEventListener('pointercancel', endDragCleanup);

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
  // In drag mode, drag-placed cells handle their own pointer events for re-drag
  if (document.body.classList.contains('drag-mode') && e.target.closest('.cell')) return;
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

// --- guided demo (Srbija) ---
let demoDone = false;
let demoCursorEl = null, demoBubbleEl = null, demoStepIndex = 0;

function hideDemoTerm() {
  if (!DEMO_TERM) return;
  const li = legendItems.get(DEMO_TERM.id);
  if (li) li.classList.add('hidden');
  const inp = inputsById.get(DEMO_TERM.id);
  if (inp) inp.parentElement.classList.add('hidden');
}

function baseToClient(bx, by) {
  const r = wrap.getBoundingClientRect();
  const sc = baseFit * zoom;
  return [r.left + panX + bx * sc, r.top + panY + by * sc];
}
function demoCursorToClient(cx, cy) {
  if (demoCursorEl) { demoCursorEl.style.left = cx + 'px'; demoCursorEl.style.top = cy + 'px'; }
}
function demoCursorToEl(el) {
  const r = el.getBoundingClientRect();
  demoCursorToClient(r.left + r.width / 2, r.top + r.height / 2);
}

// --- demo actions (operate on the Srbija term, id 0) ---
function demoDropWrongAt(bx, by) {
  // The Srbija marker (number 0) lands at this wrong map spot.
  const [cx, cy] = baseToClient(bx, by);
  demoCursorToClient(cx, cy);
  applyDrop(DEMO_TERM.id, false, bx, by);
}
function demoDropCorrect() {
  const cell = inputsById.get(DEMO_TERM.id).parentElement;
  const bx = parseFloat(cell.dataset.canonSx), by = parseFloat(cell.dataset.canonSy);
  const [cx, cy] = baseToClient(bx, by);
  demoCursorToClient(cx, cy);
  applyDrop(DEMO_TERM.id, true, bx, by);
}
function demoEnterTest() { setTestMode(true, {}); }
function demoEnsureQuiz() {
  // Make sure the test-mode quiz panel for Srbija is open before answering.
  if (!panelBody.querySelector('.quiz')) showPanelFor(DEMO_TERM.id);
}
function demoAnswerQuestion(qi, correct) {
  demoEnsureQuiz();
  const quizEl = panelBody.querySelector('.quiz');
  if (!quizEl) return;
  const block = quizEl.querySelector('.q[data-qi="' + qi + '"]');
  if (!block || block.classList.contains('solved')) {
    // if already solved (the correct pass), nothing to do
    if (correct) return;
  }
  if (!block) return;
  const opts = DEMO_TERM.quiz.questions[qi].options;
  const boxes = [...block.querySelectorAll('input[type=checkbox]')];
  boxes.forEach((c, i) => { c.checked = correct ? !!opts[i].c : !opts[i].c; });
  const pv = block.querySelector('.q-proveri');
  if (pv) pv.click();
}
function demoBonus() {
  demoEnsureQuiz();
  const block = panelBody.querySelector('.bonus');
  if (!block) return;
  const opts = DEMO_TERM.quiz.bonus.options;
  const boxes = [...block.querySelectorAll('input[type=checkbox]')];
  boxes.forEach((c, i) => { c.checked = !!opts[i].c; });
  const pv = block.querySelector('.q-proveri[data-bonus-btn]');
  if (pv) pv.click();
}

// --- demo step script ---
const DEMO_STEPS = [
  { l: 'Učenje', t: 'Prevlačim pojam <b>Srbija</b> na pogrešno mesto — broj <b>0</b> pada tu (crveno). Greška se broji i otvara prvi <b>hint</b>.', a: () => demoDropWrongAt(MW * 0.20, MH * 0.28), at: 'map' },
  { l: 'Hintovi', t: 'Spuštam <b>0</b> na drugo pogrešno mesto — otkriva se sledeći, konkretniji hint.', a: () => demoDropWrongAt(MW * 0.31, MH * 0.56), at: 'map' },
  { l: 'Tačno', t: 'Sad <b>0</b> ide na tačno mesto. Tada se prikaže <b>pun opis</b> pojma u panelu.', a: demoDropCorrect, at: 'map' },
  { l: 'Test mod', t: 'Prelazim u <b>Test</b> mod. Ovde nema hintova ni opisa — posle tačnog lociranja dobijaš pitanja.', a: demoEnterTest, at: 'mode' },
  { l: 'Test: greška 1', t: 'I u testu pogrešno lociranje broji grešku — <b>0</b> na prvo pogrešno mesto.', a: () => demoDropWrongAt(MW * 0.22, MH * 0.30), at: 'map' },
  { l: 'Test: greška 2', t: '...pa <b>0</b> na drugo pogrešno mesto.', a: () => demoDropWrongAt(MW * 0.33, MH * 0.58), at: 'map' },
  { l: 'Test: tačno', t: 'Pa <b>0</b> na tačno mesto — otvaraju se tri pitanja.', a: demoDropCorrect, at: 'map' },
  { l: 'Pitanje 1', t: 'Prvo pitanje rešavam tačno iz prve.', a: () => demoAnswerQuestion(0, true), at: 'panel' },
  { l: 'Pitanje 2', t: 'Drugo pitanje prvo namerno pogrešim — broji se jedna greška.', a: () => demoAnswerQuestion(1, false), at: 'panel' },
  { l: 'Pitanje 2', t: '...pa ga ispravim na tačno.', a: () => demoAnswerQuestion(1, true), at: 'panel' },
  { l: 'Pitanje 3', t: 'Treće pitanje opet prvo pogrešim...', a: () => demoAnswerQuestion(2, false), at: 'panel' },
  { l: 'Pitanje 3', t: '...pa ispravim na tačno. Sva tri rešena — otključava se <b>bonus</b>.', a: () => demoAnswerQuestion(2, true), at: 'panel' },
  { l: 'Bonus', t: 'Da bi tačno odgovorio na bonus, treba da klikneš na <b>sve izvore</b> iz kojih je nastao opis ovog pojma. Odgovaram tačno.', a: demoBonus, at: 'panel' },
  { l: 'Kraj', t: 'To je ceo tok kviza — učenje, pa test, pa bonus. Srbija sada nestaje sa spiska. Srećno!', a: null, at: 'mode' },
];

function demoPositionBubble(at) {
  // Pin the bubble to the bottom-left, over the legend column — so it never
  // covers the map markers or the side panel while the demo runs.
  demoBubbleEl.style.left = '14px';
  demoBubbleEl.style.right = 'auto';
  demoBubbleEl.style.top = 'auto';
  demoBubbleEl.style.bottom = '16px';
  // Move the pointer to the relevant control (map drops move it themselves).
  if (at === 'mode') {
    demoCursorToEl(modeTest);
  } else if (at === 'panel') {
    const visible = [...panelBody.querySelectorAll('.q-proveri')]
      .find(b => b.offsetParent !== null);
    if (visible) demoCursorToEl(visible);
  }
}

function renderDemoStep(i) {
  demoStepIndex = i;
  const step = DEMO_STEPS[i];
  if (step.a) step.a();                 // perform this step's move, then pause on the bubble
  const last = i === DEMO_STEPS.length - 1;
  const nextLabel = last ? 'Završi' : 'Dalje';
  demoBubbleEl.innerHTML =
    '<div class="demo-step">' + (i + 1) + '/' + DEMO_STEPS.length + ' · ' + step.l + '</div>' +
    '<div>' + step.t + '</div>' +
    '<div class="demo-ctrls">' +
    '<button class="demo-skip" id="demoSkip">Preskoči</button>' +
    '<button id="demoNext">' + nextLabel + '</button></div>';
  demoPositionBubble(step.at);
  document.getElementById('demoSkip').onclick = endDemo;
  document.getElementById('demoNext').onclick = () => {
    if (demoStepIndex >= DEMO_STEPS.length - 1) { endDemo(); return; }
    renderDemoStep(demoStepIndex + 1);
  };
}

function demoResetSrbija() {
  const inp = inputsById.get(DEMO_TERM.id);
  if (!inp) return;
  const cell = inp.parentElement;
  inp.classList.remove('correct', 'wrong', 'wrong-placed');
  inp.readOnly = false; inp.dataset.miss = '0'; inp.value = '';
  cell.classList.remove('drag-placed', 'dragging');
  cell.dataset.sx = cell.dataset.canonSx;
  cell.dataset.sy = cell.dataset.canonSy;
  const badge = cell.querySelector('.miss');
  if (badge) { badge.style.display = 'none'; badge.textContent = '0'; }
  const li = legendItems.get(DEMO_TERM.id);
  if (li) li.classList.remove('placed');
  quizProgress.delete(DEMO_TERM.id);
}

function startDemo() {
  if (demoDone || document.body.classList.contains('demo-running')) return;
  document.body.classList.add('demo-running');
  // make sure we start clean, in learn mode, with Srbija unplaced
  if (isTestMode()) setTestMode(false, {});
  demoResetSrbija();
  apply();
  recountCorrectMiss();
  demoCursorEl = document.createElement('div');
  demoCursorEl.id = 'demoCursor';
  demoCursorEl.textContent = '👆';
  demoBubbleEl = document.createElement('div');
  demoBubbleEl.id = 'demoBubble';
  document.body.appendChild(demoCursorEl);
  document.body.appendChild(demoBubbleEl);
  const li = legendItems.get(DEMO_TERM.id);
  if (li) demoCursorToEl(li);
  renderDemoStep(0);
}

function endDemo() {
  if (demoCursorEl) { demoCursorEl.remove(); demoCursorEl = null; }
  if (demoBubbleEl) { demoBubbleEl.remove(); demoBubbleEl = null; }
  document.body.classList.remove('demo-running');
  demoDone = true;
  // reset board to a clean learn-mode quiz, then permanently hide Srbija
  if (isTestMode()) setTestMode(false, {}); else { applyAnswers({}); recountCorrectMiss(); apply(); }
  closePanel();
  hideDemoTerm();
  saveState();
}

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
  if (saved.testMode) setTestMode(true, { restore: true });
  if (saved.demoDone) { demoDone = true; }
  resumeBanner.classList.add('show');
} else {
  setMode('all', {});
}
recountBonus();
if (demoDone) hideDemoTerm();

window.addEventListener('resize', () => { setHeaderTop(); fit(); });
setHeaderTop();
fit();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Knowledge base (shared/znanje) — side-panel descriptions
# ---------------------------------------------------------------------------

import html as _html
import re as _re


def _find_znanje_dir(spec):
    """Walk up from the spec dir to find shared/znanje/. Returns Path or None."""
    start = pathlib.Path(spec.get("_spec_dir", ".")).resolve()
    for base in [start, *start.parents]:
        cand = base / "shared" / "znanje"
        if cand.is_dir():
            return cand
    return None


def _md_inline(text):
    """Minimal inline Markdown → HTML: escape, then **bold**, *italic*, strip [[wikilinks]]."""
    text = _re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)          # [[slug]] → slug
    text = _html.escape(text)
    text = _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = _re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", text)
    return text


def _md_blocks_to_html(body):
    """Convert a small Markdown fragment (paragraphs + '- ' bullet lists) to HTML."""
    out, buf_list = [], []

    def flush_list():
        if buf_list:
            out.append("<ul>" + "".join(f"<li>{_md_inline(x)}</li>" for x in buf_list) + "</ul>")
            buf_list.clear()

    para = []

    def flush_para():
        if para:
            out.append("<p>" + _md_inline(" ".join(para)) + "</p>")
            para.clear()

    for raw in body.splitlines():
        line = raw.rstrip()
        if line.startswith("- "):
            flush_para()
            buf_list.append(line[2:].strip())
        elif not line.strip():
            flush_para(); flush_list()
        else:
            flush_list()
            para.append(line.strip())
    flush_para(); flush_list()
    return "".join(out)


def _extract_section(md_body, heading):
    """Return the text under a '## {heading}' up to the next '## ' (or end)."""
    m = _re.search(
        r"^##\s+" + _re.escape(heading) + r"\s*$(.*?)(?=^##\s|\Z)",
        md_body, _re.MULTILINE | _re.DOTALL,
    )
    return m.group(1).strip() if m else ""


def _parse_frontmatter(text):
    """Split a Markdown file into (frontmatter_dict, body)."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                fm = {}
            return fm, parts[2]
    return {}, text


def _term_descriptions(spec):
    """For each term with a `slug`, load shared/znanje/{slug}/index.md and build a
    panel HTML snippet (Sažetak + Ključne činjenice) + vrsta + source attributions.
    Returns {term_id: {"vrsta": str|None, "html": str, "sources": [{naziv,url}]}}.
    Terms without a knowledge folder are omitted (client shows a placeholder)."""
    znanje = _find_znanje_dir(spec)
    result = {}
    if not znanje:
        return result
    for t in spec["terms"]:
        slug = t.get("slug")
        if not slug:
            continue
        idx = znanje / slug / "index.md"
        if not idx.is_file():
            continue
        fm, body = _parse_frontmatter(idx.read_text(encoding="utf-8"))
        sazetak = _extract_section(body, "Sažetak")
        cinjenice = _extract_section(body, "Ključne činjenice")
        # Progressive hints (ordered, subtle → concrete); revealed one per wrong attempt.
        hints = [
            _md_inline(ln.strip()[2:].strip())
            for ln in _extract_section(body, "Hintovi").splitlines()
            if ln.strip().startswith("- ")
        ]
        html_parts = []
        if sazetak:
            html_parts.append(_md_blocks_to_html(sazetak))
        if cinjenice:
            html_parts.append('<h4>Ključne činjenice</h4>')
            html_parts.append(_md_blocks_to_html(cinjenice))
        if not html_parts:
            continue
        # Source attributions from referenced izvori/*.md frontmatter
        sources = []
        for rel in (fm.get("izvori") or []):
            src = (znanje / slug / rel)
            if src.is_file():
                sfm, _ = _parse_frontmatter(src.read_text(encoding="utf-8"))
                if sfm.get("izvor"):
                    sources.append({"naziv": sfm["izvor"], "url": sfm.get("url", "")})
        result[t["id"]] = {
            "vrsta": fm.get("vrsta"),
            "html": "".join(html_parts),
            "sources": sources,
            "hints": hints,
        }
    return result


def _term_questions(spec):
    """For each term with a `slug`, load shared/znanje/{slug}/pitanja.yaml (test mode).
    Returns {term_id: {"questions": [...], "bonus": {...}|None}} where each question is
    {"tezina", "pitanje", "options": [{"t": text, "c": is_correct}]}. Terms without a
    pitanja.yaml are omitted (test mode shows nothing for them)."""
    znanje = _find_znanje_dir(spec)
    result = {}
    if not znanje:
        return result

    def _conv(q):
        return {
            "tezina": q.get("tezina"),
            "pitanje": q.get("pitanje", ""),
            "options": [
                {"t": o.get("tekst", ""), "c": bool(o.get("tacan"))}
                for o in (q.get("odgovori") or [])
            ],
        }

    for t in spec["terms"]:
        slug = t.get("slug")
        if not slug:
            continue
        pf = znanje / slug / "pitanja.yaml"
        if not pf.is_file():
            continue
        try:
            data = yaml.safe_load(pf.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        questions = [_conv(q) for q in (data.get("pitanja") or [])]
        if not questions:
            continue
        bonus = _conv(data["bonus"]) if data.get("bonus") else None
        result[t["id"]] = {"questions": questions, "bonus": bonus}
    return result


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

    # Mountains, rivers, and mountain marks reference CSS variables so the
    # B&W toggle can swap them at runtime. Each element gets a class so the
    # "hide features" toggle can target them via CSS.
    mtn_svg = "".join(
        f'<polyline class="feat-mtn" data-term="{tid}" points="{polyline_str(p)}" fill="none" '
        f'stroke="var(--mtn-col)" stroke-width="3" stroke-linejoin="round" '
        f'stroke-linecap="round"/>'
        for tid, p in spec["_mountains"]
    )
    mtn_marks = ""
    for tid, pts in spec["_mountains"]:
        for lo, la in pts:
            x, y = px(lo, la)
            mtn_marks += (
                f'<path class="feat-mtn-mark" data-term="{tid}" d="M{x-3:.1f},{y+3:.1f} '
                f'L{x:.1f},{y-3:.1f} L{x+3:.1f},{y+3:.1f} Z" '
                f'fill="var(--mtn-col)"/>'
            )
    riv_svg = "".join(
        f'<polyline class="feat-riv" data-term="{tid}" points="{polyline_str(p)}" fill="none" '
        f'stroke="var(--riv-col)" stroke-width="2.2" stroke-linejoin="round" '
        f'stroke-linecap="round"/>'
        for tid, p in spec["_rivers"]
    )

    boxes = ""
    for t in spec["terms"]:
        lon, lat = t["label_at"]
        x, y = px(lon, lat)
        demo_attr = ' data-demo="1"' if t.get("demo") else ''
        # data-sx/sy is the CURRENT position (mutable when dragging in drag mode);
        # data-canon-sx/sy is the IMMUTABLE canonical position used for distance check.
        boxes += (
            f'<div class="cell"{demo_attr} data-sx="{x:.1f}" data-sy="{y:.1f}" '
            f'data-canon-sx="{x:.1f}" data-canon-sy="{y:.1f}">'
            f'<input class="ans" data-id="{t["id"]}" data-correct="{t["id"]}" data-miss="0" '
            f'maxlength="3" inputmode="numeric" autocomplete="off" aria-label="number">'
            f'<span class="miss" style="display:none">0</span></div>'
        )

    def _leg_row(t):
        if t.get("demo"):
            return (f'<li class="demo-item" data-id="{t["id"]}" data-demo="1">'
                    f'<b>{t["id"]}.</b> {t["name"]} <span class="demo-badge">demo</span></li>')
        return f'<li data-id="{t["id"]}"><b>{t["id"]}.</b> {t["name"]}</li>'

    leg_rows = "".join(_leg_row(t) for t in spec["terms"])

    # Terms JSON for client-side use. Includes:
    #   id, name           — for CSV export + display
    #   label_at           — canonical center, fallback for drop check
    #   geometry.polyline  — used by accept.buffer_deg
    #   accept             — per-term drop acceptance criteria (any matching = correct)
    descriptions = _term_descriptions(spec)
    questions = _term_questions(spec)
    terms_json = _json.dumps(
        [
            {
                "id": t["id"],
                "name": t["name"],
                "label_at": t.get("label_at"),
                "geometry": t.get("geometry"),
                "accept": t.get("accept"),
                # Demo term (Srbija) — not counted; clicking its legend item runs the demo
                "demo": bool(t.get("demo", False)),
                # Learn-mode side-panel content (None → client placeholder)
                "desc": descriptions.get(t["id"]),
                # Test-mode questions (None → no test content for this term)
                "quiz": questions.get(t["id"]),
            }
            for t in spec["terms"]
        ],
        ensure_ascii=False
    )

    n_quiz = len([t for t in spec["terms"] if not t.get("demo")])
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
        "__HDR_SUB_DRAG__": ui["header_subtitle_drag"],
        "__LBL_CORRECT__": ui["stat_correct"],
        "__LBL_MISS__": ui["stat_miss"],
        "__BTN_RESET__": ui["btn_reset"],
        "__BTN_CSV__": ui["btn_export_csv"],
        "__MODE_LABEL__": ui["mode_label"],
        "__MODE_ALL__": ui["mode_all"].replace("{n}", str(n_quiz)),
        "__MODE_20__": ui["mode_random"].replace("{n}", "20"),
        "__MODE_10__": ui["mode_random"].replace("{n}", "10"),
        "__MODE_5__": ui["mode_random"].replace("{n}", "5"),
        "__TGL_FEATURES__": ui["toggle_features"],
        "__TGL_BORDERS__": ui["toggle_borders"],
        "__TGL_BW__": ui["toggle_bw"],
        "__TGL_DRAG__": ui["toggle_drag"],
        "__LIST_HEADING__": ui["list_heading"],
        "__LEG_MOUNTAINS__": ui["legend_mountains"],
        "__LEG_RIVERS__": ui["legend_rivers"],
        "__LEG_CIRCLES__": ui["legend_circles"],
        "__ZHINT__": ui["zoom_hint"],
        "__RESUME_MSG__": ui["resume_indicator"],
        "__TOTAL__": str(n_quiz),
        "__TERMS_JSON__": terms_json,
        "__RANDOMIZE_NUMBERS__": "true" if spec.get("randomize_numbers", True) else "false",
        # Projection constants — JS uses these to convert drop screen coords back to lon/lat
        "__PROJ_LON0__": f"{extent_lon[0]}",
        "__PROJ_LAT1__": f"{extent_lat[1]}",
        "__PROJ_SX__": f"{(map_width_px / (extent_lon[1] - extent_lon[0])):.6f}",
        "__PROJ_SY__": f"{(map_width_px / (extent_lon[1] - extent_lon[0])) * (1.0 / math.cos(math.radians(mid_lat))):.6f}",
        "__MSG_CORRECT__": _json.dumps(ui["msg_correct"]),
        "__MSG_WRONG__": _json.dumps(ui["msg_wrong"]),
        "__MSG_WIN__": _json.dumps(ui["msg_win"]),
        "__MODE_ALL_TPL__": _json.dumps(ui["mode_all"]),
        "__MODE_RANDOM_TPL__": _json.dumps(ui["mode_random"]),
        "__PANEL_CLOSE__": _html.escape(ui["panel_close"], quote=True),
        "__PANEL_PLACEHOLDER__": _json.dumps(ui["panel_placeholder"]),
        "__PANEL_SOURCE_LBL__": _json.dumps(ui["panel_source_label"]),
        "__PANEL_HINT_HEADING__": _json.dumps(ui["panel_hint_heading"]),
        "__PANEL_HINT_PROMPT__": _json.dumps(ui["panel_hint_prompt"]),
        "__PANEL_HINTS_DONE__": _json.dumps(ui["panel_hints_done"]),
        "__PANEL_NO_HINT__": _json.dumps(ui["panel_no_hint"]),
        "__MODE_SWITCH_LABEL__": _html.escape(ui["mode_switch_label"]),
        "__MODE_LEARN__": _html.escape(ui["mode_learn"]),
        "__MODE_TEST__": _html.escape(ui["mode_test"]),
        "__LBL_BONUS__": _html.escape(ui["stat_bonus"]),
        "__BTN_PROVERI__": _json.dumps(ui["btn_proveri"]),
        "__Q_CORRECT__": _json.dumps(ui["q_correct"]),
        "__Q_WRONG__": _json.dumps(ui["q_wrong"]),
        "__BONUS_LABEL__": _json.dumps(ui["bonus_label"]),
        "__BONUS_LOCKED__": _json.dumps(ui["bonus_locked"]),
        "__TEST_NO_Q__": _json.dumps(ui["test_no_questions"]),
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

    # Demo terms (Srbija) are interactive-only; never drawn on the printable PDF.
    pdf_terms = [t for t in spec["terms"] if not t.get("demo")]
    r = 0.95
    for t in pdf_terms:
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
    n = len(pdf_terms)
    col_split = (n + 1) // 2
    y0, dy = 0.955, 0.0445
    for i, t in enumerate(pdf_terms):
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
