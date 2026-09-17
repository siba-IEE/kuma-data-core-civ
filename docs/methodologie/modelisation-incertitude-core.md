# Note de conception - Modélisation de l'incertitude dans le Core

> Note de conception : comment le schéma Core représente une
> **incertitude quantifiée** attachée à une grandeur/série. Tout est ancré dans
> le schéma réel (lecture base). L'incertitude est un concept neuf pour le Core.

Le terme d'incertitude absolu relève du régime confiance A (mesure sol) et
n'est pas spécifié ici. L'incertitude disponible sans mesure sol reste
l'**écart inter-source** (`ecart_relatif_dni_cams` et les grandeurs de rang,
livrés). L'épine dorsale (b) ci-dessous est retenue ; l'option (c) est fermée.

## 0. Deux rectifications factuelles d'entrée

1. **`series_metadonnees` n'a AUCUNE colonne JSONB**. Le JSONB
   `metadonnees` vit sur **`sources.metadonnees`** (utilisé pour ERA5-Land/CAMS).
   → L'option (c) « JSONB sur `series_metadonnees` » suppose une colonne qui
   **n'existe pas** : elle implique d'en **ajouter** une.
2. **L'horaire = 6 674 360 lignes réelles** (`mesures_ressource_horaires`,
   présent en base, pas hypothétique). La volumétrie de l'option (a) est concrète.

## 1. Prior art - ce que le schéma porte déjà

### 1.1 Trois tables de mesures, même squelette

| Table | Lignes | Identité temporelle |
|---|---|---|
| `mesures_ressource` | 131 448 | `instant_mesure` (date) |
| `mesures_ressource_mensuelles` | 22 314 | `(annee, mois)` |
| `mesures_ressource_horaires` | **6 674 360** | (horodatage horaire) |

Colonnes communes pertinentes : `valeur` (double, NOT NULL), bitemporel
`valide_du`/`valide_au`, `statut` ('brut'…), **`niveau_confiance_derive`
(NOT NULL, CHECK A/B/C)** + **`niveau_confiance_override` (nullable, A/B/C)**,
`commentaire_editorial`, audit. **Aucune colonne quantitative d'incertitude.**

### 1.2 La confiance déjà présente est **qualitative**, pas quantitative

