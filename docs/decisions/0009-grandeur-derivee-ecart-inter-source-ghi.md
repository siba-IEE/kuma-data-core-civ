# ADR-0009 : première grandeur dérivée — écart inter-source GHI (SARAH-3 vs NASA POWER)

Date : 2026-09-17. Statut : accepté.

## Contexte

ADR-0007 et ADR-0008 ont gravé deux sources **brutes** de GHI mensuel aux
mêmes 3 points (Abidjan, Yamoussoukro, Korhogo) : NASA POWER (1991-2020) et
SARAH-3/PVGIS (2005-2020). Le désaccord entre elles — SARAH-3 systématiquement
plus haut, +6,6 à +16,6 % — est le savoir que ce moteur doit **tracer** (une
valeur porte sa source *et* son écart aux autres). Jusqu'ici cet écart était
seulement *calculable* ; cet ADR le **grave comme grandeur**.

C'est la **première grandeur calculée** de l'instance CIV (jusque-là :
localités et donnée brute uniquement). Elle franchit donc un seuil : trois
pièges doivent être tranchés **avant** gravure.

## Décision

Nouvelle grandeur au `grandeurs_referentiel` :

- **code** : `ecart_relatif_ghi_sarah3_nasa` ;
- **libellé** : « Écart relatif GHI SARAH-3 par rapport à NASA POWER » ;
- **unité** : `pourcent` (id 123, sans dimension) ;
- **famille** : `F1` ;
- **strategie_calcul** : **`stockee`** (voir piège 1) ;
- **formule** : `(sarah3 − nasa) / nasa × 100`, par (localité, année, mois)
  (voir orientation).

### Orientation : NASA POWER au dénominateur (référence)

`(sarah3 − nasa) / nasa × 100` prend **NASA POWER comme référence** (dénominateur)
et **SARAH-3 comme valeur comparée** (numérateur). Un écart positif = SARAH-3
plus haut que la référence. Justification :

- NASA POWER GHI est l'**ancre primaire** de l'instance : gravé en premier
  (0008), **plus long enregistrement** (1991-2020, normale climatologique OMM
  30 ans) — la référence climatologique naturelle.
- SARAH-3 (0010) est la **deuxième source**, comparée *à* cette référence.
- Cette orientation **retrouve le signe et l'ordre de grandeur** déjà publiés
  en ADR-0008 et au CHANGELOG (SARAH-3 plus haut, +6,6 / +16,6 / +11,1 %).
  La moyenne des écarts **mensuels** gravés (+6,3 / +16,5 / +11,1 %) diffère à
  la marge des chiffres ADR-0008, qui sont des rapports de **moyennes de
  période** (moyenne des ratios vs ratio des moyennes) — les deux sont
  légitimes ; la grandeur est définie **par (localité, mois)**. Inverser
  l'orientation mettrait le moteur en contradiction de **signe** avec sa
  propre documentation gravée.

Divergence assumée avec le précédent `ecart_relatif_dni_cams` (id 27,
héritage), dont la formule est `(nasa − cams) / cams` : là, **CAMS** était la
référence d'écart (DNI aérosol-corrigé) donc au dénominateur ; ici **NASA
POWER** est la référence-de-record (série la plus longue), donc au
dénominateur. La convention stable est « **source de référence = dénominateur** » ;
c'est le *rôle* de référence qui change de source, pas la règle. Le signe reste
un **résultat empirique** (SARAH-3 plus haut), non un choix de design.

## Les trois pièges, tranchés

### Piège 1 — stockée vs calculée-à-la-volée

Le schéma (commentaire `grandeurs_referentiel.strategie_calcul`) définit :
`stockee` = *valeur persistée dans `grandeurs_metier`* ; `calculee_volee` =
*recalculée à chaque consultation, dépendante du périmètre courant*.

L'écart GHI est **déterministe** et **indépendant du périmètre** : il ne
dépend que des deux séries brutes figées et de leur fenêtre commune, jamais de
l'ensemble des sites en scope ni d'un paramètre utilisateur (contrairement à
`ecart_relatif_referentiel` id 7 ou `rang_referentiel`, réellement
`calculee_volee`). Il est donc **`stockee`** : matérialisé dans
`grandeurs_metier`, `periode_type='mensuel'`, une ligne par (localité, année,
mois).

