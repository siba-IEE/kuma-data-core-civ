# ADR-0026 : Indice de clarté `kt` aux 142 localités, pour les 4 sources de GHI

Date : 2026-10-15. Statut : accepté — **gravé** (migration 0041, 2026-10-15).

## Contexte

La grandeur `kt` (id 2, F1 `stockee`, sans dimension) est seedée depuis 0002
mais n'avait ni fiche, ni service, ni valeur en base. Le GHI mensuel des 4
sources est gravé aux 142 localités (ADR-0015, ADR-0018) : NASA POWER
1991-2025, CAMS 2005-2025, SARAH-3 et ERA5 2005-2023. Rapporté à
l'irradiation extraterrestre `H0`, il donne un indice débarrassé de l'effet
astronomique (latitude, saison), comparable d'un lieu et d'un mois à
l'autre.

## Décision

### Formule (fiche `docs/methodologie/grandeurs/kt.md`, version 1)

```
kt(annee, mois) := Σ GHI(t) / Σ H0(t), t ∈ jours(annee, mois) = GHI_moyen / H0_moyen
kt(annee)       := Σ GHI(t) / Σ H0(t), t ∈ jours(annee)       = Σ_m GHI_m·n_m / Σ_m H0_m·n_m
```

`H0` journalier : Duffie & Beckman (5ᵉ éd., 2020) éq. 1.10.3 ; `H0` mensuel :
moyenne des `H0` de **tous** les jours civils du mois. Fonctions pures dans
`services/grandeurs/kt.py`, testées contre les valeurs publiées du livre.

### Choix tranchés

| Point | Retenu | Écarté | Raison |
|---|---|---|---|
| Déclinaison | Spencer (1971), éq. 1.6.1b | Cooper (1969), éq. 1.6.1a | erreur < 0,035° contre jusqu'à 1,4° ; D&B l'utilisent dans les solutions de tous leurs exemples |
| Excentricité | Spencer (1971), éq. 1.4.1b | `1 + 0,033 cos(360° n/365)` | ±0,01 % contre jusqu'à 0,26 % d'écart |
| Constante solaire | **1361 W/m²** | 1367 W/m² (WRC, D&B) | valeur mesurée SORCE/TIM (Kopp & Lean 2011), nominale UAI 2015 B3 ; biais nul contre NASA (ci-dessous) |
| `H0` mensuel | moyenne des jours civils | jour moyen de Klein (1977) | définition exacte de `Σ H0` ; le jour moyen s'en écarte jusqu'à +0,46 % |
| Latitude | celle de la localité, lue en base | centre de maille de la source | une localité, une géométrie ; écart borné (§ Validation externe) |

Aux latitudes ivoiriennes, le couple de Cooper déplacerait `H0` mensuel de
−0,3 % à +0,9 % ; la constante de 1367 W/m² abaisserait tous les `kt` de
0,44 %.

### Périmètre et migration 0041

- 4 sources × 142 localités = **568 séries** `kt_<source>_<loc>`
  (`nasa_power`, `cams`, `sarah3`, `era5`), source `kuma_calculs`, méthode
  `calcul_derive`, confiance **B** (héritée du GHI), version de formule 1.
- **160 176 lignes mensuelles** et **13 348 annuelles** :

| Source | Période | Mensuel | Annuel |
|---|---|---:|---:|
| NASA POWER | 1991-2025 | 59 640 | 4 970 |
| CAMS | 2005-2025 | 35 784 | 2 982 |
| SARAH-3 | 2005-2023 | 32 376 | 2 698 |
| ERA5 | 2005-2023 | 32 376 | 2 698 |

- `H0` calculé **en Python dans la migration** (paramètres figés : Spencer,
  1361 W/m²), à la latitude lue dans `localites` ; `kt` calculé par
  `calculer_kt` (sommes `math.fsum`), puis inséré par `COPY`. Le résultat ne
  dépend ni du plan d'exécution ni de l'ordre d'agrégation de Postgres.
- Les séries `kt_era5_<loc>` portent la **mise en garde du saut ERA5 de
  2021**, phrase identique à celle de 0033 (le test de 0033 est étendu à ces
  142 séries).
