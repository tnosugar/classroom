#!/usr/bin/env python3
"""Regenerate top-level classroom/index.html from tools/*/*/spec.yaml files.

Run after adding a new tool, or whenever a tool's spec.yaml changes its title
or description. Idempotent — safe to run repeatedly.

Usage (from anywhere in the repo):
    python3 scripts/regenerate_index.py

What it does:
    1. Walks tools/{predmet}/{slug}/spec.yaml for every tool.
    2. Groups tools by predmet (the immediate parent folder of the tool).
    3. Writes classroom/index.html with a section per predmet listing all tools.
    4. Detects whether radna.pdf / resenja.pdf exist beside the tool's index.html;
       only emits PDF links if the files are there.

The generated file is fully self-contained HTML; no build, no JS framework.
"""
import html
import pathlib
import sys
import yaml


# Predmet ordering for the catalog. Predmeti not in this list appear after,
# alphabetically. Edit this list to change top-level catalog ordering.
PREDMET_ORDER = [
    "geografija",
    "biologija",
    "hemija",
    "fizika",
    "matematika",
    "istorija",
    "srpski",
    "strani-jezici",
    "umetnost",
    "muzicka-kultura",
    "informatika",
]

PREDMET_TITLES = {
    "geografija": "Geografija",
    "biologija": "Biologija",
    "hemija": "Hemija",
    "fizika": "Fizika",
    "matematika": "Matematika",
    "istorija": "Istorija",
    "srpski": "Srpski jezik",
    "strani-jezici": "Strani jezici",
    "umetnost": "Likovna kultura",
    "muzicka-kultura": "Muzička kultura",
    "informatika": "Informatika",
}


def find_repo_root(start):
    """Walk up from `start` until we find a folder containing shared/python/."""
    p = pathlib.Path(start).resolve()
    for parent in [p, *p.parents]:
        if (parent / "shared" / "python").is_dir():
            return parent
    raise SystemExit(f"Could not find classroom repo root from {start}")


def collect_tools(repo_root):
    """Return dict {predmet: [tool_info, ...]} sorted within each predmet by slug."""
    tools = {}
    tools_dir = repo_root / "tools"
    if not tools_dir.is_dir():
        return tools

    for spec_path in sorted(tools_dir.glob("*/*/spec.yaml")):
        slug = spec_path.parent.name
        predmet = spec_path.parent.parent.name
        try:
            with open(spec_path) as f:
                spec = yaml.safe_load(f) or {}
        except Exception as e:
            print(f"  WARNING: failed to read {spec_path}: {e}", file=sys.stderr)
            continue

        tool_folder = spec_path.parent
        info = {
            "slug": slug,
            "predmet": predmet,
            "title": spec.get("title") or spec.get("title_short") or slug,
            "description": (spec.get("description") or "").strip(),
            "rel_path": f"tools/{predmet}/{slug}/",
            "has_html": (tool_folder / "index.html").exists(),
            "has_radna_pdf": (tool_folder / "radna.pdf").exists(),
            "has_resenja_pdf": (tool_folder / "resenja.pdf").exists(),
        }
        tools.setdefault(predmet, []).append(info)

    for predmet in tools:
        tools[predmet].sort(key=lambda t: t["slug"])

    return tools


def ordered_predmeti(tools):
    """Return predmet keys in catalog order: PREDMET_ORDER first, then alphabetical."""
    known = [p for p in PREDMET_ORDER if p in tools]
    unknown = sorted([p for p in tools if p not in PREDMET_ORDER])
    return known + unknown


def render_tool_li(tool):
    title = html.escape(tool["title"])
    desc = html.escape(tool["description"])
    rel = tool["rel_path"]
    links = []
    if tool["has_html"]:
        links.append(f'<a href="{rel}">Interaktivni alat</a>')
    if tool["has_radna_pdf"]:
        links.append(f'<a href="{rel}radna.pdf">PDF (radna)</a>')
    if tool["has_resenja_pdf"]:
        links.append(f'<a href="{rel}resenja.pdf">PDF (rešenja)</a>')
    links_html = " · ".join(links) if links else '<span class="muted">(nema generisanih fajlova)</span>'

    desc_html = f'<p>{desc}</p>' if desc else ""
    primary_href = rel if tool["has_html"] else (rel + "radna.pdf" if tool["has_radna_pdf"] else rel)

    return (
        '<li class="tool">'
        f'<a class="title" href="{primary_href}">{title}</a>'
        f'{desc_html}'
        f'<span class="links">{links_html}</span>'
        '</li>'
    )


