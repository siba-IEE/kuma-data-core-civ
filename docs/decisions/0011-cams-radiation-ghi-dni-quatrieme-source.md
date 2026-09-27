# ADR-0011 : CAMS Radiation — 4ᵉ source GHI et 1er écart DNI (NASA↔CAMS)

Date : 2026-09-27. Statut : accepté — **gravé** (migrations 0014-0016, 2026-09-27).

## Contexte

La triangulation GHI (ADR-0010) repose sur trois sources : NASA POWER (CERES),
SARAH-3 (Meteosat/Heliosat CM SAF) et ERA5 (réanalyse). **CAMS Radiation**
(Heliosat-4 + McClear, Meteosat, aérosols CAMS explicites) apporte deux choses
qu'aucune autre n'a ici :

1. une **4ᵉ source GHI** satellitaire à traitement d'aérosols explicite ;
2. surtout, une **2ᵉ source DNI** — le DNI n'a jusqu'ici qu'une seule source
   (NASA POWER, ADR-0007), donc **aucun écart DNI n'est calculable**. Le DNI est
   la grandeur la plus sensible aux aérosols (**Harmattan** en Afrique de
   l'Ouest), et CAMS DNI est aérosol-corrigé : c'est l'écart inter-source le
   plus instructif du domaine ivoirien.

Accès : CAMS est servi par l'**ADS Copernicus**, qui exige une **clé** (via
`cdsapi`). La recette d'ingestion est reprise du moteur générique
`kuma-data-core` (`scripts/preparer_seed_cams.py`, sondage ADS vérifié
2026-06-16). Cet ADR et l'ingester CIV sont préparés **sans la clé** ; la gravure
(seeds + migrations + tests) se fait dans une session disposant du secret
`ADS_API_KEY`.

## Décision

### Source : `cams_radiation` (id 13, déjà seedée) — GHI **et** DNI

CAMS Radiation timeseries sert le GHI et le DNI (BNI) all-sky du même produit.
On réutilise la source **existante** `cams_radiation` (id 13) pour les deux
grandeurs. `methode_collecte='modele_satellitaire'` : Heliosat-4 est une
restitution **satellitaire** — donc, contrairement à ERA5 (ADR-0010),
**aucune extension d'énumération** n'est nécessaire. Confiance dérivée **B**
(R4 ; satellite, A réservé au terrain).

### Contrat de série brute (identique à ADR-0007/0008)

Grandeurs `ghi` et `dni`, unité `kwh_par_m2_jour` héritée, granularité
`mensuel`, méthode `modele_satellitaire`, confiance **B**, statut `brut`,
**couverture 2005-2020** (CAMS démarre 2004-02 ; on grave la fenêtre commune aux
autres sources). **Conversion** ADS : le CSV donne l'irradiation **mensuelle
intégrée en Wh/m²** ; on la ramène en moyenne journalière
`kWh/m²/jour = (Wh/m²/mois ÷ 1000) ÷ jours du mois`. Les colonnes GHI et BNI sont
**repérées par nom** dans l'en-tête du CSV (robustesse), pas par index en dur.

Résultat : **6 séries** brutes (GHI + DNI × 3 points) × 192 mesures = **1152
mesures** (migration 0014).

### Deux grandeurs d'écart dérivées — NASA POWER au dénominateur commun

Même contrat qu'ADR-0009 (`stockee`, `pourcent`, F1, matérialisées dans
`grandeurs_metier`, fenêtre commune stricte par jointure SQL, confiance B, 576
lignes chacune) :

1. **`ecart_relatif_ghi_cams_nasa`** — `(cams − nasa) / nasa × 100` : **4ᵉ point
   de la triangulation GHI**, même dénominateur NASA que les écarts SARAH-3 et
   ERA5 → les quatre sources se comparent sur une seule référence.
2. **`ecart_relatif_dni_cams_nasa`** — `(cams − nasa) / nasa × 100` : **1er écart
   DNI** de l'instance. Attendu **fortement positif** (CAMS lit davantage de DNI
   que NASA sous aérosols — le moteur générique observe ≈ +35 % côté Guinée),
   signature du Harmattan. *(Gravure : signe confirmé, mais pic saisonnier en
   mousson et non en Harmattan — voir « Résultat de la gravure ».)*

