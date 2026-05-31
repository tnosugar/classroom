# labeled-location-quiz (šablon)

Šablon za kviz tipa "obeleži lokaciju" — na karti (ili bilo kojoj slici) je N označenih lokacija; učenik upisuje broj pojma sa spiska u kvadrat na pravoj lokaciji. Sistem broji greške po polju i ukupno, pa traži ponovan unos dok ne bude tačno.

Prva instanca ovog šablona: `tools/geografija/evropa-kviz/`.

## Kako da napraviš novi kviz iz ovog šablona

1. Kopiraj ovaj folder na novu lokaciju ispod `tools/`:

   ```bash
   cp -r templates/labeled-location-quiz/ tools/{predmet}/{novi-kviz-slug}/
   cd tools/{predmet}/{novi-kviz-slug}/
   mv spec.template.yaml spec.yaml
   ```

2. Otvori `spec.yaml` i popuni podatke:

   - `title`, `title_short`, `locale`, `description` — metapodaci
   - `map.extent` — `[min_lon, max_lon]` × `[min_lat, max_lat]` geografski okvir
   - `map.mid_lat_for_aspect` — centralna latitude (koristi se za aspect ratio)
   - `map.geo_data` — relativna putanja do GeoJSON sa granicama država (za geografske kvizove obično `../../../shared/data/countries.geojson`)
   - `ui` — svi vidljivi tekstovi na lokalu (lako je posrbiti ili prevesti)
   - `terms` — niz pojmova, svaki sa `id`, `name`, `label_at: [lon, lat]`; opciono `geometry` (planinski venac, reka)

3. Rebuild:

   ```bash
   python3 make.py
   ```

   Generišu se tri fajla u istom folderu:
   - `index.html` — interaktivan kviz (otvara se duplim klikom u browseru, GitHub Pages servira)
   - `radna.pdf` — student-ova verzija za štampu (prazni krugovi)
   - `resenja.pdf` — verzija sa odgovorima (krugovi sa upisanim brojevima)

4. Regeneriši top-level katalog (`classroom/index.html`) tako da se novi alat pojavi:

   ```bash
   cd ../../..
   python3 scripts/regenerate_index.py
   ```

5. Commit:

   ```bash
   git add tools/{predmet}/{novi-kviz-slug}/ index.html
   git commit -m "tools/{predmet}/{novi-kviz-slug}: prva verzija"
   ```

## Šta dobiješ "iz kutije" (svaki kviz ovog tipa)

Render logika u `classroom/shared/python/labeled_location_quiz.py` produkuje HTML kviz sa sledećim feature-ima — sve aktivno bez ikakve konfiguracije u spec.yaml:

- **localStorage persistencija** — učenik može slučajno da osveži stranicu; svi odgovori i greške se sačuvaju i vrate sa žutim banerom "Nastavak prethodne sesije". Dugme "Počni ispočetka" briše sačuvano stanje.
- **Mod selektor** — header ima "Pitanja: Sve (N) / 20 nasumičnih / 10 nasumičnih / 5 nasumičnih". Default je "Sve". Promena moda nasumično bira podskup termina (algoritam: Fisher-Yates). Opcije sa N >= ukupnog broja termina se sakrivaju (npr. ako kviz ima 8 termina, opcija "10 nasumičnih" se ne prikazuje).
- **CSV export** — dugme "Preuzmi rezultate (CSV)" se pojavi po završetku; CSV format: `id, name, correct, miss_count`.
- **@media print** — Ctrl+P daje čistu print verziju direktno iz browser-a (bez kontrola, bez zoom-a, bez bojica). PDF generator ostaje opcionalan ako je potreban formalniji output.
- **Lokalizovani stringovi** — sav vidljiv tekst je u `spec.yaml.ui` sekciji. Za drugi jezik samo prepravi ui ključeve.

## Šta NE menjati

`make.py` je generički — koristi `classroom/shared/python/labeled_location_quiz.py`. Ne diraj ga osim ako menjaš tip alata. Sve specifičnosti idu u `spec.yaml`.

Ako želiš da promeniš render logiku za SVE kvizove ovog tipa (npr. dodaš tajmer, ili menjaš boje krugova), uredi `classroom/shared/python/labeled_location_quiz.py` — svi kvizovi ovog šablona dobijaju izmenu pri sledećem rebuild-u.

## Dijagnoze

| Problem | Verovatan uzrok |
|---|---|
| `Could not find classroom/shared/python/` | `make.py` se ne pokreće iz foldera unutar classroom repo-a. |
| `FileNotFoundError: countries.geojson` | `map.geo_data` putanja u `spec.yaml` ne pokazuje na pravo mesto (relativna od `spec.yaml`). |
| Krugovi/polja na pogrešnim lokacijama | `label_at` koordinate u `spec.yaml` su pogrešne. Otvoriti `radna.pdf` i vizuelno proveriti. |
| HTML otvara prazno | Browser blokira fetch lokalnog fajla. Otvoriti direktno fajl (file://), ne kroz lokalni server. |

## Vidi takođe

- `classroom/shared/python/labeled_location_quiz.py` — render logika koju ovaj šablon koristi.
- `classroom/tools/geografija/evropa-kviz/` — referentna instanca.
- `classroom/CLAUDE.md` — orientacija za Claude sesije unutar repo-a.
