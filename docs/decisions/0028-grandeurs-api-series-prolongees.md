# ADR-0028 : Grandeurs métier par l'API sur les séries de l'instance

Date : 2026-10-15. Statut : accepté — appliqué dans `api/v1/grandeurs.py`
(aucune migration, aucune donnée modifiée).

## Contexte

Les 11 routes `/v1/grandeurs/*` ont été appelées sur les données gravées
(révision 0033). Quatre hypothèses héritées de l'instance d'origine les
faisaient échouer ou mentir :

| Hypothèse | Effet sur les données de l'instance |
|---|---|
| Une compagne (DNI, DHI, T2M…) a le **même `periode_debut`** que la série source | GHI NASA journalier depuis 1991, DNI/DHI depuis 2001 (ADR-0013, ADR-0016) : POA basculé **en silence** sur le repli Liu-Jordan, POA bifacial en 400 |
| La série GHI de `ghi_exceedance` est « celle qui débute en 1991 » (`LIMIT 1` sans ordre ni granularité), lue en entier | Aux 34 points journaliers, la série journalière était choisie (500) ; ailleurs, la série prolongée à 2025 (ADR-0018) donnait **35 années** étiquetées « 1991-2020 » |
| Une route journalière reçoit une série journalière | Une série mensuelle était lue dans la table journalière : **200 avec une liste vide** |
| Les écarts de l'atlas s'appellent `ecart_relatif_referentiel` / `ecart_relatif_dni_cams` et la dégénérescence de pixel est matérialisée | Ici, les écarts sont `ecart_relatif_<g>_<src>_nasa`, orientés `(comparée − nasa) / nasa` (ADR-0009, ADR-0017), et `degenerescence_pixel` n'est pas gravée à la révision 0033 : 404 partout, collection vide (et 500 dès qu'un écart serait trouvé) |

## Décision

### Compagnes : granularité et recouvrement, pas date de début

Une compagne est cherchée sur la même localité, la même source et la même
**granularité**, parmi les séries actives qui **recouvrent la période demandée**
(à défaut, la plage de la série source). Ordre déterministe : plus grand
recouvrement, puis même `periode_debut` que la source, puis `id`. Les séries
d'une même source n'ont pas toutes la même profondeur : la date de début n'est
pas une identité de famille.

### Garde de granularité

Une route F2 exige une série **journalière** (`methode=moyenne_journaliere`,
`productible_pr_fourni` admet aussi le mensuel) ou **horaire**
(`integration_horaire`) : sinon `400 VALIDATION_VALEUR_INVALIDE`. Les routes F1
`taux_salissure_proxy` et `pr_realiste` exigent une série journalière : sinon
`400 INCOMPATIBILITE_SOURCE_GRANDEUR`.

### `ghi_exceedance` : la normale reste 1991-2020

Série NASA POWER **mensuelle** couvrant 1991-2020 ; seules ses années
1991-2020, et seulement les **années complètes**, entrent dans les totaux. La
normale OMM reste la référence climatologique (ADR-0018). Les **jumeaux de
pixel** (localités dont la série 1991-2020 est strictement identique) sont
détectés à la lecture (`grouper_jumeaux_pixel`) et cités dans `limite`, à la
place d'une paire de localités codée en dur.

Une série est « climatologique » si elle **couvre** la normale :
`periode_debut <= 1991-01-01` et `periode_fin` nulle ou `>= 2020-12-31` — même
règle que la résolution des localités de l'API séries ; le service
`referentiels` (contextes du recalcul des écarts) s'y aligne aussi.

### `incertitude_inter_source` : conventions explicites

- **Paires candidates** par grandeur, dans l'ordre : `ecart_relatif_ghi_sarah3_nasa`
  puis `ecart_relatif_referentiel` (GHI) ; `ecart_relatif_dni_cams_nasa` puis
  `ecart_relatif_dni_cams` (DNI). La première portant des écarts sur la fenêtre
  est retenue. Le contrat de réponse ne change pas.
- **Une paire par grandeur, pas les sept écarts.** La fiche garde son contrat
  (GHI et DNI, une paire chacun, référence d'écart de l'atlas : SARAH-3 pour le
  GHI, CAMS pour le DNI). ERA5 est écarté : son saut de 2021 (ADR-0018) tombe
  précisément dans la fenêtre 2021-2023. Les autres écarts (ERA5, DNI SARAH-3,
  DHI CAMS) restent servis par `/v1/series` (séries `kuma_calculs`).
- **Lecture du signe** : `paire = "A vs B"` signifie que l'écart stocké vaut
  `(A − B) / B × 100` (référence nommée en second, au dénominateur). Ici :
  « PVGIS-SARAH3 vs NASA POWER » et « CAMS vs NASA POWER » ; un écart positif
  veut dire que la source comparée est au-dessus de NASA. Les valeurs sont lues
  telles quelles, jamais converties.
- **Fenêtre 2021-2023 conservée** : commune à SARAH-3 (servi jusqu'en 2023) et
  à CAMS.
- **Dégénérescence de pixel** : lue si la grandeur `degenerescence_pixel` est
  gravée (ligne rattachée à la série GHI NASA POWER mensuelle) ; sinon
  **détectée à la lecture** par égalité exacte des séries GHI NASA POWER
  mensuelles 1991-2020 (même méthode que la grandeur), confiance B. C'est un
  test d'égalité sur la donnée brute, pas un calcul de substrat ; une requête
  d'environ 70 ms pour les 142 localités. Une fiche ne tombe donc plus en
  erreur 500 quand la grandeur n'est pas (encore) gravée.

## Résultat

Base `kuma_p1` (révision 0033) :

- Séries GHI NASA mensuelles 1991-2020 : **142 séries, 35 vecteurs distincts** ;
  8 localités résolues, plus grand groupe de jumeaux : 12 localités.
- `ghi_exceedance` : `civ_dep_abidjan` passe d'une erreur 500 à P50 1 718,8 /
  P90 1 679,6 kWh/m²/an sur 30 ans ; `civ_dep_aboisso` passe de 1 683,5 (35 ans)
  à 1 686,1 kWh/m²/an (30 ans).
- `incertitude_inter_source` : 142 fiches au lieu de 0. Exemple
  `civ_dep_abidjan` : GHI SARAH-3 vs NASA, médiane |écart| 6,70 %, moyenne
  +7,29 % ; DNI CAMS vs NASA, 29,63 % et +30,44 % ; 6 jumeaux de pixel.
- POA paramétrable aux 34 points journaliers : Perez avec DNI/DHI réels au lieu
  du repli Liu-Jordan ; POA bifacial calculé au lieu d'une 400.

## Conséquences

- Les routes qui attendent des séries pas encore gravées (T2M, précipitation et
  albédo journaliers NASA POWER, PM2.5/PM10 journaliers CAMS EAC4) répondent
  par une 400 explicite ; leurs tests d'intégration sont prêts et s'activent
  dès que les séries existent.
- **Limite connue, non corrigée ici** : en `moyenne_journaliere`, Perez applique
  des totaux journaliers au midi solaire (biais L-TR-6). À inclinaison nulle, le
  POA vaut `DNI cos(z) + DHI` et non le GHI : de 0,75 à 1,30 fois le GHI selon
  le jour, entre −2,2 % et +3,4 % sur l'année 2022 aux trois points testés
  (Abidjan, Korhogo, Tonkpi). Le repli Liu-Jordan, lui, restitue exactement le
  GHI.
- La référence de l'API (§ 3.7) doit refléter ces règles.