**Divergence assumée avec le précédent `ecart_relatif_dni_cams` (id 27,
héritage Guinée)**, qui mettait **CAMS au dénominateur** (`(nasa − cams)/cams`,
CAMS = référence d'écart DNI). En CIV, **NASA POWER est la référence uniforme**
de *tous* les écarts inter-source (GHI comme DNI), ce qui les rend mutuellement
comparables et cohérents avec ADR-0009/0010. Le dénominateur est une convention ;
le signe reste un **résultat empirique**. La grandeur héritée id 27 n'est pas
réemployée (nom `_nasa` explicite pour lever l'ambiguïté d'orientation).

### Confiance dérivée des écarts : B

Les deux entrées sont B (satellite). R4 sur `calcul_derive` (source
`kuma_calculs`) → B ; `min(B, B) = B` ; jamais A. Idem ADR-0009.

## Résultat de la gravure (moyennes 2005-2020)

Ingestion ADS du 2026-09-27 (3 requêtes, ~1-4 min de file chacune) ; 6 séries
× 192 mois, toutes dans les bornes (GHI ∈ [3,33 ; 6,58], DNI ∈ [0,94 ; 7,68]
kWh/m²/jour). Aucun mois manquant, aucune valeur comblée.

**GHI — triangulation à 4 sources** (kWh/m²/jour ; écarts en rapport de moyennes
de période, la grandeur stocke le ratio par mois) :

| Point | NASA | CAMS | SARAH-3 | ERA5 | CAMS − NASA | SARAH-3 − NASA | ERA5 − NASA |
|---|---:|---:|---:|---:|---:|---:|---:|
| Abidjan | 4,66 | 4,62 | 4,97 | 5,00 | **−0,8 %** | +6,6 % | +7,3 % |
| Yamoussoukro | 4,60 | 5,23 | 5,36 | 4,68 | **+13,7 %** | +16,6 % | +1,8 % |
| Korhogo | 5,29 | 5,74 | 5,88 | 5,55 | **+8,4 %** | +11,1 % | +4,9 % |

**DNI — premier écart** (kWh/m²/jour) :

| Point | NASA | CAMS | CAMS − NASA | moy. écart mensuel | DJF (Harmattan) | JJA (mousson) |
|---|---:|---:|---:|---:|---:|---:|
| Abidjan | 2,13 | 2,74 | **+29,1 %** | +31,5 % | +25,2 % | +38,2 % |
| Yamoussoukro | 2,05 | 3,58 | **+74,7 %** | +78,1 % | +64,1 % | +85,3 % |
| Korhogo | 3,07 | 4,55 | **+48,2 %** | +51,8 % | +45,6 % | +69,3 % |

**Lecture (honnête, sans sur-interprétation) :**

- **GHI, la 4ᵉ source nuance la lecture d'ADR-0010.** À Abidjan, CAMS colle à
  NASA (−0,8 %) : on a maintenant 2 sources contre 2 (NASA/CAMS bas,
  SARAH-3/ERA5 haut), et « NASA est le point bas » n'est plus tranché. À
  Yamoussoukro, CAMS (+13,7 %) rejoint SARAH-3 (+16,6 %) contre NASA/ERA5 :
  SARAH-3 n'y est plus isolé. **Caveat d'indépendance** : CAMS et SARAH-3
  exploitent tous deux l'imagerie **Meteosat** ; leur concordance est en partie
  structurelle et ne vaut pas deux votes indépendants.
- **DNI : le signe attendu est confirmé** (CAMS nettement au-dessus de NASA aux 3
  points, de +29 % à +75 %, écart mensuel toujours positif à Korhogo et
  Yamoussoukro).
- **L'hypothèse « signature du Harmattan » n'est pas confirmée par la
  saisonnalité** : l'écart culmine en **JJA (mousson)**, pas en **DJF
  (Harmattan)**, aux 3 points. Il est donc au moins autant piloté par le
  traitement des **nuages** que par celui des aérosols. Le Harmattan reste une
  question ouverte, pas un résultat. Il faudra une ancre sol DNI (Jalon 4) pour
  dire quelle source est juste.

## Reproductibilité et accès

`scripts/ingest_cams_radiation_mensuel.py` (CIV) : lit la clé depuis la variable
d'environnement **`ADS_API_KEY`** (secret d'environnement ; repli `~/.cdsapirc`),
télécharge le CSV mensuel CAMS aux 3 points, extrait GHI + BNI par nom de
colonne, convertit, et **régénère deux seeds committés**
(`series_cams_ghi_mensuel_civ`, `series_cams_dni_mensuel_civ`). Les migrations
les lisent **hors-ligne** (invariant README). L'ADS exige une clé : sans elle,
seuls l'ADR et l'ingester existent ; la gravure attend une session portant
`ADS_API_KEY`.

## Conséquences

- **Triangulation GHI à 4 sources** : deux satellites classiques (NASA/CERES,
  SARAH-3/CM SAF), une réanalyse (ERA5) et un satellite aérosol-explicite
  (CAMS/Heliosat-4) — la localisation de l'aberrant gagne une dimension
  (traitement d'aérosols).
- **Premier écart DNI** de l'instance : le Harmattan devient chiffrable en base
  (CAMS − NASA sur le DNI), grandeur la plus stratégique pour le solaire à
  concentration et le suivi de salissure.
- Tous les écarts partagent la référence NASA POWER → un seul cadre de lecture
  pour GHI et DNI.
- CAMS étant satellitaire, l'énumération `methode_collecte` reste inchangée
  (contraste avec ERA5).
- Étendre au DHI ou à d'autres points suivra le même contrat, dès lors que la
  clé ADS est disponible.
