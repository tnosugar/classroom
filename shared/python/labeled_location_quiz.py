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
        "btn_borders_on": "Borders: on",
        "btn_borders_off": "Borders: off",
        "btn_borders_locked_title": "Borders can be changed only before the first term is placed.",
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
        "msg_revealed": "10 attempts used — the location has been revealed.",
        "msg_win": "Done! All correct ({total}/{total}) · total mistakes: {miss}",
        "resume_indicator": "Resumed previous session — your progress is restored.",
        "zoom_hint": "Zoom: + / − / wheel / dblclick · Drag to pan",
        "pdf_title_quiz": "Quiz",
        "pdf_title_answer": "Answer key",
        "pdf_legend_heading": "Terms:",
        "pdf_legend_symbols": "▲ mountains    — rivers    ○ location",
        "panel_close": "Zatvori",
        "panel_placeholder": "Opis uskoro.",
        "panel_idle": "Prevuci pojam na kartu — ovde se prikazuje opis (Učenje) ili pitanja (Test).",
        "panel_source_label": "Izvor:",
        "panel_hint_heading": "Hint",
        "panel_hint_prompt": "Hint se otkriva sa svakom greškom — pokušaj da postaviš pojam.",
        "panel_hints_done": "Svi hintovi iskorišćeni — evo opisa:",
        "panel_no_hint": "Nema hinta za ovaj pojam (još).",
        "mode_switch_label": "Mod",
        "mode_learn": "Učenje",
        "mode_test": "Test",
        "btn_desc": "Opis",
        "btn_desc_ok": "Razumem",
        "stat_answers": "Pitanja",
        "stat_bonus": "Bonus",
        "btn_proveri": "Proveri",
        "q_correct": "Tačno!",
        "q_wrong": "Pogrešno — pokušaj ponovo",
        "q_incorrect": "Netačno (tačni odgovori su označeni).",
        "bonus_label": "Bonus",
        "bonus_locked": "Reši sva 3 pitanja da otključaš bonus.",
        "bonus_note": "Da bi odgovorio na bonus pitanje, potrebno je da istražuješ o geografskom pojmu u ponuđenim izvorima.",
        "test_no_questions": "Nema test-pitanja za ovaj pojam.",
        "analysis_title": "Analiza učinka",
        "analysis_run": "Analiziraj",
        "analysis_key_link": "API ključ",
        "analysis_key_label": "Claude API ključ (čuva se samo u ovom pregledaču):",
        "analysis_key_save": "Sačuvaj",
        "analysis_key_clear": "Obriši",
        "analysis_idle": "Analiza se pojavi kad lociraš sve pojmove i rešiš sva pitanja, ili je pokreni dugmetom 'Analiziraj'.",
        "analysis_note": "Analiza koristi Claude API i šalje samo tvoje rezultate (procente i oznake odgovora) radi ocene. Ključ se čuva lokalno u pregledaču i nije deo koda.",
        "analysis_loading": "Generišem analizu…",
        "analysis_no_key": "Za analizu je potreban Claude API ključ. Klikni 'API ključ', unesi ga (čuva se lokalno), pa ponovo 'Analiziraj'.",
        "analysis_error": "Greška pri analizi:",
        "analysis_empty": "Nema dovoljno podataka — prvo uradi bar nešto u testu.",
        "m_confirm": "Potvrdi",
        "m_next": "Sledeći pojam ›",
        "m_next_desc": "Dalje na opis ›",
        "m_next_q": "Dalje na pitanja ›",
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
 .resume-banner{display:none;margin:14px 4px 0;background:#fffbe6;border:1px solid #f0d878;border-radius:8px;padding:6px 12px;font-size:13px;color:#7a5a00}
 .resume-banner.show{display:block}
 .layout{display:flex;align-items:flex-start;gap:0;width:100%}
 .qcol{flex:0 0 260px;width:260px;padding:12px 14px;border-right:1px solid #e6e0d2;background:#fff;position:sticky;top:var(--htop,0px);max-height:calc(100vh - var(--htop,0px));overflow:auto}
 .qcol h2{font-size:14px;color:#3a3528;margin:0 0 8px}
 .mapcol{flex:1 1 auto;min-width:0;padding:0}
 /* Info side panel (third column) — opens when a term is solved or its marker clicked */
 .panelcol{flex:0 0 440px;width:440px;padding:14px 16px;border-left:1px solid #e6e0d2;background:#fff;position:sticky;top:var(--htop,0px);max-height:calc(100vh - var(--htop,0px));overflow:auto}
 /* Panel column is ALWAYS present (reserves space right of the map). When idle,
    only its header/footer hide; the body shows a placeholder. */
 .layout:not(.panel-open) .panelhead, .layout:not(.panel-open) .panelfoot{display:none}
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
 /* Title + description live in a dismissible modal; "Opis" button reopens it */
 .desc-btn{font-size:13px;padding:5px 12px}
 .desc-modal{position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;padding:20px}
 .desc-modal[hidden]{display:none}
 .desc-modal-box{background:#fff;max-width:640px;width:100%;border-radius:12px;padding:24px 26px 20px;box-shadow:0 10px 40px rgba(0,0,0,.32);position:relative}
 .desc-modal-box h1{margin:0 0 12px;font-size:21px;color:#3a3528}
 .desc-modal-box .sub{font-size:14px;color:#4a4434;line-height:1.6;margin:0;max-width:none}
 .desc-modal-x{position:absolute;top:10px;right:12px;border:none;background:transparent;font-size:26px;line-height:1;color:#6b6456;cursor:pointer;padding:0 4px}
 .desc-modal-x:hover{background:transparent;color:#b1271f}
 .desc-ok{margin-top:18px}
 /* Performance analysis section below the map (test mode) */
 .analysis{margin:14px 4px 28px;padding:14px 16px;border:1px solid #e1d8c2;border-radius:10px;background:#fff}
 body:not(.test-mode) .analysis{display:none}
 .analysis-head{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:10px}
 .analysis-head h2{margin:0;font-size:16px;color:#3a3528;flex:1}
 .analysis-key{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px;font-size:13px}
 .analysis-key input{font:inherit;padding:5px 8px;border:1px solid #6b6456;border-radius:6px;min-width:240px}
 .analysis-body{font-size:13.5px;line-height:1.6;color:#2b2b2b}
 .analysis-body h3{font-size:14px;color:#3a3528;margin:12px 0 4px}
 .analysis-body p{margin:0 0 9px} .analysis-body ul{margin:0 0 9px;padding-left:18px}
 .analysis-body .placeholder{color:#9b9387;font-style:italic}
 .analysis-body .loading{color:#6b6456} .analysis-body .err{color:#b1271f}
 .analysis-note{margin:10px 0 0;font-size:11px;color:#9b9387}
 .link-btn{border:none;background:transparent;color:#6b6456;text-decoration:underline;cursor:pointer;padding:0;font:inherit;font-size:12.5px}
 .link-btn:hover{background:transparent;color:#b1271f}
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
 #demoBubble{position:fixed;z-index:301;left:14px;bottom:16px;width:236px;height:210px;display:flex;flex-direction:column;background:#2b2b2b;color:#fff;font-size:12.5px;line-height:1.4;padding:10px 12px;border-radius:10px;box-shadow:0 4px 16px rgba(0,0,0,.35)}
 #demoBubble .demo-text{flex:1;overflow:auto;margin:2px 0}
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
 body:not(.test-mode) #statCorrect, body:not(.test-mode) #statMiss, body:not(.test-mode) #statAnswers,
 body:not(.test-mode) #win, body:not(.test-mode) #exportCsv { display: none !important; }
 /* Per-term answer-state markers in the legend (test mode): 3 questions + bonus */
 .qmarks{margin-left:6px;font-size:11px;letter-spacing:1px;white-space:nowrap}
 .qm-todo{color:#b9b2a0} .qm-ok{color:#1f7a3a} .qm-bad{color:#b1271f}
 .qm-bonus{margin-left:3px}
 body:not(.test-mode) .qmarks{display:none}
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
 .quiz .opt.miss-correct{color:#1f7a3a;text-decoration:underline;font-weight:600}
 .quiz .opt.chosen-wrong{color:#b1271f;font-weight:600}
 .quiz .q.answered-wrong,.quiz .bonus.answered-wrong{background:#fdecec;border-color:#e6b0b0}
 .quiz .bonus{background:#fff7e6;border-color:#f0d878}
 .quiz .bonus.locked .opt input,.quiz .bonus.locked .q-proveri{pointer-events:none;opacity:.5}
 .quiz .bonus .q-tezina{background:#fce9b8;border-color:#f0d878;color:#7a5a00}
 .quiz .bonus-lock-msg{font-size:11.5px;color:#7a5a00;margin-top:6px}
 .quiz .bonus-note{font-size:11.5px;color:#7a5a00;font-style:italic;margin:0 0 8px}
 #stageWrap{width:100%;overflow:hidden;position:relative;touch-action:none;cursor:grab}
 #stageWrap.grabbing{cursor:grabbing}
 .zoombar{position:absolute;right:12px;top:12px;z-index:30;display:grid;grid-template-columns:auto auto;gap:6px}
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
 .ans.correct.revealed-loc{background:#fde7c9;border-color:#c98a2c;color:#8a5a14}  /* otkriveno (10 pokušaja) */
 ol.terms li.revealed-loc b{color:#c98a2c}
 svg .reveal-area{fill:rgba(201,138,44,.10);stroke:#c98a2c;stroke-width:1.6;stroke-dasharray:5 3;pointer-events:none}
 .ans.wrong{animation:shake .3s;background:#fdd;border-color:#b1271f}
 @keyframes shake{0%,100%{transform:translateX(0)}25%{transform:translateX(-4px)}75%{transform:translateX(4px)}}
 .miss{position:absolute;top:-9px;right:-9px;background:#b1271f;color:#fff;font-size:10px;font-weight:700;min-width:16px;height:16px;line-height:16px;text-align:center;border-radius:9px;padding:0 3px}
 ol.terms{list-style:none;padding:0;margin:0;font-size:12px;line-height:1.55}
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
 /* Country borders: shown by default; toggled (only before the first term) via #bordersBtn. */
 body.show-borders svg .border-path { display: inline }
 #bordersBtn:disabled,#mMenuBorders:disabled{opacity:.5;cursor:default}
 #bordersBtn.borders-off,#mMenuBorders.borders-off{color:#9b3b32;border-color:#c98a2c}

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
 /* ===== MOBILE (class set by JS via matchMedia) — screen-at-a-time flow ===== */
 .m-only{display:none}
 body.mobile .m-only{display:flex}
 body.mobile .layout{display:block}
 body.mobile .qcol,body.mobile .mapcol,body.mobile .panelcol{
   position:fixed;left:0;right:0;top:var(--htop,52px);bottom:0;width:auto;max-height:none;
   border:none;overflow:auto;background:#faf8f2;z-index:30}
 body.mobile .qcol{padding:10px 14px}
 body.mobile .qcol ol.terms{columns:1;font-size:15px;line-height:1.7}
 body.mobile ol.terms li{padding:9px 8px;border-bottom:1px solid #eee}
 body.mobile .mapcol{padding:0}
 body.mobile .panelcol{padding:14px 16px 84px;border-top:none}
 body.mobile:not(.m-list) .qcol{display:none}
 body.mobile:not(.m-map) .mapcol{display:none}
 body.mobile:not(.m-result) .panelcol{display:none}
 body.mobile #stageWrap{height:100%!important}
 /* active-term label: top-left of the map, both orientations; visible while on the map screen */
 #mTermLabel{display:none}
 body.mobile.m-map #mTermLabel{display:block;position:absolute;left:12px;top:12px;z-index:30;
   background:rgba(255,255,255,.92);border:1px solid #6b6456;border-radius:9px;
   padding:6px 11px;font-weight:700;font-size:14px;color:#3a3528;max-width:62%;
   box-shadow:0 1px 3px rgba(0,0,0,.22)}
 body.mobile.m-map #mTermLabel:empty{display:none}
 body.mobile .resume-banner,body.mobile #analysis{display:none!important}      /* phase 2 */
 body.mobile li.demo-item{display:none!important}                              /* phase 2 */
 body.mobile .panelhead .panel-x{display:none}                                 /* nav handles closing */
 /* compact top bar */
 body.mobile header{padding:8px 12px}
 body.mobile .bar{gap:6px 8px;align-items:center}
 body.mobile #statCorrect,body.mobile #statMiss,body.mobile #statAnswers,body.mobile #bonusStat{font-size:11px;padding:3px 7px}
 /* stats grouping: own row under the header in mobile portrait test; inline in landscape */
 .stats-group{display:inline-flex;gap:8px;align-items:center;flex-wrap:wrap}
 body:not(.test-mode) .stats-group{display:none}
 body.mobile.test-mode .stats-group{display:flex;flex-basis:100%;gap:6px;order:9}
 @media (orientation:landscape){ body.mobile.test-mode .stats-group{flex-basis:auto;order:0} }
 body.mobile .mode-selector,body.mobile #exportCsv,body.mobile #descBtn,body.mobile #reset,body.mobile #bordersBtn{display:none}
 body.mobile #mobileBack,body.mobile #mobileMenuBtn{display:inline-flex}
 #mobileBack,#mobileMenuBtn{display:none;align-items:center;justify-content:center;font-size:20px;line-height:1;padding:5px 10px;min-width:auto}
 body.mobile.m-list #mobileBack{visibility:hidden}
 /* ⋯ menu */
 #mobileMenu{display:none;position:fixed;right:10px;top:var(--htop,52px);z-index:70;background:#fff;border:1px solid #e1d8c2;border-radius:10px;box-shadow:0 6px 20px rgba(0,0,0,.2);padding:8px;min-width:190px}
 body.mobile #mobileMenu.open{display:block}
 #mobileMenu button,#mobileMenu label{display:block;width:100%;text-align:left;margin:4px 0;border:none;background:transparent;color:#3a3528;font:inherit;padding:8px;border-radius:6px;cursor:pointer}
 #mobileMenu button:hover{background:#f3ecd8;color:#3a3528}
 #mobileMenu select{font:inherit;width:100%;padding:6px;border:1px solid #6b6456;border-radius:6px;margin-top:4px}
 /* bottom action bars */
 .m-bottombar{display:none;position:fixed;left:0;right:0;bottom:0;z-index:60;background:#fff;border-top:1px solid #e1d8c2;padding:10px 14px;gap:10px}
 body.mobile.m-map #mobileMapBar{display:flex}
 body.mobile.m-result #mobileResultBar{display:flex}
 .m-bottombar button{width:100%;padding:13px;font-size:15px;border-radius:10px}
 #mPotvrdi:disabled{opacity:.45;border-color:#bbb;color:#bbb;background:#fff;cursor:default}
 body.mobile #msg{bottom:80px}   /* sit above the bottom action bar, not over the button */
 /* hint bottom-sheet */
 #mobileHint{display:none;position:fixed;left:0;right:0;bottom:74px;z-index:58;background:#2b2b2b;color:#fff;
   max-height:33vh;overflow:auto;padding:12px 36px 14px 14px;border-radius:12px 12px 0 0;box-shadow:0 -4px 16px rgba(0,0,0,.35);font-size:13px;line-height:1.5}
 body.mobile.m-map.m-hint-on:not(.m-hint-min) #mobileHint{display:block}
 #mobileHint h4{margin:0 0 6px;font-size:12px;color:#ffd27a;text-transform:uppercase;letter-spacing:.05em}
 #mobileHint ol{margin:0;padding-left:18px} #mobileHint li{margin:5px 0}
 #mobileHint .m-hint-min{position:absolute;top:8px;right:8px;border:none;background:rgba(255,255,255,.15);color:#fff;width:26px;height:26px;border-radius:7px;font-size:16px;line-height:1;cursor:pointer;padding:0}
 #mobileHint .m-hint-min:hover{background:rgba(255,255,255,.28);color:#fff}
 /* minimized hint → square button under the zoom buttons */
 #hintRestore{display:none}
 body.mobile.m-map.m-hint-on.m-hint-min #hintRestore{display:flex;align-items:center;justify-content:center;grid-column:2}
 #hintRestore{background:#2b2b2b;color:#ffd27a;border-color:#2b2b2b}
 #hintRestore:hover{background:#3a3a3a;color:#ffd27a}
 /* provisional pin (mobile place) */
 body.mobile .cell.m-provisional{display:block!important}
 body.mobile .cell.m-provisional .ans{box-shadow:0 0 0 3px rgba(177,39,31,.25)}
 body.mobile .map-hint{position:absolute;left:50%;bottom:84px;transform:translateX(-50%);z-index:40;background:rgba(255,255,255,.92);border:1px solid #e1d8c2;border-radius:8px;padding:6px 12px;font-size:12px;color:#6b6456;pointer-events:none}
 @media print {
   header .bar, .zoombar, .zhint, #msg, .resume-banner, button, .panelcol, .analysis { display: none !important; }
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
 <div class="bar">
  <button id="mobileBack" type="button" aria-label="Nazad">&lsaquo;</button>
  <button id="descBtn" class="desc-btn">__BTN_DESC__</button>
  <span class="mode-switch">__MODE_SWITCH_LABEL__:
   <button type="button" id="modeLearn" class="ms-btn active">__MODE_LEARN__</button><button type="button" id="modeTest" class="ms-btn">__MODE_TEST__</button>
  </span>
  <button id="mobileMenuBtn" type="button" aria-label="Meni">&#8943;</button>
  <span class="stats-group">
  <span class="stat" id="statCorrect">__LBL_CORRECT__: <b class="ok" id="cCorrect">0</b> / <b id="cTotal">__TOTAL__</b></span>
  <span class="stat" id="statAnswers" style="display:none">__LBL_ANSWERS__: <b class="ok" id="cAnswers">0</b> / <b id="cAnswersTotal">0</b></span>
  <span class="stat" id="statMiss">__LBL_MISS__: <b class="bad" id="cMiss">0</b></span>
  <span class="stat bonus-stat" id="bonusStat" style="display:none">__LBL_BONUS__: <b class="ok" id="cBonus">0</b> / <b id="cBonusTotal">0</b></span>
  </span>
  <button id="reset">__BTN_RESET__</button>
  <button id="bordersBtn" class="secondary" title="__BTN_BORDERS_LOCKED_TITLE__">__BTN_BORDERS_ON__</button>
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
</header>
<div id="mobileMenu">
 <button id="mMenuOpis" type="button">__BTN_DESC__</button>
 <button id="mMenuReset" type="button">__BTN_RESET__</button>
 <button id="mMenuBorders" type="button">__BTN_BORDERS_ON__</button>
 <label>__MODE_LABEL__
  <select id="mobileMode">
   <option value="all">__MODE_ALL__</option>
   <option value="20">__MODE_20__</option>
   <option value="10">__MODE_10__</option>
   <option value="5">__MODE_5__</option>
  </select>
 </label>
</div>
<div id="mobileMapBar" class="m-bottombar"><button id="mPotvrdi" type="button" class="secondary" disabled>__M_CONFIRM__</button></div>
<div id="mobileResultBar" class="m-bottombar"><button id="mNext" type="button" class="secondary">__M_NEXT__</button></div>
<div id="mobileHint"></div>
<div id="descModal" class="desc-modal" hidden>
 <div class="desc-modal-box">
  <button class="desc-modal-x" id="descClose" aria-label="__PANEL_CLOSE__">&times;</button>
  <h1>__HDR_TITLE__</h1>
  <p class="sub">__HDR_SUB_DRAG__</p>
  <button id="descOk" class="desc-ok">__BTN_DESC_OK__</button>
 </div>
</div>
<div class="layout">
 <aside class="qcol">
  <h2>__LIST_HEADING__</h2>
  <ol class="terms">__LEG__</ol>
  <p class="keyline"><span class="m">__LEG_MOUNTAINS__</span><br><span class="r">__LEG_RIVERS__</span><br>__LEG_CIRCLES__</p>
 </aside>
 <main class="mapcol">
  <div id="stageWrap">
   <div id="mTermLabel"></div>
   <div class="zoombar">
    <button id="zreset" title="⟳">⟳</button>
    <button id="zin" title="+">+</button>
    <button id="zfull" title="Ceo ekran" aria-label="Ceo ekran">&#9974;</button>
    <button id="zout" title="−">−</button>
    <button id="hintRestore" title="Prikaži hint" aria-label="Prikaži hint">&#128161;</button>
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
  <div id="resumeBanner" class="resume-banner">__RESUME_MSG__</div>
  <section id="analysis" class="analysis">
   <div class="analysis-head">
    <h2>__ANALYSIS_TITLE__</h2>
    <button id="analysisRun" class="secondary">__ANALYSIS_RUN__</button>
    <button id="analysisKeyToggle" class="link-btn">__ANALYSIS_KEY_LINK__</button>
   </div>
   <div id="analysisKeyRow" class="analysis-key" hidden>
    <label>__ANALYSIS_KEY_LABEL__</label>
    <input type="password" id="analysisKey" placeholder="sk-ant-..." autocomplete="off" spellcheck="false">
    <button id="analysisKeySave">__ANALYSIS_KEY_SAVE__</button>
    <button id="analysisKeyClear" class="link-btn">__ANALYSIS_KEY_CLEAR__</button>
   </div>
   <div id="analysisBody" class="analysis-body"><p class="placeholder">__ANALYSIS_IDLE__</p></div>
   <p class="analysis-note">__ANALYSIS_NOTE__</p>
  </section>
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
const STATE_VERSION = 5;
const RANDOMIZE_NUMBERS = __RANDOMIZE_NUMBERS__;
// Projection constants for screen-pixel ↔ lon/lat conversion (drag mode only)
const PROJ_LON0 = __PROJ_LON0__, PROJ_LAT1 = __PROJ_LAT1__;
const PROJ_SX = __PROJ_SX__, PROJ_SY = __PROJ_SY__;
const MSG_CORRECT = __MSG_CORRECT__, MSG_WRONG = __MSG_WRONG__, MSG_WIN_TPL = __MSG_WIN__;
const MSG_REVEALED = __MSG_REVEALED__;
const MAX_LOC_ATTEMPTS = 10;   // after 10 wrong drops, the location is revealed & locked
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
    const id = parseInt(inp.dataset.id, 10);   // canonical id (matches visibleIds)
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
const PANEL_IDLE = __PANEL_IDLE__;
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
  layoutEl.classList.add('panel-open');
  document.getElementById('panelcol').setAttribute('aria-hidden', 'false');
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
  if (MOBILE()) { mShowHint(canonId); return; }   // mobile: bottom-sheet hint
  const t = ALL_TERMS.find(t => t.id === canonId);
  if (t && t.desc && t.desc.hints && t.desc.hints.length) showPanelFor(canonId);
}

function closePanel() {
  layoutEl.classList.remove('panel-open');
  document.getElementById('panelcol').setAttribute('aria-hidden', 'true');
  panelFoot.style.display = 'none';
  panelBody.innerHTML = '<p class="placeholder">' + PANEL_IDLE + '</p>';
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
const Q_CORRECT = __Q_CORRECT__, Q_WRONG = __Q_WRONG__, Q_INCORRECT = __Q_INCORRECT__;
const BONUS_LABEL = __BONUS_LABEL__, BONUS_LOCKED = __BONUS_LOCKED__;
const BONUS_NOTE = __BONUS_NOTE__;
const TEST_NO_Q = __TEST_NO_Q__;
const modeLearn = document.getElementById('modeLearn');
const modeTest = document.getElementById('modeTest');
const bonusStat = document.getElementById('bonusStat');
const cBonus = document.getElementById('cBonus');
const cBonusTotal = document.getElementById('cBonusTotal');
const statAnswers = document.getElementById('statAnswers');
const cAnswers = document.getElementById('cAnswers');
const cAnswersTotal = document.getElementById('cAnswersTotal');

function isTestMode() { return document.body.classList.contains('test-mode'); }
function esc(s) { return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

// Per-term quiz progress. A question is single-attempt: once answered it is
// terminal — 'solved' (correct) or 'wrong'. `chosen` keeps the picked options so
// a wrong question re-renders with the same red/green feedback within the session.
const quizProgress = new Map();
function getQP(canonId) {
  let p = quizProgress.get(canonId);
  if (!p) {
    const t = ALL_TERMS.find(x => x.id === canonId);
    const n = (t && t.quiz && t.quiz.questions) ? t.quiz.questions.length : 0;
    p = { solved: new Array(n).fill(false), wrong: new Array(n).fill(false),
          chosen: {}, bonus: false, bonusWrong: false, bonusChosen: null };
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

// state: 'todo' | 'solved' | 'wrong'. chosen: array of picked indices (for 'wrong').
function optsHTML(options, state, chosen) {
  const sel = new Set(chosen || []);
  return options.map((o, oi) => {
    let cls = '', checked = '', dis = (state === 'todo') ? '' : ' disabled';
    if (state === 'solved') {
      if (o.c) { cls = ' reveal-correct'; checked = ' checked'; }
    } else if (state === 'wrong') {
      if (sel.has(oi)) checked = ' checked';
      if (o.c && sel.has(oi)) cls = ' reveal-correct';        // correct, picked
      else if (o.c && !sel.has(oi)) cls = ' miss-correct';    // correct, missed → green underline
      else if (!o.c && sel.has(oi)) cls = ' chosen-wrong';    // wrong, picked → red
    }
    return '<label class="opt' + cls + '"><input type="checkbox" data-oi="' + oi + '"' +
      checked + dis + '> ' + esc(o.t) + '</label>';
  }).join('');
}

function qStateClass(state) { return state === 'solved' ? ' solved' : (state === 'wrong' ? ' answered-wrong' : ''); }
function qStatusHTML(state) {
  if (state === 'solved') return '<span class="q-status ok">' + Q_CORRECT + '</span>';
  if (state === 'wrong') return '<span class="q-status bad">' + Q_INCORRECT + '</span>';
  return '<span class="q-status"></span>';
}

function questionHTML(q, qi, state, chosen) {
  const done = state !== 'todo';
  return '<div class="q' + qStateClass(state) + '" data-qi="' + qi + '">' +
    '<div class="q-head"><span class="q-tezina">' + esc(q.tezina || '') + '</span> ' +
    '<span class="q-txt">' + esc(q.pitanje) + '</span></div>' +
    optsHTML(q.options, state, chosen) +
    '<div><button type="button" class="q-proveri"' + (done ? ' style="display:none"' : '') + '>' +
    BTN_PROVERI + '</button>' + qStatusHTML(state) + '</div></div>';
}

function bonusHTML(bonus, unlocked, state, chosen) {
  const done = state !== 'todo';
  let h = '<div class="bonus' + (unlocked ? '' : ' locked') + qStateClass(state) + '" data-bonus>' +
    '<div class="q-head"><span class="q-tezina">' + BONUS_LABEL + '</span> ' +
    '<span class="q-txt">' + esc(bonus.pitanje) + '</span></div>' +
    '<div class="bonus-note">' + BONUS_NOTE + '</div>' +
    optsHTML(bonus.options, state, chosen) +
    '<div><button type="button" class="q-proveri" data-bonus-btn' + (done ? ' style="display:none"' : '') + '>' +
    BTN_PROVERI + '</button>' + qStatusHTML(state) + '</div>';
  if (!unlocked) h += '<div class="bonus-lock-msg">' + BONUS_LOCKED + '</div>';
  return h + '</div>';
}

function qStateOf(p, i) { return p.solved[i] ? 'solved' : (p.wrong[i] ? 'wrong' : 'todo'); }

function renderQuiz(canonId, quiz) {
  const p = getQP(canonId);
  const allAnswered = p.solved.length > 0 && p.solved.every((s, i) => s || p.wrong[i]);
  let h = '<div class="quiz" data-canon="' + canonId + '">';
  quiz.questions.forEach((q, qi) => { h += questionHTML(q, qi, qStateOf(p, qi), p.chosen[qi]); });
  if (quiz.bonus) {
    const bState = p.bonus ? 'solved' : (p.bonusWrong ? 'wrong' : 'todo');
    h += bonusHTML(quiz.bonus, allAnswered, bState, p.bonusChosen);
  }
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
  block.querySelectorAll('input[type=checkbox]').forEach(c => {
    const oi = parseInt(c.dataset.oi, 10);
    c.checked = !!options[oi].c;
    c.disabled = true;
    const lbl = c.closest('.opt');
    if (lbl && options[oi].c) lbl.classList.add('reveal-correct');
  });
  const pv = block.querySelector('.q-proveri');
  if (pv) pv.style.display = 'none';
  const st = block.querySelector('.q-status');
  st.className = 'q-status ok';
  st.textContent = Q_CORRECT;
}

// Wrong answer is terminal: lock the question, mark picked-wrong red and
// correct-not-picked green (underline); the question can no longer be changed.
function markBlockWrong(block, options) {
  block.classList.add('answered-wrong');
  block.querySelectorAll('input[type=checkbox]').forEach(c => {
    const oi = parseInt(c.dataset.oi, 10);
    const picked = c.checked;
    c.disabled = true;
    const lbl = c.closest('.opt');
    if (!lbl) return;
    if (options[oi].c && picked) lbl.classList.add('reveal-correct');
    else if (options[oi].c && !picked) lbl.classList.add('miss-correct');
    else if (!options[oi].c && picked) lbl.classList.add('chosen-wrong');
  });
  const pv = block.querySelector('.q-proveri');
  if (pv) pv.style.display = 'none';
  const st = block.querySelector('.q-status');
  st.className = 'q-status bad';
  st.textContent = Q_INCORRECT;
}

function maybeUnlockBonus(canonId) {
  const p = getQP(canonId);
  // Bonus unlocks once all 3 questions are ANSWERED (correct or wrong).
  if (p.solved.length > 0 && p.solved.every((s, i) => s || p.wrong[i])) {
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

// Count of correctly answered main questions across the counted terms.
function recountAnswers() {
  if (!isTestMode()) { statAnswers.style.display = 'none'; return; }
  let solved = 0, total = 0;
  for (const id of countedIds()) {
    const t = ALL_TERMS.find(x => x.id === id);
    if (t && t.quiz && t.quiz.questions) {
      total += t.quiz.questions.length;
      const p = quizProgress.get(id);
      if (p) solved += p.solved.filter(Boolean).length;
    }
  }
  cAnswers.textContent = solved;
  cAnswersTotal.textContent = total;
  statAnswers.style.display = total > 0 ? 'inline-block' : 'none';
}

// Legend markers for a term: ● tačno / ✕ pogrešno / ○ nedovršeno per question,
// and ★/✕/☆ for the bonus. Shown next to a placed term in test mode.
function legendMarksHTML(canonId) {
  const t = ALL_TERMS.find(x => x.id === canonId);
  if (!t || !t.quiz || !t.quiz.questions) return '';
  const p = getQP(canonId);
  let h = '';
  t.quiz.questions.forEach((q, i) => {
    if (p.solved[i]) h += '<span class="qm-ok">●</span>';
    else if (p.wrong[i]) h += '<span class="qm-bad">✕</span>';
    else h += '<span class="qm-todo">○</span>';
  });
  if (t.quiz.bonus) {
    if (p.bonus) h += '<span class="qm-ok qm-bonus">★</span>';
    else if (p.bonusWrong) h += '<span class="qm-bad qm-bonus">✕</span>';
    else h += '<span class="qm-todo qm-bonus">☆</span>';
  }
  return h;
}
function updateLegendMarks(canonId) {
  const li = legendItems.get(canonId);
  if (!li) return;
  let span = li.querySelector('.qmarks');
  const inp = inputsById.get(canonId);
  const placed = inp && inp.classList.contains('correct');
  const t = ALL_TERMS.find(x => x.id === canonId);
  const show = isTestMode() && placed && t && t.quiz && t.quiz.questions;
  if (!show) { if (span) span.remove(); return; }
  if (!span) { span = document.createElement('span'); span.className = 'qmarks'; li.appendChild(span); }
  span.innerHTML = legendMarksHTML(canonId);
}
function refreshAllLegendMarks() {
  for (const [id] of legendItems) updateLegendMarks(id);
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
  // Single attempt: an already-answered question can't be changed.
  if (block.classList.contains('solved') || block.classList.contains('answered-wrong')) return;
  const options = isBonus
    ? term.quiz.bonus.options
    : term.quiz.questions[parseInt(block.dataset.qi, 10)].options;
  const selected = new Set([...block.querySelectorAll('input[type=checkbox]')]
    .filter(c => c.checked).map(c => parseInt(c.dataset.oi, 10)));
  const chosenArr = [...selected];
  const p = getQP(canonId);
  const correct = optionsMatch(selected, options);
  if (isBonus) {
    if (correct) { p.bonus = true; p.bonusWrong = false; markBlockSolved(block, options); }
    else { p.bonusWrong = true; p.bonus = false; p.bonusChosen = chosenArr; markBlockWrong(block, options); }
    // bonus wrong does NOT count as a mistake
  } else {
    const qi = parseInt(block.dataset.qi, 10);
    if (correct) { p.solved[qi] = true; p.wrong[qi] = false; markBlockSolved(block, options); }
    else {
      p.wrong[qi] = true; p.solved[qi] = false; p.chosen[qi] = chosenArr;
      markBlockWrong(block, options);
      // wrong answer counts as a mistake on the term (same counter as bad location)
      const inp = inputsById.get(canonId);
      const m = (parseInt(inp.dataset.miss, 10) || 0) + 1;
      inp.dataset.miss = m;
      const badge = inp.parentElement.querySelector('.miss');
      badge.textContent = m;
      badge.style.display = 'block';
      recountCorrectMiss();
    }
    maybeUnlockBonus(canonId);
  }
  recountAnswers();
  recountBonus();
  updateLegendMarks(canonId);
  saveState();
  maybeAutoAnalyze();
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
  recountAnswers();
  refreshAllLegendMarks();
  saveState();
}
modeLearn.addEventListener('click', () => { if (isTestMode()) setTestMode(false, {}); });
modeTest.addEventListener('click', () => { if (!isTestMode()) setTestMode(true, {}); });

function check(inp) {
  if (inp.parentElement.classList.contains('hidden')) return;
  if (inp.classList.contains('correct')) return;
  const v = inp.value.trim();
  if (v === '') return;
  markQuizStarted();
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
      m: parseInt(inp.dataset.miss, 10) || 0,
      lm: parseInt(inp.dataset.locmiss, 10) || 0,
      rv: inp.classList.contains('revealed-loc')
    };
    // Drag placement (only relevant in drag mode for placed cells)
    if (cell.classList.contains('drag-placed')) {
      a.dp = true;
      a.px = parseFloat(cell.dataset.sx);
      a.py = parseFloat(cell.dataset.sy);
    }
    const qp = quizProgress.get(parseInt(inp.dataset.id, 10));
    if (qp && (qp.bonus || qp.bonusWrong || qp.solved.some(Boolean) || qp.wrong.some(Boolean))) {
      a.qz = qp.solved.slice();
      a.qw = qp.wrong.slice();
      a.bn = qp.bonus;
      a.bw = qp.bonusWrong;
    }
    answers[inp.dataset.id] = a;
  }
  const state = {
    v: STATE_VERSION,
    mode: currentMode,
    testMode: isTestMode(),
    demoDone: demoDone,
    borders: bordersOn,
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
    inp.dataset.locmiss = '0';
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
      const cid = parseInt(inp.dataset.id, 10);
      inp.classList.add('correct');
      inp.readOnly = true;
      revealGeometry(cid);
      if (a.rv) {
        inp.classList.add('revealed-loc');
        const rli = legendItems.get(cid);
        if (rli) rli.classList.add('revealed-loc');
        drawRevealArea(ALL_TERMS.find(t => t.id === cid));
      }
    }
    if (a.m && a.m > 0) {
      inp.dataset.miss = String(a.m);
      badge.textContent = a.m;
      badge.style.display = 'block';
    }
    if (a.lm) inp.dataset.locmiss = String(a.lm);
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
      qp.wrong = a.qw ? a.qw.slice() : new Array(qp.solved.length).fill(false);
      qp.bonus = !!a.bn;
      qp.bonusWrong = !!a.bw;
    }
  }
  // Restore legend "placed" strikethrough for correctly drag-placed items
  for (const [id, li] of legendItems) {
    const a = answers[id];
    li.classList.toggle('placed', !!(a && a.dp && a.c));
  }
  refreshAllLegendMarks();
  recountAnswers();
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
  recountAnswers();
  refreshAllLegendMarks();
  resetAnalysis();
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
  for (const el of document.querySelectorAll('svg .revealed')) el.classList.remove('revealed');
  for (const el of document.querySelectorAll('svg .reveal-area')) el.remove();
}

// Draw the accept-area outline (circle / rectangle / polygon) so a revealed term
// shows roughly WHERE it is, even when it has no drawn line geometry.
function lonLatToBase(lon, lat) { return [(lon - PROJ_LON0) * PROJ_SX, (PROJ_LAT1 - lat) * PROJ_SY]; }
function svgEl(tag) { return document.createElementNS('http://www.w3.org/2000/svg', tag); }
function drawRevealArea(term) {
  const svg = document.querySelector('#stage svg');
  if (!svg || !term || !term.accept) return;
  for (const el of svg.querySelectorAll('.reveal-area[data-term="' + term.id + '"]')) el.remove();
  const acc = term.accept;
  const pts = a => a.map(p => lonLatToBase(p[0], p[1]).map(v => v.toFixed(1)).join(',')).join(' ');
  let shape = null;
  if (acc.polygon) {
    shape = svgEl('polygon'); shape.setAttribute('points', pts(acc.polygon));
  } else if (acc.bbox) {
    const [lo0, la0, lo1, la1] = acc.bbox;
    shape = svgEl('polygon'); shape.setAttribute('points', pts([[lo0, la1], [lo1, la1], [lo1, la0], [lo0, la0]]));
  } else if (acc.radius_deg != null && term.label_at) {
    const [cx, cy] = lonLatToBase(term.label_at[0], term.label_at[1]);
    shape = svgEl('circle');
    shape.setAttribute('cx', cx.toFixed(1)); shape.setAttribute('cy', cy.toFixed(1));
    shape.setAttribute('r', (acc.radius_deg * PROJ_SX).toFixed(1));
  } else {
    return;   // buffer_deg terms already show their polyline geometry
  }
  shape.setAttribute('class', 'reveal-area');
  shape.setAttribute('data-term', term.id);
  svg.appendChild(shape);
}

// After MAX_LOC_ATTEMPTS wrong drops, reveal & lock the term at its correct spot.
function revealLocation(canonId) {
  const inp = inputsById.get(canonId);
  if (!inp || inp.classList.contains('correct')) return;
  const cell = inp.parentElement;
  inp.classList.remove('wrong-placed');
  inp.classList.add('correct', 'revealed-loc');
  inp.readOnly = true;
  inp.value = inp.dataset.correct;
  cell.classList.add('drag-placed');
  cell.dataset.sx = cell.dataset.canonSx;
  cell.dataset.sy = cell.dataset.canonSy;
  const li = legendItems.get(canonId);
  if (li) { li.classList.add('placed'); li.classList.add('revealed-loc'); }
  const term = ALL_TERMS.find(t => t.id === canonId);
  revealGeometry(canonId);
  drawRevealArea(term);
  showMsg(MSG_REVEALED, false);
  updateLegendMarks(canonId);
  showPanelFor(canonId);
  apply();
  recountCorrectMiss();
  saveState();
  maybeAutoAnalyze();
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
  markQuizStarted();   // first placed term locks the borders toggle
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
    updateLegendMarks(canonicalId);
    showPanelFor(canonicalId);
    maybeAutoAnalyze();
  } else {
    inp.classList.add('wrong-placed');
    const m = (parseInt(inp.dataset.miss, 10) || 0) + 1;
    inp.dataset.miss = m;
    const lm = (parseInt(inp.dataset.locmiss, 10) || 0) + 1;   // location-only mistakes
    inp.dataset.locmiss = lm;
    const badge = cell.querySelector('.miss');
    badge.textContent = m;
    badge.style.display = 'block';
    if (lm >= MAX_LOC_ATTEMPTS) { revealLocation(canonicalId); return; }  // give up → reveal
    showMsg(MSG_WRONG, false);
    maybeHintPanel(canonicalId);
  }
  apply();
  recountCorrectMiss();
  saveState();
}

// pointerdown on a legend item starts drag
legendList.addEventListener('pointerdown', e => {
  if (document.body.classList.contains('mobile')) return;   // mobile uses tap (click) handler
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
  if (document.body.classList.contains('mobile')) return;   // mobile re-places via tap + Potvrdi
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
  // Full reset: setMode() with no restore opts picks a fresh subset (for N-mode)
  // AND clears the board (applyAnswers({}) → cells, drawings, answers all reset).
  mAttemptId = null; mobileHeld = null;
  bordersLocked = false; updateBordersUI();   // back to start → borders editable again
  setMode(currentMode, {});
  apply();   // re-render cleared cell positions
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
  // On mobile the map fills the whole screen (wrap is full-height), so fit to the
  // actual wrap height — the entire map is visible at minimum zoom.
  const availH = MOBILE() ? wrap.clientHeight : Math.max(240, window.innerHeight - top - 14);
  baseFit = Math.min(availW / MW, availH / MH);
}
function clampPan() {
  // Viewport height = the real visible area: wrap height on mobile (full screen),
  // fitted map height on desktop. This lets panning reach all edges when zoomed.
  const vw = wrap.clientWidth, vh = MOBILE() ? wrap.clientHeight : baseFit * MH;
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
function fit() { computeFit(); if (!MOBILE()) wrap.style.height = (baseFit * MH) + 'px'; apply(); }
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
// Full-screen toggle (below the zoom buttons) + return to default
const zfull = document.getElementById('zfull');
function fsElement() { return document.fullscreenElement || document.webkitFullscreenElement || null; }
function toggleFullscreen() {
  const el = document.documentElement;
  if (!fsElement()) { const req = el.requestFullscreen || el.webkitRequestFullscreen; if (req) req.call(el); }
  else { const ex = document.exitFullscreen || document.webkitExitFullscreen; if (ex) ex.call(document); }
}
function updateFsBtn() {
  const on = !!fsElement();
  zfull.innerHTML = on ? '&#10006;' : '&#9974;';
  zfull.title = on ? 'Izađi iz celog ekrana' : 'Ceo ekran';
}
zfull.addEventListener('click', toggleFullscreen);
document.addEventListener('fullscreenchange', () => { setHeaderTop(); fit(); updateFsBtn(); });
document.addEventListener('webkitfullscreenchange', () => { setHeaderTop(); fit(); updateFsBtn(); });
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
  if (!block || block.classList.contains('solved') || block.classList.contains('answered-wrong')) return;
  const opts = DEMO_TERM.quiz.questions[qi].options;
  block.querySelectorAll('input[type=checkbox]').forEach(c => {
    const oi = parseInt(c.dataset.oi, 10);
    c.checked = correct ? !!opts[oi].c : !opts[oi].c;
  });
  const pv = block.querySelector('.q-proveri');
  if (pv) pv.click();
}
function demoBonus() {
  demoEnsureQuiz();
  const block = panelBody.querySelector('.bonus');
  if (!block) return;
  if (block.classList.contains('solved') || block.classList.contains('answered-wrong')) return;
  const opts = DEMO_TERM.quiz.bonus.options;
  block.querySelectorAll('input[type=checkbox]').forEach(c => {
    const oi = parseInt(c.dataset.oi, 10);
    c.checked = !!opts[oi].c;
  });
  const pv = block.querySelector('.q-proveri[data-bonus-btn]');
  if (pv) pv.click();
}

// Demonstrate the borders toggle (flash off → on) without locking it.
function demoFlashBorders() {
  bordersOn = false; updateBordersUI();
  setTimeout(() => { bordersOn = true; updateBordersUI(); }, 800);
}
// Demonstrate zoom: zoom in, then reset the view shortly after.
function demoZoomDemo() {
  centerZoom(1.7);
  setTimeout(() => { zoom = 1; panX = 0; panY = 0; fit(); }, 900);
}

// --- demo step script ---
const DEMO_STEPS = [
  // --- podešavanja pre početka ---
  { l: 'Granice', t: 'Pre početka možeš <b>uključiti/isključiti državne granice</b> ovim dugmetom. To je moguće samo na startu — čim postaviš prvi pojam, opcija se zaključava.', a: demoFlashBorders, at: 'borders' },
  { l: 'Broj pitanja', t: 'Ovde biraš obim vežbe: <b>svih 42</b> pojma, ili <b>nasumično 20 / 10 / 5</b>.', a: null, at: 'modesel' },
  { l: 'Zumiranje', t: 'Mapu zumiraš dugmadima <b>+ / −</b>, a <b>⟳</b> vraća prikaz. Mapa može i da se prevlači.', a: demoZoomDemo, at: 'zoom' },
  { l: 'Ceo ekran', t: 'Dugme <b>⛶</b> otvara mapu preko celog ekrana; istim dugmetom se vraćaš nazad.', a: null, at: 'full' },
  // --- mod Učenje ---
  { l: 'Učenje', t: 'Prevlačim pojam <b>Srbija</b> na pogrešno mesto — broj <b>0</b> pada tu (crveno). Greška se broji i otvara prvi <b>hint</b>.', a: () => demoDropWrongAt(MW * 0.20, MH * 0.28), at: 'map' },
  { l: 'Hintovi', t: 'Spuštam <b>0</b> na drugo pogrešno mesto — otkriva se sledeći, konkretniji hint. (Posle 10 pokušaja mesto se samo otkriva.)', a: () => demoDropWrongAt(MW * 0.31, MH * 0.56), at: 'map' },
  { l: 'Tačno', t: 'Sad <b>0</b> ide na tačno mesto — iscrta se baš taj pojam, a u panelu se prikaže <b>pun opis</b>. Dugme <b>Opis</b> ga kasnije ponovo otvara.', a: demoDropCorrect, at: 'desc' },
  { l: 'Test mod', t: 'Prelazim u <b>Test</b> mod. Ovde nema hintova ni opisa — posle tačnog lociranja dobijaš pitanja.', a: demoEnterTest, at: 'mode' },
  { l: 'Test: greška 1', t: 'I u testu pogrešno lociranje broji grešku — <b>0</b> na prvo pogrešno mesto.', a: () => demoDropWrongAt(MW * 0.22, MH * 0.30), at: 'map' },
  { l: 'Test: greška 2', t: '...pa <b>0</b> na drugo pogrešno mesto.', a: () => demoDropWrongAt(MW * 0.33, MH * 0.58), at: 'map' },
  { l: 'Test: tačno', t: 'Pa <b>0</b> na tačno mesto — otvaraju se tri pitanja.', a: demoDropCorrect, at: 'map' },
  { l: 'Pitanje 1', t: 'Prvo pitanje odgovaram tačno.', a: () => demoAnswerQuestion(0, true), at: 'panel' },
  { l: 'Pitanje 2', t: 'Drugo pitanje namerno pogrešim — pitanje se <b>zaključa</b>: pogrešan odgovor pocrveni, a tačni se označe zeleno. Ispravka nije moguća; broji se greška.', a: () => demoAnswerQuestion(1, false), at: 'panel' },
  { l: 'Pitanje 3', t: 'Treće pitanje odgovaram tačno. Sva tri su odgovorena — otključava se <b>bonus</b>.', a: () => demoAnswerQuestion(2, true), at: 'panel' },
  { l: 'Bonus', t: 'Za bonus treba pregledati <b>sve izvore</b> iz kojih je nastao opis. Odgovaram tačno.', a: demoBonus, at: 'panel' },
  // --- alati posle kviza ---
  { l: 'Analiza', t: 'Ispod mape je <b>Analiza znanja</b>: nastavnik unese svoj Claude API ključ i dobije kratak osvrt — gde je učenik dobar, a gde treba da vežba. Ključ ostaje samo u pregledaču, nikad u kodu.', a: null, at: 'analysis' },
  { l: 'Rezultati', t: 'Po završetku se pojavi dugme <b>Preuzmi rezultate (CSV)</b>. A <b>Počni ispočetka</b> briše sve i kreće iz početka.', a: null, at: 'reset' },
  { l: 'Kraj', t: 'To je ceo tok — podešavanja, učenje, test, bonus i analiza. Srbija sada nestaje sa spiska. Srećno!', a: null, at: 'mode' },
];

function demoPositionBubble(at) {
  // The bubble has a fixed size/position via CSS (bottom-left, over the legend),
  // so the "Dalje" button stays in the exact same spot on every step.
  // Here we only move the animated pointer to the relevant control.
  if (at === 'mode') {
    demoCursorToEl(modeTest);
  } else if (at === 'panel') {
    const visible = [...panelBody.querySelectorAll('.q-proveri')]
      .find(b => b.offsetParent !== null);
    if (visible) demoCursorToEl(visible);
  } else if (at === 'borders') {
    demoCursorToEl(bordersBtn);
  } else if (at === 'modesel') {
    const el = document.querySelector('.mode-selector');
    if (el) demoCursorToEl(el);
  } else if (at === 'zoom') {
    demoCursorToEl(document.getElementById('zin'));
  } else if (at === 'full') {
    demoCursorToEl(document.getElementById('zfull'));
  } else if (at === 'desc') {
    demoCursorToEl(descBtn);
  } else if (at === 'reset') {
    demoCursorToEl(resetBtn);
  } else if (at === 'analysis') {
    const el = document.getElementById('analysis');
    if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'center' }); setTimeout(() => demoCursorToEl(el), 350); }
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
    '<div class="demo-text">' + step.t + '</div>' +
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
  bordersOn = true; bordersLocked = false; updateBordersUI();   // back to default after the demo
  closePanel();
  hideDemoTerm();
  saveState();
}

// --- performance analysis (optional, uses the teacher's own Claude API key) ---
const ANALYSIS_KEY_LS = 'classroom-claude-key';      // teacher's key, local only — never in code
const ANALYSIS_MODEL = 'claude-3-5-haiku-latest';    // editable if the model name changes
const ANALYSIS_LOADING = __ANALYSIS_LOADING__;
const ANALYSIS_NO_KEY = __ANALYSIS_NO_KEY__;
const ANALYSIS_ERROR = __ANALYSIS_ERROR__;
const ANALYSIS_EMPTY = __ANALYSIS_EMPTY__;
const ANALYSIS_SYS = 'Ti si iskusan i ohrabrujući nastavnik geografije. Pišeš kratku, konkretnu analizu učinka učenika na srpskom (latinica).';
const ANALYSIS_USER = 'Na osnovu sledećih podataka o učinku na geografskom kvizu napiši analizu. ' +
  'Skala: >=80% tačno = dobar; 50-80% = ima prostora za napredak; <50% = slab (treba se više potruditi). ' +
  'Pokrij u 3-5 kratkih pasusa: ukupan utisak; u čemu je učenik dobar; gde ima prostora za napredak; gde je slab i treba se potruditi. ' +
  'Budi konkretan: pomeni vrste pojmova (mora, planine, reke...) i težine pitanja, i RAZLIKUJ greške u lociranju na mapi od grešaka u odgovorima na pitanja. ' +
  'Uzmi u obzir i BROJ POKUŠAJA lociranja: greske_lociranja po pojmu i lokPokusaji ukupno (manje je bolje). ' +
  'Pojmovi sa otkriven:true znače da učenik nije uspeo da ih locira ni iz 10 pokušaja pa mu je lokacija otkrivena — to su izrazito slabe tačke. ' +
  'Bez markdown naslova. Podaci (JSON):\n';

const analysisEl = document.getElementById('analysis');
const analysisRun = document.getElementById('analysisRun');
const analysisBody = document.getElementById('analysisBody');
const analysisKeyToggle = document.getElementById('analysisKeyToggle');
const analysisKeyRow = document.getElementById('analysisKeyRow');
const analysisKey = document.getElementById('analysisKey');
const analysisKeySave = document.getElementById('analysisKeySave');
const analysisKeyClear = document.getElementById('analysisKeyClear');
const ANALYSIS_IDLE_HTML = analysisBody.innerHTML;   // keep the idle placeholder
let analysisRunning = false, analysisDone = false;

function buildAnalysisData() {
  const byTezina = {}, byVrsta = {};
  const faza = { lokUkupno: 0, lokPostavljeno: 0, lokIzPrve: 0, lokOtkriveno: 0, lokPokusaji: 0,
                 pitUkupno: 0, pitTacno: 0, pitPogresno: 0, pitNereseno: 0,
                 bonusUkupno: 0, bonusTacno: 0, bonusPogresno: 0, bonusNereseno: 0 };
  const pojmovi = [];
  for (const id of countedIds()) {
    const t = ALL_TERMS.find(x => x.id === id);
    if (!t || !t.quiz) continue;
    const inp = inputsById.get(id);
    const located = !!(inp && inp.classList.contains('correct'));
    const locmiss = inp ? (parseInt(inp.dataset.locmiss, 10) || 0) : 0;
    const locFirst = located && locmiss === 0;
    const otkriven = !!(inp && inp.classList.contains('revealed-loc'));
    const vr = (t.desc && t.desc.vrsta) ? t.desc.vrsta.replace(/_/g, ' ') : 'ostalo';
    const p = quizProgress.get(id) || { solved: [], wrong: [], bonus: false, bonusWrong: false };
    faza.lokUkupno++; faza.lokPokusaji += locmiss;
    if (located) { faza.lokPostavljeno++; if (locFirst) faza.lokIzPrve++; }
    if (otkriven) faza.lokOtkriveno++;
    byVrsta[vr] = byVrsta[vr] || { lokUkupno: 0, lokIzPrve: 0, pitUkupno: 0, pitTacno: 0, pitPogresno: 0, pitNereseno: 0 };
    byVrsta[vr].lokUkupno++; if (locFirst) byVrsta[vr].lokIzPrve++;
    const qd = [];
    t.quiz.questions.forEach((q, i) => {
      const solved = !!(p.solved && p.solved[i]);
      const wrong = !!(p.wrong && p.wrong[i]);
      const status = solved ? 'tacno' : (wrong ? 'pogresno' : 'nereseno');
      const tz = q.tezina || 'nepoznato';
      byTezina[tz] = byTezina[tz] || { ukupno: 0, tacno: 0, pogresno: 0, nereseno: 0 };
      byTezina[tz].ukupno++; byTezina[tz][status]++;
      faza.pitUkupno++;
      if (status === 'tacno') faza.pitTacno++; else if (status === 'pogresno') faza.pitPogresno++; else faza.pitNereseno++;
      byVrsta[vr].pitUkupno++;
      if (status === 'tacno') byVrsta[vr].pitTacno++; else if (status === 'pogresno') byVrsta[vr].pitPogresno++; else byVrsta[vr].pitNereseno++;
      qd.push({ tezina: tz, status: status });
    });
    let bonus = null;
    if (t.quiz.bonus) {
      bonus = p.bonus ? 'tacno' : (p.bonusWrong ? 'pogresno' : 'nereseno');
      faza.bonusUkupno++;
      if (p.bonus) faza.bonusTacno++; else if (p.bonusWrong) faza.bonusPogresno++; else faza.bonusNereseno++;
    }
    pojmovi.push({ naziv: t.name, vrsta: vr, lociran: located, otkriven: otkriven, greske_lociranja: locmiss, pitanja: qd, bonus: bonus });
  }
  return { faza: faza, po_tezini: byTezina, po_vrsti: byVrsta, pojmovi: pojmovi };
}

function analysisTextToHTML(text) {
  return esc(text).split(/\n\n+/).filter(s => s.trim()).map(s => '<p>' + s.replace(/\n/g, '<br>') + '</p>').join('');
}

async function callClaudeAnalysis(apiKey, data) {
  const resp = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-api-key': apiKey,
      'anthropic-version': '2023-06-01',
      'anthropic-dangerous-direct-browser-access': 'true'
    },
    body: JSON.stringify({
      model: ANALYSIS_MODEL,
      max_tokens: 1000,
      system: ANALYSIS_SYS,
      messages: [{ role: 'user', content: ANALYSIS_USER + JSON.stringify(data) }]
    })
  });
  if (!resp.ok) {
    let detail = '';
    try { detail = (await resp.text()).slice(0, 300); } catch (e) {}
    throw new Error('HTTP ' + resp.status + ' ' + detail);
  }
  const j = await resp.json();
  return (j.content && j.content[0] && j.content[0].text) ? j.content[0].text : '';
}

async function runAnalysis() {
  if (analysisRunning) return;
  const key = (localStorage.getItem(ANALYSIS_KEY_LS) || '').trim();
  if (!key) {
    analysisKeyRow.hidden = false;
    analysisKey.value = '';
    analysisBody.innerHTML = '<p class="placeholder">' + ANALYSIS_NO_KEY + '</p>';
    return;
  }
  const data = buildAnalysisData();
  if (!data.pojmovi.length || (data.faza.lokPostavljeno === 0 && data.faza.pitTacno === 0 && data.faza.pitPogresno === 0)) {
    analysisBody.innerHTML = '<p class="placeholder">' + ANALYSIS_EMPTY + '</p>';
    return;
  }
  analysisRunning = true;
  analysisBody.innerHTML = '<p class="loading">' + ANALYSIS_LOADING + '</p>';
  try {
    const text = await callClaudeAnalysis(key, data);
    analysisBody.innerHTML = analysisTextToHTML(text) || ('<p class="placeholder">' + ANALYSIS_EMPTY + '</p>');
    analysisDone = true;
  } catch (e) {
    analysisBody.innerHTML = '<p class="err">' + ANALYSIS_ERROR + ' ' + esc(String((e && e.message) || e)) + '</p>';
  } finally {
    analysisRunning = false;
  }
}

function maybeAutoAnalyze() {
  if (MOBILE()) return;   // mobile analysis is phase 2
  if (!isTestMode() || analysisDone || analysisRunning) return;
  const f = buildAnalysisData().faza;
  const complete = f.lokUkupno > 0 && f.lokPostavljeno === f.lokUkupno &&
                   f.pitUkupno > 0 && (f.pitTacno + f.pitPogresno) === f.pitUkupno;
  if (complete) runAnalysis();
}

function resetAnalysis() {
  analysisDone = false;
  if (!analysisRunning) analysisBody.innerHTML = ANALYSIS_IDLE_HTML;
}

analysisRun.addEventListener('click', runAnalysis);
analysisKeyToggle.addEventListener('click', () => {
  analysisKeyRow.hidden = !analysisKeyRow.hidden;
  if (!analysisKeyRow.hidden) analysisKey.value = localStorage.getItem(ANALYSIS_KEY_LS) || '';
});
analysisKeySave.addEventListener('click', () => {
  try { localStorage.setItem(ANALYSIS_KEY_LS, analysisKey.value.trim()); } catch (e) {}
  analysisKeyRow.hidden = true;
  runAnalysis();
});
analysisKeyClear.addEventListener('click', () => {
  try { localStorage.removeItem(ANALYSIS_KEY_LS); } catch (e) {}
  analysisKey.value = '';
});

// --- title/description modal ---
const descModal = document.getElementById('descModal');
const descBtn = document.getElementById('descBtn');
const DESC_KEY = 'classroom-desc:' + window.location.pathname;
function showDescModal() { descModal.hidden = false; }
function hideDescModal() {
  descModal.hidden = true;
  try { localStorage.setItem(DESC_KEY, '1'); } catch (e) {}
}
descBtn.addEventListener('click', showDescModal);
document.getElementById('descClose').addEventListener('click', hideDescModal);
document.getElementById('descOk').addEventListener('click', hideDescModal);
descModal.addEventListener('click', e => { if (e.target === descModal) hideDescModal(); });

// --- mobile mode (screen-at-a-time flow: list -> map -> result) ---
function MOBILE() { return document.body.classList.contains('mobile'); }
const mobileBack = document.getElementById('mobileBack');
const mTermLabel = document.getElementById('mTermLabel');
function mSetTermLabel(id) { const t = ALL_TERMS.find(x => x.id === id); mTermLabel.textContent = t ? t.name : ''; }
const mobileMenuBtn = document.getElementById('mobileMenuBtn');
const mobileMenu = document.getElementById('mobileMenu');
const mPotvrdi = document.getElementById('mPotvrdi');
const mNext = document.getElementById('mNext');
const mobileHintEl = document.getElementById('mobileHint');
const mobileModeSel = document.getElementById('mobileMode');
let mobileHeld = null;     // canonical id of the term "in hand"
let mProvisional = null;   // { baseX, baseY, lon, lat }
const M_CONFIRM_TXT = __M_CONFIRM_TXT__, M_NEXT_DESC = __M_NEXT_DESC__, M_NEXT_Q = __M_NEXT_Q__;
let mAwaitNext = false;    // placed correctly → button becomes "Dalje" (don't jump to result yet)
let mAttemptId = null;     // term taken from the list; its result is committed only after
                          // the full cycle (place → read description → "Sledeći pojam").
                          // Leaving via the back arrow before that reverts it entirely.

// Undo any drawn geometry / reveal-area for a single term.
function hideGeometry(canonId) {
  for (const el of document.querySelectorAll('svg [data-term="' + canonId + '"]')) el.classList.remove('revealed');
  for (const el of document.querySelectorAll('svg .reveal-area[data-term="' + canonId + '"]')) el.remove();
}

// Fully revert a term to its pristine (untouched) state — used when the student
// goes back to the list without finishing the read-description cycle, so neither
// a correct result, a placement, nor accumulated mistakes are committed.
function mAbandonAttempt(id) {
  const inp = inputsById.get(id);
  if (!inp) return;
  const cell = inp.parentElement;
  inp.classList.remove('correct', 'wrong-placed', 'wrong', 'revealed-loc');
  inp.readOnly = false;
  inp.value = '';
  inp.dataset.miss = '0';
  inp.dataset.locmiss = '0';
  cell.classList.remove('drag-placed', 'm-provisional', 'dragging');
  cell.dataset.sx = cell.dataset.canonSx;
  cell.dataset.sy = cell.dataset.canonSy;
  const badge = cell.querySelector('.miss');
  if (badge) { badge.textContent = '0'; badge.style.display = 'none'; }
  const li = legendItems.get(id);
  if (li) li.classList.remove('placed', 'revealed-loc');
  hideGeometry(id);
  updateLegendMarks(id);
  apply();
  recountCorrectMiss();
  saveState();
}

function mShowHint(canonId) {
  const t = ALL_TERMS.find(x => x.id === canonId);
  const hints = (t && t.desc && t.desc.hints) ? t.desc.hints : [];
  const inp = inputsById.get(canonId);
  const miss = inp ? (parseInt(inp.dataset.locmiss, 10) || 0) : 0;
  const shown = hints.slice(0, Math.min(miss, hints.length));
  if (!shown.length) { mHideHint(); return; }
  mobileHintEl.innerHTML = '<button class="m-hint-min" title="Smanji" aria-label="Smanji">&#9662;</button>' +
    '<h4>' + PANEL_HINT_HEADING + '</h4><ol>' +
    shown.map(h => '<li>' + h + '</li>').join('') + '</ol>';
  document.body.classList.add('m-hint-on');
  document.body.classList.remove('m-hint-min');   // a fresh hint pops the sheet back open
}
function mHideHint() { document.body.classList.remove('m-hint-on', 'm-hint-min'); }

function mGoto(screen) {
  document.body.classList.remove('m-list', 'm-map', 'm-result');
  document.body.classList.add('m-' + screen);
  mHideHint();
  if (screen !== 'map') { mProvisional = null; mAwaitNext = false; mPotvrdi.disabled = true; mPotvrdi.textContent = M_CONFIRM_TXT; mTermLabel.textContent = ''; }
  else { fit(); }   // map just became visible — measure it and fit the whole map
  mCloseMenu();
  window.scrollTo(0, 0);
}

function mTapPlace(clientX, clientY) {
  if (mobileHeld == null) return;
  const r = wrap.getBoundingClientRect();
  if (clientX < r.left || clientX > r.right || clientY < r.top || clientY > r.bottom) return;
  const sc = baseFit * zoom;
  const baseX = (clientX - r.left - panX) / sc, baseY = (clientY - r.top - panY) / sc;
  const [lon, lat] = screenToLonLat(clientX, clientY);
  mProvisional = { baseX, baseY, lon, lat };
  const cell = inputsById.get(mobileHeld).parentElement;
  const inp = cell.querySelector('.ans');
  inp.classList.remove('wrong-placed');
  cell.classList.remove('drag-placed');
  cell.classList.add('m-provisional');
  cell.dataset.sx = String(baseX); cell.dataset.sy = String(baseY);
  inp.value = inp.dataset.correct;
  apply();
  mPotvrdi.disabled = false;
  mHideHint();
}

function mConfirm() {
  if (mobileHeld == null || !mProvisional) return;
  const id = mobileHeld;
  const term = ALL_TERMS.find(t => t.id === id);
  inputsById.get(id).parentElement.classList.remove('m-provisional');
  const accepted = isDropAcceptable(term, mProvisional.lon, mProvisional.lat);
  // The button update runs in `finally` so a hiccup inside applyDrop can never
  // leave the button stuck on "Potvrdi" after a correct placement.
  try {
    applyDrop(id, accepted, mProvisional.baseX, mProvisional.baseY);
  } finally {
    mProvisional = null;
    if (inputsById.get(id).classList.contains('correct')) {
      // Correct (or revealed after 10 tries): stay on the map; the Potvrdi button
      // becomes "Dalje na opis/pitanja" — the user reviews the map, then continues.
      mobileHeld = null;
      mAwaitNext = true;
      mPotvrdi.disabled = false;
      mPotvrdi.textContent = isTestMode() ? M_NEXT_Q : M_NEXT_DESC;
    } else {
      mPotvrdi.disabled = true;   // wrong → re-tap the map to try again
    }
  }
}

function mBack() {
  // Leaving the map before the cycle is complete = abandon: revert the whole
  // attempt (correct/wrong/misses/geometry) so the counter never keeps a result
  // for a term the student didn't finish. A committed correct answer is reached
  // only through "Dalje" → description, where mAttemptId was already cleared.
  if (document.body.classList.contains('m-map') && mAttemptId != null) {
    mAbandonAttempt(mAttemptId);
  }
  mAttemptId = null;
  mobileHeld = null;
  mGoto('list');
}

function mCloseMenu() { mobileMenu.classList.remove('open'); }

// list tap → take the term (or open a placed term's result)
legendList.addEventListener('click', e => {
  if (!MOBILE()) return;
  const li = e.target.closest('li');
  if (!li || li.dataset.demo || li.classList.contains('hidden')) return;
  const id = parseInt(li.dataset.id, 10);
  const inp = inputsById.get(id);
  if (inp && inp.classList.contains('correct')) { mobileHeld = null; showPanelFor(id); mGoto('result'); return; }
  mobileHeld = id; mAttemptId = id; mProvisional = null; mAwaitNext = false;
  mPotvrdi.disabled = true; mPotvrdi.textContent = M_CONFIRM_TXT;
  mGoto('map');
  mSetTermLabel(id);
});

// map tap (no pan) → set provisional pin
let mTapStart = null;
wrap.addEventListener('pointerdown', e => {
  if (MOBILE() && mobileHeld != null && !e.target.closest('.zoombar')) mTapStart = { x: e.clientX, y: e.clientY };
});
wrap.addEventListener('pointerup', e => {
  if (mTapStart) {
    if (Math.hypot(e.clientX - mTapStart.x, e.clientY - mTapStart.y) < 8) mTapPlace(e.clientX, e.clientY);
    mTapStart = null;
  }
});

mPotvrdi.addEventListener('click', () => {
  if (mAwaitNext) { mAwaitNext = false; mAttemptId = null; mPotvrdi.textContent = M_CONFIRM_TXT; mPotvrdi.disabled = true; mGoto('result'); }
  else mConfirm();
});
mNext.addEventListener('click', () => mGoto('list'));
mobileBack.addEventListener('click', mBack);
mobileHintEl.addEventListener('click', e => { if (e.target.closest('.m-hint-min')) document.body.classList.add('m-hint-min'); });
document.getElementById('hintRestore').addEventListener('click', () => document.body.classList.remove('m-hint-min'));
mobileMenuBtn.addEventListener('click', e => { e.stopPropagation(); mobileMenu.classList.toggle('open'); });
document.addEventListener('click', e => { if (!mobileMenu.contains(e.target) && e.target !== mobileMenuBtn) mCloseMenu(); });
document.getElementById('mMenuOpis').addEventListener('click', () => { mCloseMenu(); showDescModal(); });
document.getElementById('mMenuReset').addEventListener('click', () => { mCloseMenu(); resetBtn.click(); mGoto('list'); });
mobileModeSel.addEventListener('change', () => { modeSelect.value = mobileModeSel.value; modeSelect.dispatchEvent(new Event('change')); mGoto('list'); });

// Mobile = phone in either orientation. Portrait uses the proven (max-width:760px)
// query; landscape adds a short-and-touch query so a phone stays mobile when rotated.
// Tablets (height > 480 in landscape) and desktops (no coarse pointer) stay desktop.
function isMobileViewport() {
  if (!window.matchMedia) return false;
  return window.matchMedia('(max-width:760px)').matches ||
         window.matchMedia('(max-height:480px) and (orientation:landscape) and (pointer:coarse)').matches;
}
function applyMobileMode() {
  const on = isMobileViewport();
  document.body.classList.toggle('mobile', on);
  if (on) {
    if (!document.body.classList.contains('m-map') && !document.body.classList.contains('m-result'))
      document.body.classList.add('m-list');
  } else {
    document.body.classList.remove('m-list', 'm-map', 'm-result', 'm-hint-on');
  }
}

// --- init ---
function setHeaderTop() {
  const h = document.querySelector('header').offsetHeight;
  document.documentElement.style.setProperty('--htop', h + 'px');
}

setSelectOptions();

// --- borders toggle (default ON; changeable only before the first term) ---
const BORDERS_ON_TXT = __BORDERS_ON_TXT__, BORDERS_OFF_TXT = __BORDERS_OFF_TXT__;
const bordersBtn = document.getElementById('bordersBtn');
const mMenuBorders = document.getElementById('mMenuBorders');
let bordersOn = true;
let bordersLocked = false;
function updateBordersUI() {
  document.body.classList.toggle('show-borders', bordersOn);
  const lbl = bordersOn ? BORDERS_ON_TXT : BORDERS_OFF_TXT;
  for (const b of [bordersBtn, mMenuBorders]) {
    if (!b) continue;
    b.textContent = lbl;
    b.disabled = bordersLocked;
    b.classList.toggle('borders-off', !bordersOn);
  }
}
function toggleBorders() { if (bordersLocked) return; bordersOn = !bordersOn; updateBordersUI(); saveState(); }
function lockBorders() { if (!bordersLocked) { bordersLocked = true; updateBordersUI(); } }
function markQuizStarted() { if (!document.body.classList.contains('demo-running')) lockBorders(); }
bordersBtn.addEventListener('click', toggleBorders);
mMenuBorders.addEventListener('click', () => { toggleBorders(); mCloseMenu(); });

// Restore state if present
const saved = loadState();
if (saved) {
  bordersOn = saved.borders !== false;
  const demoKey = DEMO_TERM ? String(DEMO_TERM.id) : null;
  bordersLocked = Object.entries(saved.answers || {})
    .some(([k, a]) => k !== demoKey && a && (a.c || (a.m && a.m > 0) || a.dp));
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
updateBordersUI();
recountBonus();
recountAnswers();
refreshAllLegendMarks();
if (demoDone) hideDemoTerm();
closePanel();   // start with the idle placeholder in the always-present panel
try { if (localStorage.getItem(DESC_KEY) !== '1') showDescModal(); } catch (e) {}

window.addEventListener('resize', () => { setHeaderTop(); applyMobileMode(); fit(); });
window.addEventListener('orientationchange', () => setTimeout(() => { setHeaderTop(); applyMobileMode(); fit(); }, 200));
setHeaderTop();
applyMobileMode();
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

    import hashlib as _hashlib
    import random as _random

    def _conv(q):
        opts = [
            {"t": o.get("tekst", ""), "c": bool(o.get("tacan"))}
            for o in (q.get("odgovori") or [])
        ]
        # Deterministic shuffle (seeded by the question text) so correct answers
        # are not clustered first, while the build stays reproducible.
        seed = int(_hashlib.md5((q.get("pitanje", "")).encode("utf-8")).hexdigest(), 16)
        _random.Random(seed).shuffle(opts)
        return {
            "tezina": q.get("tezina"),
            "pitanje": q.get("pitanje", ""),
            "options": opts,
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
            f'<input class="ans" data-id="{t["id"]}" data-correct="{t["id"]}" data-miss="0" data-locmiss="0" '
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
        "__LBL_ANSWERS__": ui["stat_answers"],
        "__LBL_MISS__": ui["stat_miss"],
        "__BTN_RESET__": ui["btn_reset"],
        "__BTN_BORDERS_ON__": ui["btn_borders_on"],
        "__BTN_BORDERS_OFF__": ui["btn_borders_off"],
        "__BTN_BORDERS_LOCKED_TITLE__": ui["btn_borders_locked_title"],
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
        "__BORDERS_ON_TXT__": _json.dumps(ui["btn_borders_on"]),
        "__BORDERS_OFF_TXT__": _json.dumps(ui["btn_borders_off"]),
        "__MSG_CORRECT__": _json.dumps(ui["msg_correct"]),
        "__MSG_WRONG__": _json.dumps(ui["msg_wrong"]),
        "__MSG_REVEALED__": _json.dumps(ui["msg_revealed"]),
        "__MSG_WIN__": _json.dumps(ui["msg_win"]),
        "__MODE_ALL_TPL__": _json.dumps(ui["mode_all"]),
        "__MODE_RANDOM_TPL__": _json.dumps(ui["mode_random"]),
        "__BTN_DESC__": _html.escape(ui["btn_desc"]),
        "__BTN_DESC_OK__": _html.escape(ui["btn_desc_ok"]),
        "__PANEL_CLOSE__": _html.escape(ui["panel_close"], quote=True),
        "__PANEL_PLACEHOLDER__": _json.dumps(ui["panel_placeholder"]),
        "__PANEL_IDLE__": _json.dumps(ui["panel_idle"]),
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
        "__Q_INCORRECT__": _json.dumps(ui["q_incorrect"]),
        "__BONUS_LABEL__": _json.dumps(ui["bonus_label"]),
        "__BONUS_LOCKED__": _json.dumps(ui["bonus_locked"]),
        "__BONUS_NOTE__": _json.dumps(ui["bonus_note"]),
        "__TEST_NO_Q__": _json.dumps(ui["test_no_questions"]),
        "__ANALYSIS_TITLE__": _html.escape(ui["analysis_title"]),
        "__ANALYSIS_RUN__": _html.escape(ui["analysis_run"]),
        "__ANALYSIS_KEY_LINK__": _html.escape(ui["analysis_key_link"]),
        "__ANALYSIS_KEY_LABEL__": _html.escape(ui["analysis_key_label"]),
        "__ANALYSIS_KEY_SAVE__": _html.escape(ui["analysis_key_save"]),
        "__ANALYSIS_KEY_CLEAR__": _html.escape(ui["analysis_key_clear"]),
        "__ANALYSIS_IDLE__": _html.escape(ui["analysis_idle"]),
        "__ANALYSIS_NOTE__": _html.escape(ui["analysis_note"]),
        "__ANALYSIS_LOADING__": _json.dumps(ui["analysis_loading"]),
        "__ANALYSIS_NO_KEY__": _json.dumps(ui["analysis_no_key"]),
        "__ANALYSIS_ERROR__": _json.dumps(ui["analysis_error"]),
        "__ANALYSIS_EMPTY__": _json.dumps(ui["analysis_empty"]),
        "__M_CONFIRM__": _html.escape(ui["m_confirm"]),
        "__M_NEXT__": _html.escape(ui["m_next"]),
        "__M_CONFIRM_TXT__": _json.dumps(ui["m_confirm"]),
        "__M_NEXT_DESC__": _json.dumps(ui["m_next_desc"]),
        "__M_NEXT_Q__": _json.dumps(ui["m_next_q"]),
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