Toutes les mesures (et `grandeurs_metier`) portent `niveau_confiance_derive ∈
{A, B, C}` (100 % à `B` aujourd'hui, faute de terrain). C'est un
**palier éditorial** (A terrain / B API-modèle / C dérivé indirect), **distinct**
de l'incertitude **quantitative** (une valeur ± numérique). Les sources portent
en plus `fiabilite ∈ {haute, moyenne, faible}` (nullable). → L'incertitude
chiffrée est une **couche neuve, complémentaire** de A/B/C, qui ne la remplace pas.

### 1.3 `grandeurs_metier` : le réceptacle des grandeurs calculées

Colonnes : `grandeur_code`, `localite_id`, `series_metadonnees_id` (NOT NULL),
`periode_type ∈ {statique, mensuel, annuel}`, `annee_debut`,
`annee_fin`, `mois` (nullable), `version_formule`, `valeur` (nullable),
`niveau_confiance_derive` (A/B/C), audit. **EXCLUDE** `ex_grandeurs_metier_identite_periode`
sur `(grandeur_code, localite_id, series_metadonnees_id, periode_type,
annee_debut, annee_fin, COALESCE(mois,…))`. → granularité **par (grandeur,
localité, série, période)**, pas par point.

### 1.4 `grandeurs_referentiel` : le catalogue des grandeurs

`code`, `unite_id`, **`famille ∈ {F1, F2}`**, **`strategie_calcul ∈ {stockee,
calculee_volee}`**, `version_formule_actuelle`, `description`. Unités candidates :
`pourcent` (id 123) pour une incertitude **relative**,
`kwh_par_m2_jour` (63) / unité de la grandeur pour une **absolue**, `sans_unite` (122).

### 1.5 L'écart inter-source est **déjà bâti** comme grandeur F1

`ecart_relatif_referentiel` et `ecart_relatif_dni_cams` : **F1, `calculee_volee`,
unité `pourcent`**, matérialisés dans `grandeurs_metier`. Ils
quantifient déjà la **divergence inter-source** - composante directe de
l'« incertitude combinée » (cf. §4).

## 2. Options de représentation (évaluées, non figées)

### (a) Colonnes sur les mesures (`incertitude` / `borne_inf` / `borne_sup` par point)

| Critère | Évaluation |
|---|---|
| Granularité | **par point** (ce que demande littéralement le cahier des charges) |
| Volumétrie | **6,67 M lignes horaires × N colonnes** ; backfill des mesures existantes ; +stockage sur 3 tables auditées |
| Immutabilité / audit | **mutation de tables auditées** (trigger `kuma_log_audit` sur chaque ligne touchée) ; ALTER sur 6,67 M lignes |
| Exposition API | barre par point **native** |
| Incertitude combinée | exigerait de **pré-calculer et stocker** la combinaison par point (rigide), ou de stocker des composantes par point (très lourd) |

**Verdict** : lourd, prématuré, rigide. La promesse « barre par point » est
atteignable par calcul à la volée depuis un modèle paramétrique (b/c) sans payer
le stockage par point. **Non recommandée comme mécanisme primaire.**

### (b) Famille F1 dédiée (`incertitude_*` par série/période), matérialisée dans `grandeurs_metier`

| Critère | Évaluation |
|---|---|
| Granularité | par **(grandeur, localité, série, période)** (mensuel/annuel/statique) |
| Volumétrie | **minime** (ordre du millier de lignes, comme l'écart : 1 218 pour CAMS DNI) |
| Immutabilité / audit | **zéro modif des tables de mesures** ; miroir exact du pattern écart |
| Exposition API | valeur d'incertitude par série/période ; l'API l'**applique par point** |
| Incertitude combinée | **fit naturel** : l'écart inter-source est déjà une F1 dans `grandeurs_metier` → une grandeur d'incertitude combinée s'y agrège (cf. §4) |

**Verdict** : **fort**. Cheap, sans toucher les mesures, réutilise le pattern
prouvé (écart), composable avec l'inter-source existant.

### (c) Métadonnée de série (modèle d'incertitude + paramètres)

`series_metadonnees` **n'ayant pas de JSONB**, cette option
implique d'**ajouter** un champ (JSONB `metadonnees`, miroir de `sources.metadonnees`,
ou colonnes typées).

| Critère | Évaluation |
|---|---|
| Granularité | par **série** (le *modèle* est série-niveau) ; l'API applique par point |
| Volumétrie | **légère** (un descriptif par série, ~centaines de séries) |
| Immutabilité / audit | ALTER sur `series_metadonnees` (table petite, auditée) ; zéro modif des mesures |
| Exposition API | porte le **modèle/paramètres** (ex. `{type:'relatif+plancher', relatif_pct:8, plancher_abs:0.2}`) → barre calculée par point |
| Incertitude combinée | **insuffisante seule** : la composante inter-source est **variable dans le temps** (les écarts mensuels), pas un paramètre statique - la métadonnée la *référence*, ne la *contient* pas |

**Verdict** : excellent pour la **loi / les paramètres** (statique), pas pour les
**valeurs calculées variables**. À combiner avec (b), pas seule.

### (d) Combinaison (b)+(c) - modèle en métadonnée + valeur dérivée en grandeur

Le **modèle & paramètres** d'incertitude (la loi : % relatif de validation source
+ plancher absolu) vivent en **métadonnée de série** ; les **valeurs calculées**
(composante inter-source variable, et toute barre combinée matérialisée) vivent
en **grandeur F1** dans `grandeurs_metier`. L'API combine *à la volée* par point :
loi paramétrique (métadonnée) ⊕ écart inter-source (grandeur). **Verdict : cible
potentielle, mais le volet (c) est différé** - on retient d'abord **(b) seule**
comme épine dorsale, et (c) n'est ouvert que si un paramètre stocké par série non
exprimable comme grandeur l'impose (§5).

## 3. Question structurante - par point vs paramétrique par série