- Garde-fous : grandeur au contrat ; aucune série ni ligne `kt`
  préexistante ; 142 localités avec latitude ; 142 séries GHI **mensuelles**
  par source (les séries journalières NASA sont exclues), à la période
  attendue, complètes, GHI > 0 ; 13 valeurs par année et par série ;
  comptes totaux exacts ; domaine `0 < kt < 1`. `ANALYZE` en fin de
  migration. `downgrade` supprime lignes et séries `kt`.
- Durées mesurées : upgrade ~45 s, downgrade ~17 s ; aller-retour
  0041 → 0033 → 0041 à empreinte md5 identique (séries et lignes).

## Validation externe (hors dépôt)

### Références publiées

Dans la convention du livre (Cooper, `1 + 0,033 cos`, 1367 W/m², année non
bissextile), la moyenne des `H0` journaliers reproduit la **table 1.10.1**
de Duffie & Beckman à 0°, 5°N, 10°N et 15°N à l'arrondi près (écart maximal
0,0495 MJ/m², table au dixième ; 0,18 MJ/m² avec le jour moyen), ainsi que
l'exemple 1.10.1 (43°N, 15 avril : 33,8 MJ/m²). La convention retenue s'en
écarte de −0,65 % à +0,54 % à 5°N et 10°N. Ces contrôles sont des tests
unitaires.

### NASA POWER `TOA_SW_DWN` et `ALLSKY_KT`

Point mensuel NASA POWER (API v2.10, communauté RE), 1991-2025, interrogé le
2026-10-15 aux coordonnées des localités. `ALLSKY_KT` est publié à 2
décimales et servi au pas mensuel à partir de 2001 seulement.

| Localité | Lat. | `H0`/TOA − 1 : biais | min – max | `kt` − `ALLSKY_KT` max \|·\| | `kt` − SW/TOA max \|·\| | annuel − `ALLSKY_KT` max \|·\| |
|---|---:|---:|---:|---:|---:|---:|
| Tabou | 4,42 | +0,00 % | −0,33 – +0,38 % | 0,0060 | 0,0019 | 0,0050 |
| Abidjan | 5,42 | +0,01 % | −0,32 – +0,40 % | 0,0060 | 0,0021 | 0,0051 |
| Yamoussoukro | 6,83 | −0,08 % | −0,71 – +0,28 % | 0,0075 | 0,0039 | 0,0050 |
| Korhogo | 9,42 | +0,02 % | −0,33 – +0,48 % | 0,0073 | 0,0029 | 0,0049 |
| Tengréla | 10,49 | −0,01 % | −0,42 – +0,42 % | 0,0073 | 0,0026 | 0,0053 |
| **5 localités** | | **−0,01 %** | −0,71 – +0,48 % | 0,0075 | 0,0039 | 0,0053 |

(SW/TOA = `ALLSKY_SFC_SW_DWN / TOA_SW_DWN`, non arrondi ; annuel : 25 ans
2001-2025 par localité.)

- **Constante solaire** : avec 1367 W/m², le biais `H0`/TOA passe à
  **+0,43 %** (−0,27 à +0,92 %). 1361 W/m² est cohérent avec NASA.
- **Yamoussoukro** est le seul écart notable : la localité est à 0,33° du
  centre de sa maille NASA de 1° (6,5°N), les quatre autres à moins de
  0,1°. Calculé au centre de maille, son biais tombe à −0,01 % (−0,33 à
  +0,32 %) : le `TOA_SW_DWN` se comporte comme une valeur de centre de
  maille (constat, non documenté par NASA).
