# classroom

Otvoreni alati za nastavu u osnovnoj školi, srednjoj školi i edukaciji odraslih.

Svaki alat je samostalan — radi u browseru bez login-a, bez naloga, bez server-a. Neki imaju i PDF verzije za štampu. Nastavnici mogu da koriste direktno kroz browser, ili da preuzmu fajlove i koriste lokalno.

## Pregled alata

Lista svih alata, organizovanih po predmetu: [classroom.tnosugar.github.io](https://classroom.tnosugar.github.io/) *(dostupno čim repo postane public + GitHub Pages se uključi)*

Aktuelni katalog:

- **Geografija**
  - [Evropa — geografski kviz](tools/geografija/evropa-kviz/) — 42 geografska pojma na karti Evrope. Interaktivni HTML kviz + PDF radna verzija + PDF rešenja.

## Struktura repo-a

```
classroom/
├── tools/                              # interaktivni alati, grupisani po predmetu
│   └── geografija/
│       └── evropa-kviz/                # jedan alat = jedan folder
│           ├── spec.yaml               # podaci alata (svi pojmovi, koordinate)
│           ├── make.py                 # rebuild komanda (čita spec.yaml)
│           ├── index.html              # generisan, otvara se u browseru
│           ├── radna.pdf               # generisan, za štampu
│           └── resenja.pdf             # generisan, ključ za nastavnika
│
├── content/                            # ne-interaktivni materijali (lekcije, planovi)
│
├── shared/                             # zajednički resursi koje koristi više alata
│   ├── data/
│   │   └── countries.geojson           # granice država (Natural Earth)
│   └── python/                         # zajedničke Python utility funkcije
│       ├── projection.py               # geografska projekcija
│       ├── geojson_utils.py            # učitavanje i obrada GeoJSON-a
│       └── labeled_location_quiz.py    # render logika za "kviz po lokacijama" tip alata
│
└── templates/                          # šabloni za nove alate
    └── labeled-location-quiz/          # za pravljenje nove varijante kviza tipa Evropa
```

## Kako da koristiš alat (nastavnik)

**Najjednostavnije:** otvori GitHub Pages link gore, klikni na alat, koristi.

**Lokalno:** preuzmi repo (ili samo jedan tool folder), otvori `index.html` u browseru.

**Štampa:** ako alat ima `radna.pdf` i `resenja.pdf`, preuzmi i odštampaj. `radna.pdf` je za učenika; `resenja.pdf` je ključ.

## Kako da napraviš novi alat

Većina alata trenutno spada u jedan tip — **labeled-location-quiz** (učenik upisuje broj pojma u kvadrat na pravoj lokaciji na karti). Za novi takav alat:

1. Kopiraj `templates/labeled-location-quiz/` ispod `tools/{predmet}/{novi-kviz-slug}/`.
2. Preimenuj `spec.template.yaml` u `spec.yaml`, popuni podatke.
3. Pokreni `python3 make.py` u tom folderu.
4. Generišu se `index.html`, `radna.pdf`, `resenja.pdf`. Commit i push.

Detalje vidi u `templates/labeled-location-quiz/README.md`.

Za drugi tip alata (npr. vremenski tajmer, drag-and-drop, generator radnih listova) — još nema šablon. Kad napraviš drugi takav, izvuci ga u `templates/` za sledeću upotrebu.

## Zavisnosti

Za rebuild alata (`python3 make.py`):

```bash
pip install pyyaml matplotlib numpy
```

Za korišćenje alata u browseru — ništa. Sve je samostalan HTML.

## Licenca i deljenje

Repo je trenutno privatan. Plan je da postane otvoren (open-source) kad bude dovoljno alata i dokumentacije da bude koristan i drugima. Tada će biti dodata licenca (verovatno MIT za kod, CC-BY-SA za sadržaj).

Ako želiš da koristiš ili adaptiraš nešto pre tog momenta — pitaj direktno.
