# classroom — orientation for Claude sessions

This file tells future Claude sessions (Cowork, Code, or otherwise) how to work in this repository.

## What this repo is

A collection of self-contained interactive educational tools (HTML/JS) plus their generators (Python). Target audience: nastavnici osnovne škole, srednje škole, i edukacija odraslih. Working language is **Serbian** (Latin script, `locale: sr`). Source-of-truth files for tools are `spec.yaml` files; everything else (HTML, PDFs) is generated.

## Repository conventions

- **Folder naming:** kebab-case throughout (`tools/geografija/evropa-kviz/`, NOT `Geografija-Evropa-Kviz/` or `evropa_kviz`).
- **Tool grouping:** nested by subject — `tools/{predmet}/{tool-slug}/`. Examples of predmet: `geografija`, `biologija`, `matematika`, `istorija`, `hemija`, `fizika`, `srpski`, `strani-jezici`, `umetnost`.
- **Languages:** UI strings and content in Serbian. Code identifiers in English. Comments may be in either as appropriate.
- **Python:** Python 3.10+. Use stdlib + the small set listed in top-level README. Add a new dependency only with strong justification.
- **JavaScript:** vanilla JS, no build step, no npm. Tools must work as a single self-contained HTML file opened directly in a browser (file://) without a local server.

## Tool architecture

Every tool follows this contract:

```
tools/{predmet}/{tool-slug}/
├── spec.yaml         # all tool-specific data and UI strings (THE source of truth)
├── make.py           # 5-line orchestrator that imports from shared/python and writes outputs
├── index.html        # GENERATED, committed
├── radna.pdf         # GENERATED if applicable, committed
└── resenja.pdf       # GENERATED if applicable, committed
```

Tools of the same TYPE share render logic in `shared/python/{type}.py`. The pilot type is **labeled-location-quiz** (`shared/python/labeled_location_quiz.py`).

To create a new tool **of an existing type**: copy the corresponding template folder, edit `spec.yaml`, run `make.py`. Do not duplicate render logic.

To create a new tool of a **new type**: introduce a new `shared/python/{type}.py` module + a new `templates/{type}/` folder with `README.md`, `spec.template.yaml`, and `make.py`. The first instance of the new type may live alongside the template authorship to validate the abstraction.

## Workflow for a Claude session

Before authoring or editing:

1. **Audit first.** Read this CLAUDE.md, the top-level README, and (if relevant) the tool's own README/spec.yaml. Per the operator-workbench audit-before-author discipline.
2. **Socratic spec building.** The user prefers iterative two-way socratic dialog when developing software. Surface design decisions as discrete questions before writing code.
3. **Verify changes.** After modifying a generator or shared module, run `python3 make.py` in at least one affected tool folder and verify the output (sizes, sample HTML/PDF render). Do not commit without rebuild verification.
4. **One commit per coherent change.** Tool changes commit independently of shared module changes when feasible. Prefix tool commits with the tool path (`tools/geografija/evropa-kviz: …`).

## Common operations

**Add a new labeled-location-quiz** (most likely task at this stage of the project):

```bash
cp -r templates/labeled-location-quiz/ tools/{predmet}/{slug}/
cd tools/{predmet}/{slug}/
mv spec.template.yaml spec.yaml
# Edit spec.yaml
python3 make.py
git add tools/{predmet}/{slug}/
git commit -m "tools/{predmet}/{slug}: prva verzija"
```

**Modify render logic for all labeled-location-quiz tools at once:**

```bash
# Edit shared/python/labeled_location_quiz.py
# Rebuild every affected tool:
for d in tools/*/*/; do
  if [ -f "$d/make.py" ] && grep -q "labeled_location_quiz" "$d/make.py"; then
    (cd "$d" && python3 make.py)
  fi
done
git add -u
git commit -m "shared/python/labeled_location_quiz: <what changed>"
```

**Verify a tool's output matches expectation:**

```bash
cd tools/{predmet}/{slug}/
python3 make.py
# Open index.html in browser, check radna.pdf and resenja.pdf
```

## Known anti-patterns (don't do these)

- **Duplicate render logic per tool.** If you find yourself copy-pasting Python rendering from one tool to another, extract to `shared/python/` and update both tools to import it.
- **Hard-coded paths.** No absolute `/Users/...` or `/sessions/...` paths in any committed file. Use `pathlib.Path(__file__).parent` and walk up to find repo root if needed (see existing `make.py` for the pattern).
- **Commit without rebuild.** If you modify `spec.yaml` or a shared module, regenerate the affected `index.html` / PDFs before committing. CI does not exist here; the committed artifacts are the source of truth for what teachers see.
- **Server dependencies for browser tools.** All `index.html` files must work via `file://`. No `fetch()` of external resources; embed everything.

## Repo state at last audit (2026-05-31)

- One tool: `tools/geografija/evropa-kviz/` — 42 European geography terms, refactored from initial proof-of-concept into the labeled-location-quiz architecture.
- One template: `templates/labeled-location-quiz/`.
- One shared type: `shared/python/labeled_location_quiz.py` with these features in the rendered HTML:
  - localStorage state persistence (keyed by `window.location.pathname`)
  - Mode selector (all / 20 / 10 / 5 random)
  - CSV export of results (visible after completion)
  - `@media print` stylesheet for clean browser printing
  - All UI strings localized via `spec.ui` keys
- One regenerator: `scripts/regenerate_index.py` — rebuilds top-level `index.html` from `tools/*/*/spec.yaml`. Run after adding a tool or after a tool's title/description changes.
- Shared data: `shared/data/countries.geojson` (Natural Earth, ~3MB).
- GitHub Pages: planned (not yet enabled). When enabled, root `index.html` becomes the tool index.

## After adding a new tool, always:

```bash
# 1. Rebuild the new tool's outputs
cd tools/{predmet}/{slug}/ && python3 make.py

# 2. Regenerate top-level index so the new tool appears in the catalog
cd ../../.. && python3 scripts/regenerate_index.py

# 3. Commit both the tool folder and the regenerated index
git add tools/{predmet}/{slug}/ index.html
git commit -m "tools/{predmet}/{slug}: prva verzija"
```

## See also

- Top-level `README.md` — user-facing project intro.
- `templates/labeled-location-quiz/README.md` — how to create a new tool from the pilot template.
- `tools/geografija/evropa-kviz/spec.yaml` — example of a fully populated spec.