- Résidu saisonnier commun aux 4 autres localités : moyennes mensuelles
  nulles ou négatives de janvier à août (jusqu'à −0,22 %), positives de
  septembre à décembre (jusqu'à +0,36 % en novembre) ; non attribué.
- `kt` NASA − `ALLSKY_KT` : biais +0,0002, écart ≤ 0,0075 sur 1 500 mois,
  dont jusqu'à 0,005 d'arrondi ; contre le rapport non arrondi, ≤ 0,0039.
  L'annuel NASA (mois « 13 ») est cohérent avec notre rapport de sommes
  (≤ 0,0006 contre SW/TOA annuels).
- Le GHI des seeds est identique à l'`ALLSKY_SFC_SW_DWN` servi (écart nul
  sur 2 100 mois).

## Résultat — 142 localités

### Par source et par latitude

Moyenne 2005-2023 (fenêtre commune aux 4 sources) des `kt` annuels ; bandes
de latitude : sud < 6,5°N (43 localités), centre 6,5-8,5°N (68), nord
≥ 8,5°N (31).

| Source | National | Sud | Centre | Nord | Min (localité) | Max (localité) | Pente par degré | r(latitude) |
|---|---:|---:|---:|---:|---|---|---:|---:|
| NASA POWER | 0,489 | 0,463 | 0,481 | 0,543 | 0,452 (Fresco) | 0,573 (Minignan) | +0,021 | +0,88 |
| CAMS | 0,541 | 0,517 | 0,537 | 0,586 | 0,466 (Abidjan) | 0,605 (Tengréla) | +0,017 | +0,85 |
| SARAH-3 | 0,554 | 0,533 | 0,547 | 0,596 | 0,498 (Alépé) | 0,614 (Tengréla) | +0,015 | +0,82 |
| ERA5 | 0,496 | 0,468 | 0,485 | 0,560 | 0,440 (Guéyo) | 0,583 (Tengréla) | +0,023 | +0,83 |

NASA sur 1991-2025 : moyenne nationale 0,490 ; année la plus couverte 2005
(0,479), la plus claire 1994 (0,506). Plages gravées, toutes sources :
annuel 0,421 à 0,627, mensuel 0,299 à 0,732 — loin des bornes 0 et 1.

### Saisons : Harmattan (DJF) contre mousson (JJA)

Moyenne 2005-2023 des `kt` mensuels :

| Source | Sud DJF | Sud JJA | Centre DJF | Centre JJA | Nord DJF | Nord JJA |
|---|---:|---:|---:|---:|---:|---:|
| NASA POWER | 0,501 | 0,406 | 0,532 | 0,415 | 0,602 | 0,477 |
| CAMS | 0,557 | 0,454 | 0,593 | 0,466 | 0,654 | 0,525 |
| SARAH-3 | 0,607 | 0,452 | 0,635 | 0,458 | 0,684 | 0,511 |
| ERA5 | 0,522 | 0,402 | 0,574 | 0,400 | 0,653 | 0,464 |

### Mois les plus clairs et les plus couverts

Climatologie nationale 2005-2023 (moyenne des 142 localités) :

| Source | J | F | M | A | M | J | J | A | S | O | N | D |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| NASA POWER | **0,554** | 0,517 | 0,518 | 0,521 | 0,507 | 0,453 | 0,421 | *0,403* | 0,430 | 0,489 | 0,532 | 0,541 |
| CAMS | **0,607** | 0,583 | 0,565 | 0,564 | 0,560 | 0,508 | 0,471 | *0,448* | 0,479 | 0,541 | 0,596 | 0,596 |
| SARAH-3 | **0,648** | 0,623 | 0,587 | 0,585 | 0,554 | 0,495 | 0,461 | *0,447* | 0,482 | 0,545 | 0,605 | 0,641 |
| ERA5 | **0,598** | 0,557 | 0,537 | 0,531 | 0,496 | 0,442 | 0,412 | *0,389* | 0,435 | 0,487 | 0,525 | 0,571 |

Extrêmes mensuels : NASA 0,307 (Sandégué, août 2024) à 0,704 (Folon,
janvier 2021) ; CAMS 0,320 (Tanda, août 2005) à 0,732 (Tengréla, janvier
2019) ; SARAH-3 0,321 (Sud-Comoé, août 2009) à 0,727 (Doropo, janvier
2012) ; ERA5 0,299 (Guéyo, août 2005) à 0,694 (Tengréla, novembre 2006).

### Comparaison des sources

Écart moyen `kt` source − `kt` NASA, mensuel, sur la fenêtre commune avec
NASA :

| Source | Tous mois | DJF | JJA | Sud | Centre | Nord |
|---|---:|---:|---:|---:|---:|---:|
| CAMS | +0,053 | +0,058 | +0,051 | +0,054 | +0,056 | +0,044 |
| SARAH-3 | +0,065 | +0,100 | +0,042 | +0,071 | +0,067 | +0,054 |
| ERA5 | +0,008 | +0,038 | −0,011 | +0,005 | +0,005 | +0,018 |

Saut ERA5 : moyenne nationale des `kt` annuels 2021-2023 contre 2016-2020 :
NASA +0,3 %, SARAH-3 +0,7 %, CAMS +1,3 %, **ERA5 +3,6 %** (variabilité
interannuelle 2005-2020 : 1,1 à 1,3 % selon la source).

**Lecture (constats, pas validation) :**

- **Le cycle saisonnier domine** : `kt` perd 0,10 à 0,19 entre la saison
  sèche (DJF) et la mousson (JJA), plus de dix fois l'écart type
  interannuel des moyennes nationales annuelles (0,005 à 0,007). **Janvier est le mois le plus clair et août le plus
  couvert** pour les 4 sources et dans les 3 bandes de latitude, y compris
  au sud, où août tombe dans la petite saison sèche. Le sud garde un palier
  en mars-avril (NASA 0,49-0,50) avant le creux de juin-août.
- **`kt` croît du sud au nord** (r = +0,82 à +0,88, +0,015 à +0,023 par
  degré), en miroir de la fraction diffuse NASA, qui décroît vers le nord
  (ADR-0017, r = −0,83).
- **Les sources gardent leur hiérarchie de GHI** : à `H0` commun,
  `kt_source / kt_NASA = GHI_source / GHI_NASA`, donc les écarts relatifs
  sont exactement ceux d'ADR-0017 ; `kt` les place sur une échelle absolue
  (NASA ≈ ERA5 ≈ 0,49-0,50, CAMS 0,54, SARAH-3 0,55).
- **Le désaccord dépend de la saison** : SARAH-3 − NASA double en saison
  sèche (+0,100 en DJF contre +0,042 en JJA) et ERA5 − NASA change de signe
  (+0,038 contre −0,011), alors que CAMS − NASA reste stable (+0,058 contre
  +0,051). La saison sèche est celle de l'Harmattan et des aérosols
  désertiques ; le traitement des aérosols par chaque source est une
  hypothèse, **non établie ici**.
- **Le saut ERA5 de 2021 passe intégralement dans `kt`** (+3,6 %, `H0` ne
  variant pas d'une année à l'autre), d'où la mise en garde portée par les
  séries `kt_era5_<loc>`.

## Conséquences

- Première grandeur dérivée gravée pour les **4 sources** (la fraction
  diffuse ne l'est que pour NASA) : `kt` met les sources sur une échelle
  commune sans changer leurs écarts relatifs.
- `kt` mensuel est l'entrée des corrélations de décomposition du GHI (Erbs
  et al. 1982, déjà utilisée par `poa_parametrable`) et neutralise l'effet
  astronomique pour la comparaison aux mesures sol ESMAP 2022-2024 (Jalon 4).
- Patron réutilisable : grandeur astronomique calculée en Python dans la
  migration, paramètres figés, insertion par `COPY`.

## Points ouverts

- La description de `kt` dans `grandeurs_referentiel` (seed 0002) dit
  « Ingéré directement depuis NASA POWER (paramètre `ALLSKY_KT`) », ce qui
  décrit le passe-plat horaire (`services/horaire.py`) et non les valeurs
  mensuelles et annuelles calculées ici. Non modifiée par 0041 ; à amender
  par une décision distincte.
- Les séries `kt` SARAH-3 et ERA5 seront à prolonger quand PVGIS servira
  2024+ (comme leurs séries de GHI, ADR-0018).
- Un `kt` journalier NASA est calculable sur les 34 localités du journalier
  (ADR-0016) ; non gravé.