Le cahier des charges dit « pour chaque point ». La réalité : 6,67 M points
horaires, et **nous n'avons pas de vérité-terrain par point** pour justifier un
nombre *distinct* par heure - un stockage par point ne ferait que **diffuser un
nombre de niveau série** sur chaque ligne.

**Recommandation** : **incertitude paramétrique par série, appliquée par point
à la volée dans l'API.** La promesse éditoriale (barre par point) est **livrée**
par point ; le **stockage** est paramétrique (série/période), pas par ligne.
C'est à la fois **moins coûteux** (pas de 6,67 M × N) et **plus honnête** (on ne
prétend pas une résolution d'incertitude qu'on n'a pas).

**Exception** : une incertitude **réellement par point** (lecture instrument
au sol, ou flag QC ponctuel) est un **jeu petit et distinct** - stockable
par point sur sa propre table le jour venu, **sans** charger l'horaire 6,67 M.

## 4. Articulation avec l'écart inter-source déjà bâti

L'« incertitude combinée » = **barre terrain (confiance A)** ⊕
**écart inter-source (NASA/SARAH-3/CAMS)**. La composante inter-source **existe
déjà** : `ecart_relatif_dni_cams` et les grandeurs de rang, F1 `calculee_volee`
dans `grandeurs_metier`.

→ **Réutilisation, pas recalcul** : une grandeur `incertitude_combinee` (F1)
**consomme** l'écart inter-source existant comme l'une de ses composantes, plutôt
que de re-mesurer la divergence. La combinaison (ex. somme quadratique des
composantes relatives) est une formule dédiée, matérialisée/`calculee_volee`
comme les écarts. La composante terrain vient en seconde brique, avec la mesure
sol.

## 5. Synthèse / recommandation (arbitrages rendus)

1. **Pas de stockage par point** (§3) : incertitude **paramétrique par série** +
   application **par point à la volée** dans l'API. **(a) écartée** comme mécanisme
   primaire (6,67 M lignes, mutation de tables auditées, rigidité).
2. **Épine dorsale = (b)** : les **valeurs d'incertitude** (combinée, et composante
   inter-source) → **grandeur(s) F1** `incertitude_*` dans `grandeurs_metier`
   (`calculee_volee`, unité `pourcent` pour le relatif ; l'absolu **dérivé**
   `relatif × valeur` à l'API), via un **orchestrateur dédié**. Pattern
   strictement identique à l'écart.
3. **(c) - modèle en métadonnée de série : différé.** **Aucun ajout à
   `series_metadonnees`** à ce stade. Préférence affirmée : **composantes comme
   grandeurs** + orchestrateur `calculee_volee` - tout reste en
   `grandeurs_referentiel` / `grandeurs_metier`, rien de neuf côté schéma de
   série. On n'ouvre (c) (et, le cas échéant, le choix **JSONB neuf vs
   colonnes typées**) que si un **paramètre stocké par série** non exprimable
   comme grandeur l'impose.
4. **Inter-source réutilisé** (§4) : `incertitude_combinee` **consomme**
   `ecart_relatif_dni_cams` et les grandeurs de rang, ne les recalcule pas.
5. **Distinct de A/B/C** : l'incertitude chiffrée **complète** le palier qualitatif
   `niveau_confiance_derive`, ne le remplace pas.

Choix relatif **vs** absolu : **relatif (`pourcent`) primaire** (homogène entre
grandeurs, composable en somme quadratique) ; absolu **dérivé** à l'API. Granularité
de sortie : par (série, période) comme l'écart.

Tant que la contribution terrain est exprimable comme **grandeur**, (c) reste fermé.

## 6. Sources

- Lecture base : absence de JSONB sur `series_metadonnees`
  (JSONB sur `sources.metadonnees`) ; volumétrie horaire 6 674 360 ; colonnes +
  CHECK A/B/C des 3 tables de mesures et de `grandeurs_metier` ; `periode_type`
  + EXCLUDE de `grandeurs_metier` ; familles F1/F2 + écarts `ecart_relatif_*` ;
  unités `pourcent`/`kwh_par_m2_jour`/`sans_unite`.
- Code : services de grandeurs (pattern écart), sous
  `src/kuma_data_core/services/grandeurs/`.