Ce choix **corrige** l'incohérence héritée de id 27 (`ecart_relatif_dni_cams`),
étiqueté `calculee_volee` *tout en se décrivant* « matérialisé dans
grandeurs_metier ». L'instance CIV ne reproduit pas ce drift : ce qui vit dans
`grandeurs_metier` est `stockee`.

### Piège 2 — appariement de fenêtre (le piège central)

NASA GHI couvre **1991-2020** (360 mois), SARAH-3 GHI **2005-2020** (192 mois).
L'écart n'a de sens que là où **les deux** sources ont une valeur pour le même
(localité, année, mois). On calcule donc l'écart **strictement sur
l'intersection** : 2005-2020, soit **192 mois × 3 localités = 576 lignes**.

Réalisation : l'écart est calculé **dans la migration par une jointure SQL**
entre les deux séries `ghi` (appariées par source), sur `(localité, année,
mois)`. Une jointure ne produit *que* les couples présents des deux côtés :
l'intersection est garantie par construction, jamais un mois 1991-2004 côté
NASA seul. La migration vérifie `COUNT = 576` (garde-fou dur).

### Piège 3 — propagation de confiance

Les deux entrées sont **confiance B** (satellite). La confiance dérivée de
l'écart est **B**, établie par **deux** chemins convergents :

1. **Règle mécanique R1-R4** appliquée à la série calculée (source
   `kuma_calculs`, `fiabilite='haute'`, `methode_collecte='calcul_derive'`) :
   R1 non (haute), R2 non, R3 non (pas `mesure_directe`), **R4 catch-all → B**.
2. **Fonction des deux entrées** : une dérivée ne dépasse pas la plus faible de
   ses entrées ; `min(B, B) = B`. Une grandeur inter-source **ne peut jamais
   être A** (A réservé à la mesure terrain `mesure_directe`).

Les deux chemins donnent **B**. Gravé en `niveau_confiance_derive='B'`,
`statut='brut'` (calcul non encore validé humainement — défaut éditorial).

## Réalisation

- Grandeur, **3 séries calculées** (`series_metadonnees`, source
  `kuma_calculs` id 10, `methode_collecte='calcul_derive'`, `granularite=NULL`
  — routage `grandeurs_metier` par la temporalité `periode_type`) et **576
  lignes** `grandeurs_metier` : migration **0011**.
- L'écart est calculé **hors-ligne, dans la migration, par SQL** depuis les
  mesures déjà gravées (0008 + 0010). **Aucun seed** (l'écart est 100 %
  dérivable : un seed ne ferait que dupliquer la base avec un risque de drift)
  et **aucun réseau** (invariant README préservé — la migration lit la base,
  pas une source amont).
- `note_publique` de chaque série calculée : trace les deux sources amont et la
  fenêtre.

## Conséquences

- L'écart inter-source devient une **grandeur de plein droit**, interrogeable
  par (localité, mois), portant sa confiance dérivée — le cœur « confiance
  tracée » passe du calculable au gravé.
- La **cohérence est structurelle** : l'écart étant recalculé depuis la base à
  chaque `alembic upgrade`, il ne peut pas diverger des séries brutes. Toute
  correction d'une mesure brute impose de régénérer l'écart (nouvelle
  migration), jamais de l'éditer à la main.
- Fenêtre commune stricte : ajouter des années côté SARAH-3 (2021-2023
  disponibles) ou côté NASA élargira l'intersection en repassant par une
  migration, avec le même garde-fou de complétude.
- `version_formule=1` : toute révision de la formule (orientation, seuil)
  incrémentera la version, permettant la coexistence v1/v2 (EXCLUDE temporel).
- Étendre à d'autres couples (DNI SARAH-3, CAMS, ERA5-Land) suivra le même
  contrat : une grandeur d'écart par couple, `stockee`, fenêtre commune,
  confiance = `min` des entrées.
