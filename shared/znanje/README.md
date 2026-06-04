# shared/znanje — atomizovana baza pojmova

Deljena baza znanja za sve alate u `classroom` repou. Svaki **pojam** (geografski,
istorijski, itd.) je jedan atomski čvor: zaseban folder sa opisom po izvoru i jednim
agregatnim fajlom koji mири izvore. Pojmovi su međusobno povezani tipiziranim vezama,
pa zajedno čine **graf znanja** koji raste kroz proces.

Cilj: jedan pojam postoji **jednom** u celom repou. Geo-kviz, istorijski timeline i
budući alati ga referenciraju preko `slug`-a umesto da dupliraju opis.

## Struktura foldera

```
shared/znanje/
├── README.md                  # ovaj fajl — šema + pravila
├── _relacije.yaml             # REGISTAR tipova veza (mašinski čitljiv, raste vremenom)
└── {slug}/                    # jedan folder = jedan pojam
    ├── index.md               # AGREGAT: frontmatter veze + pomiren opis + kontradikcije
    └── izvori/                # sirovi opisi, po jedan fajl po izvoru
        ├── wikipedia.md
        └── {drugi-izvor}.md   # u budućnosti: druga enciklopedija, udžbenik, atlas...
```

`{slug}` je ASCII kebab-case bez dijakritika: `Skandinavske planine` → `skandinavske-planine`,
`Galdhøpiggen` → `galdhepigen`.

## `index.md` — agregatni fajl

Frontmatter nosi identitet i veze; telo nosi pomiren opis i eksplicitne kontradikcije.

```yaml
---
pojam: Skandinavske planine        # ljudski naziv (može imati dijakritike)
slug: skandinavske-planine         # = ime foldera
vrsta: planinski_venac             # klasifikacija (vidi _relacije.yaml › vrste)
predmet: [geografija]              # u kojim predmetima se pojam koristi
veze:                              # SAMO "forward" smer; inverz se izvodi programski
  nalazi_se_u: [skandinavsko-poluostrvo]
  prostire_se_kroz: [norveska, svedska, finska]
  srodni: [skandinavski-kaledoni, galdhepigen]
izvori: [izvori/wikipedia.md]      # putanje ka sirovim izvorima
status: pilot                      # pilot | nacrt | potvrdjen
azurirano: 2026-06-04
---
```

### Telo `index.md`
- `## Sažetak` — pomiren opis u 2–4 rečenice, sopstvenim rečima.
- `## Ključne činjenice` — datumi, brojevi, imena (faktografija koja se ne parafrazira).
- `## Hintovi` — opciono; progresivni hintovi za kviz (vidi dole).
- `## Pomirenje izvora` — gde se izvori slažu; kako su spojeni.
- `## Otvorena pitanja i kontradikcije` — gde se izvori (ili literatura) razilaze. **Ne brisati neslaganja — istaći ih.**

### `## Hintovi` — progresivni hintovi za kviz

Uređena lista (bullet `- `) hintova koji pomažu učeniku da **sam zaključi** gde je pojam,
**redom od najsuptilnijeg ka najkonkretnijem**. Kviz ih otkriva jedan po jedan: sa svakom
greškom izlazi sledeći hint u side-panelu. Pravila pisanja:

- Prvi hint **ne sme** da bude očigledan ni da imenuje odgovor — navodi na razmišljanje
  (oblik, tip, odnos prema susedima), ne na lokaciju direktno.
- Svaki sledeći je konkretniji; poslednji sme da bude jasno lociran, ali i dalje ne imenuje
  sam pojam.
- Posle poslednjeg hinta, sledeća greška u kvizu otkriva **ceo opis** (faktički odgovor).
- 2–4 hinta je obično dovoljno. Pojam bez `## Hintovi` sekcije = kviz ćuti na grešku
  (nema generičkih hintova).
- `vrsta`, izvori i pun opis se **ne** prikazuju dok je nerešeno — samo hintovi.

## Veze: slug-ovi, ne nazivi

Cilj svake veze je **slug** drugog pojma — ne prikazni naziv. Slug koji još **nema svoj
folder** je validan: označava budući čvor (kao `[[wikilink]]` koji tek treba napisati).
Tako iz teksta jednog pojma izvlačimo nove pojmove: pomenут slug uđe u `veze`, a kasnije
mu napravimo folder, povučemo izvore i napišemo `index.md`.

Čuvamo samo jedan smer veze (npr. planine `nalazi_se_u` poluostrvo). Inverz
(`poluostrvo obuhvata planine`) **ne** upisujemo ručno — izvešćemo ga programski iz
registra, da se ne održavaju dva mesta.

## `_relacije.yaml` — registar tipova veza (otvoren, raste)

Broj tipova tipiziranih veza **nije fiksan** — raste kako se uvode novi pojmovi, i to je
namerno proces. Registar `_relacije.yaml` je jedino mesto istine: svaki predikat ima opis,
opcioni inverz, i napomenu o domenu. `srodni` je uvek dostupan kao netipizovan fallback.

### Proces uvođenja novog tipa veze
1. Prvo pokušaj da uklopiš odnos u postojeći predikat ili u `srodni`.
2. Ako se odnos ponavlja kroz više pojmova i nosi semantiku koju vredi mašinski koristiti
   (npr. za generisanje pitanja), tek tada uvedi nov predikat.
3. Dodaj ga u `_relacije.yaml` sa: `naziv`, `opis`, `inverz` (ako postoji), `primer`.
4. Predikat dobija ime na srpskom, snake_case, glagolski/odnosni oblik
   (`prostire_se_kroz`, `granici_se_sa`, `nalazi_se_u`).

Dok predikat nije u registru, **ne koristi ga** — prvo ga registruj.

## Licenca izvora

Wikipedia tekst je CC BY-SA. U svakom `izvori/*.md` fajlu obavezni su `url`, `datum_pristupa`
i `licenca` u frontmatter-u. U `izvori/` se piše **parafraza + faktografija**, ne doslovan
prepis celih pasusa.