def render_section(predmet, predmet_title, tools_in_section):
    items = "\n  ".join(render_tool_li(t) for t in tools_in_section)
    return (
        f'<section class="subject">\n'
        f' <h2>{html.escape(predmet_title)}</h2>\n'
        f' <ul class="tools">\n  {items}\n </ul>\n'
        f'</section>'
    )


HEAD = """<!DOCTYPE html>
<html lang="sr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>classroom — interaktivni alati za nastavu</title>
<style>
 :root{--bg:#faf8f2;--surface:#fff;--ink:#2b2b2b;--muted:#6b6456;--edge:#b1271f;--accent:#1f7a3a;--border:#e6e0d2;}
 *{box-sizing:border-box}
 body{margin:0;font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif;color:var(--ink);background:var(--bg);line-height:1.5}
 .wrap{max-width:880px;margin:0 auto;padding:32px 22px 64px}
 header h1{font-size:28px;margin:0 0 8px;color:#3a3528}
 header p{margin:0 0 6px;color:var(--muted);max-width:680px}
 .meta{font-size:13px;color:var(--muted);margin-top:14px}
 .meta a{color:var(--edge);text-decoration:none}
 .meta a:hover{text-decoration:underline}
 main{margin-top:36px}
 section.subject{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:20px 22px;margin-bottom:18px}
 section.subject > h2{font-size:18px;margin:0 0 14px;color:var(--edge);border-bottom:1px solid var(--border);padding-bottom:8px}
 ul.tools{list-style:none;padding:0;margin:0;display:grid;grid-template-columns:1fr;gap:14px}
 @media (min-width:600px){ ul.tools{grid-template-columns:1fr 1fr;gap:18px} }
 li.tool{border:1px solid var(--border);border-radius:8px;padding:14px 16px;background:#fefcf7;transition:border-color .15s,background .15s}
 li.tool:hover{border-color:var(--accent);background:#fff}
 li.tool a.title{display:block;font-weight:700;font-size:15.5px;color:#3a3528;text-decoration:none;margin-bottom:6px}
 li.tool a.title:hover{color:var(--accent)}
 li.tool p{margin:0 0 8px;font-size:13.5px;color:var(--muted)}
 li.tool .links{font-size:12.5px;color:var(--muted)}
 li.tool .links a{color:var(--edge);text-decoration:none}
 li.tool .links a:hover{text-decoration:underline}
 .muted{color:var(--muted);font-style:italic}
 .empty{padding:20px 22px;background:var(--surface);border:1px dashed var(--border);border-radius:10px;color:var(--muted);text-align:center}
 footer{margin-top:48px;padding-top:18px;border-top:1px solid var(--border);font-size:12.5px;color:var(--muted);text-align:center}
 footer a{color:var(--edge);text-decoration:none}
</style>
</head>
<body>
<div class="wrap">

<header>
 <h1>classroom</h1>
 <p>Interaktivni alati za nastavu u osnovnoj školi, srednjoj školi i edukaciji odraslih. Svaki alat radi u browseru bez login-a i bez naloga. Mnogi imaju i verziju za štampu.</p>
 <p class="meta">Repo: <a href="https://github.com/tnosugar/classroom-private">github.com/tnosugar/classroom-private</a> · Generisano automatski pomoću scripts/regenerate_index.py</p>
</header>

<main>
"""

FOOT = """</main>

<footer>
 classroom · otvoreni alati za nastavu · <a href="https://github.com/tnosugar/classroom-private">izvorni kod</a>
</footer>

</div>
</body>
</html>
"""


def main():
    repo_root = find_repo_root(__file__)
    tools = collect_tools(repo_root)
    out_path = repo_root / "index.html"

    sections = []
    if not tools:
        sections.append(
            '<div class="empty">Još uvek nema alata. Dodaj prvi alat u <code>tools/{predmet}/{slug}/</code>.</div>'
        )
    else:
        for predmet in ordered_predmeti(tools):
            title = PREDMET_TITLES.get(predmet, predmet.title())
            sections.append(render_section(predmet, title, tools[predmet]))

    html_out = HEAD + "\n".join(sections) + "\n" + FOOT

    # Only write if content actually changed (helps git diff stay clean)
    if out_path.exists():
        existing = out_path.read_text(encoding="utf-8")
        if existing == html_out:
            print(f"index.html unchanged (no diff)")
            return

    out_path.write_text(html_out, encoding="utf-8")

    total_tools = sum(len(v) for v in tools.values())
    print(f"Wrote {out_path}")
    print(f"  {total_tools} tool(s) across {len(tools)} predmet(a):")
    for predmet in ordered_predmeti(tools):
        names = ", ".join(t["slug"] for t in tools[predmet])
        print(f"    {predmet}: {names}")


if __name__ == "__main__":
    main()
