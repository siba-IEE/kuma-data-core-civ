# Référence de l'API Kuma Data Core

> Référence technique de l'API, dérivée du code (routeurs, schémas
> Pydantic, règles de confiance) et des seeds. Le catalogue et les
> volumes se découvrent via l'API elle-même (listing `/v1/series`, doc
> interactive `/docs`), pas via des compteurs figés dans ce document :
> ils dépendent du mode d'ingestion du déploiement.
>
> Aucun secret n'est exposé : les clés API, URL internes et chemins
> d'infrastructure sont décrits en termes de mécanismes, jamais en
> valeurs.

## 1. Vue d'ensemble de l'API

Kuma Data Core expose une API HTTP qui sert de source de vérité aux
outils Kuma (média éditorial, scripts de synchronisation, Solar Bridge,
autres outils dérivés) et, sur le profil serveur public (édition
publiée, ADR-0003), aux consommateurs tiers munis d'une clé
self-service. Elle n'est pas destinée à un accès anonyme : tous les
endpoints métier exigent une clé API (administrative ou self-service).

| Aspect | Choix |
|---|---|
| Style | REST, JSON par défaut, CSV optionnel sur `series/{code}`, `grandeurs/*` (F2) et `horaire/*` |
| Framework | FastAPI (Python 3.12) |
| Base de données | PostgreSQL 16 |
| Versioning | Préfixe `/v1`. Contrat stable une fois publié, breaking changes documentés par décision d'architecture |
| Authentification | Header `Authorization: Bearer <cle>` |
| Format d'erreur | Enveloppe normalisée `{"erreur": {"code": ..., "message": ..., "details": ...}}` |
| Documentation interactive | OpenAPI à `/docs` et `/redoc` (dev/intégration uniquement, désactivée en production par validateur de configuration) |
| Schéma OpenAPI brut | `/openapi.json` (mêmes conditions) |

Base URL : les exemples utilisent l'hôte placeholder `<base-url>`.
Toutes les routes métier vivent sous `/v1/...`.

Structure des routes :

```
/v1/health                                        santé publique (non authentifié)
/v1/health/db                                     santé infrastructure (authentifié)
/v1/edition                                       édition publiée servie (non authentifié)
/v1/cles                POST                      émission self-service d'une clé (non authentifié)
/v1/cles/{prefixe}      DELETE                    révocation d'une clé (administrateur)
/v1/series                                        catalogue des séries
/v1/series/{code_serie}                           détail d'une série + ses mesures
/v1/localites                                     référentiel géographique
/v1/localites/{code}                              détail d'une localité
/v1/grandeurs/<code>                              11 routes grandeurs (F1 calculées, F2 paramétrables)
/v1/horaire/{localite}/{grandeur}                 horaire stocké validé, repli passe-plat
/v1/horaire/{localite}/{grandeur}/disponibilite   plage temporelle disponible
```

22 endpoints en tout : santé (2), édition (1), clés (2), séries (2),
localités (2), horaire (2), grandeurs (11). Le préfixe `/v1/grandeurs/`
n'agrège pas dynamiquement, il expose 11 routes distinctes (détail
en 3.7).

## 2. Authentification et accès

### 2.1 Mécanisme

Toute requête autre que les endpoints publics (`GET /v1/health`,
`GET /v1/edition`, `POST /v1/cles`) doit présenter le header HTTP :

```
Authorization: Bearer <cle>
```

La validation se fait en 4 étapes (`api/dependencies.py:verifier_cle_api`) :

1. Présence du header, sinon `401 AUTH_HEADER_MANQUANT`
2. Préfixe `Bearer `, sinon `401 AUTH_FORMAT_INVALIDE`
3. Comparaison aux clés d'environnement (administrative, Bridge)
4. À défaut, et si une base de service est configurée : recherche de
   l'empreinte SHA-256 de la clé parmi les clés self-service actives ;
   sinon `401 AUTH_CLE_INVALIDE`

Les clés self-service actives sont soumises à un quota journalier
(section 3.11) quand le rate limiting est activé ; les clés
d'environnement ne sont jamais limitées.

### 2.2 Modèle d'accès

Deux régimes coexistent :

- **Régime local / interne** (historique) : aucun compte, aucun flux
  d'inscription. Les clés sont attribuées par l'éditeur de Kuma Data
  Core aux consommateurs autorisés, en variables d'environnement.
- **Régime serveur public** (édition publiée, ADR-0003) : inscription
  self-service légère via `POST /v1/cles` (une adresse de contact
  suffit). La clé est gratuite, montrée une seule fois, révocable, et
  porte un quota journalier. Les données servies restent publiques : la
  clé n'est pas une barrière mais une signature (traçabilité, limitation
  par consommateur, révocation ciblée).

### 2.3 Garanties techniques sans exposition de secret

- Les clés sont stockées en `SecretStr` (jamais loggées en clair).
- Les logs d'erreur ne contiennent aucune PII ni clé.
- Le filet de sécurité `handler_exception_generique` retourne un 500
  normalisé sans fuite de stack trace, de chemin interne ni de version
  de dépendance.
- L'OpenAPI est désactivée en production par validateur de
  configuration (toute incohérence bloque le démarrage de
  l'application).
- L'origine CORS est restreinte à une liste close. Aucune origine
  publique n'est autorisée par défaut.

## 3. Endpoints (détail)

### 3.1 `GET /v1/health` : santé publique

- Auth : non requise
- Réponse 200 :

```json
{
  "statut": "operationnel",
  "version": "<x.y.z>",
  "environnement": "<dev|integration|prod>",
  "edition": "edition_20260702"
}
```

- Indique que l'API répond. `edition` est lu en best-effort (identifiant
  de l'édition publiée servie, `null` hors régime édition ou si la
  lecture échoue) : le health ne dépend de rien et ne renvoie jamais de
  5xx. Le détail de l'édition vit sur `GET /v1/edition` (3.10).

### 3.2 `GET /v1/health/db` : santé détaillée

- Auth : Bearer requise
- Réponse 200 :

```json
{
  "statut": "operationnel",
  "version": "<x.y.z>",
  "environnement": "<dev|integration|prod>",
  "composants": [{"nom": "postgresql", "statut": "operationnel"}]
}
```

- Erreurs : `503 INFRASTRUCTURE_BASE_INDISPONIBLE` si la base ne répond
  pas (avec détail `composants`).
- La vérification Redis n'est pas branchée dans cet endpoint (la forme
  de réponse est prête à recevoir un second composant). Redis est
  consommé par les compteurs de quota (3.11) en mode fail-open : son
  indisponibilité n'affecte pas la santé de l'API.

### 3.3 `GET /v1/series` : listing des séries

- Auth : Bearer requise
- Pagination : offset-based, `limit` défaut 100, max 1000.
- Tri : `ORDER BY code ASC` (stable).
- Paramètres query :

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `localite` | `str` | | Filtre par code localité (ex. `gin_kindia`) |
| `grandeur` | `str` | | Filtre par code grandeur (ex. `ghi`, `hep`) |
| `source` | `str` | | Filtre par code source (ex. `nasa_power`, `kuma_calculs`) |
| `actif` | `bool` | `true` | Inclut les séries soft-deleted si `false` |
| `limit` | `int [1, 1000]` | `100` | Pagination |
| `offset` | `int >= 0` | `0` | Pagination |

- Réponse 200 (envelope paginée) :

```json
{
  "items": [
    {
      "id": 12,
      "code": "gin_conakry_ghi_nasa_power_2021_2025",
      "libelle": "GHI journalier Conakry-Kaloum 2021-2025 (NASA POWER)",
      "localite_id": 14,
      "localite_code": "gin_conakry_kaloum",
      "localite_nom": "Kaloum",
      "localite_iso3": "GIN",
      "grandeur_code": "ghi",
      "grandeur_label": "Irradiation globale horizontale",
      "grandeur_unit": "kWh/m²/jour",
      "source_id": 1,
      "source_code": "nasa_power",
      "source_label": "NASA POWER - Prediction Of Worldwide Energy Resources : Solar and Meteorological Data Archive",
      "source_url": "https://power.larc.nasa.gov/",
      "periode_debut": "2021-01-01",
      "periode_fin": "2025-12-31",
      "methode_collecte": "modele_satellitaire",
      "notes_fr": "Donnee brute GHI ingeree depuis NASA POWER, methode satellitaire ...",
      "created_at": "2026-05-11T19:30:00Z",
      "updated_at": "2026-05-11T19:30:00Z",
      "actif": true
    }
  ],
  "total": 96,
  "limit": 100,
  "offset": 0
}
```

- 18 champs par item, dénormalisés (localité, grandeur, source) pour
  éviter au consommateur de chaîner les appels. Le champ `total` reflète
  le nombre de séries matchant les filtres dans le déploiement interrogé.
- Note de stabilité : le contrat de cet endpoint est figé. Les
  renommages publics `cree_le` vers `created_at`, `modifie_le` vers
  `updated_at`, `commentaire_editorial` vers `notes_fr`, `sources.titre`
  vers `source_label` sont assumés et ne dérivent pas du nom de colonne DB.

### 3.4 `GET /v1/series/{code_serie}` : détail d'une série + mesures

- Auth : Bearer requise
- Paramètres path : `code_serie` (convention de nommage en 5.4)
- Paramètres query :

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `from` | `YYYY-MM-DD` ou `YYYY-MM` | | Borne basse temporelle inclusive |
| `to` | `YYYY-MM-DD` ou `YYYY-MM` | | Borne haute temporelle inclusive |
| `format` | `json` ou `csv` | `json` | Format de réponse |
| `limit` | `int [1, 10000]` | `1000` | Pagination des mesures |
| `offset` | `int >= 0` | `0` | Pagination |

- Résolution de la table-cible : le routeur déduit où vivent les mesures
  (`mesures_ressource` journalier, `mesures_ressource_mensuelles`
  mensuel brut, ou `grandeurs_metier` valeurs calculées Kuma via la vue
  `v_grandeurs_metier_courantes`) à partir de `source.code` et
  `periode_debut` (`api/services/serie_lecture.py`).

- Réponse 200 JSON, exemple série journalière NASA POWER :

```json
{
  "id": 12,
  "code": "gin_conakry_ghi_nasa_power_2021_2025",
  "libelle": "GHI journalier Conakry-Kaloum 2021-2025 (NASA POWER)",
  "grandeur_code": "ghi",
  "grandeur_unit": "kWh/m²/jour",
  "source_code": "nasa_power",
  "periode_debut": "2021-01-01",
  "periode_fin": "2025-12-31",
  "unite_code": "kwh_par_m2_jour",
  "mesures": [
    {
      "type": "journalier",
      "instant_mesure": "2024-06-15",
      "valeur": 5.83,
      "niveau_confiance_derive": "B",
      "niveau_confiance_override": null,
      "niveau_effectif": "B",
      "statut": "brut"
    }
  ]
}
```

(Les champs d'en-tête dénormalisés sont identiques à ceux du listing,
omis ici pour la lisibilité.)

- Trois formes de mesures discriminées (champ `type`) :

  - `journalier` : `instant_mesure: date`, `valeur: float`
  - `mensuel` : `annee: int`, `mois: int`, `valeur: float`
  - `grandeur_metier` : `periode_type` (`mensuel`, `annuel`, `statique`),
    `annee_debut`, `annee_fin`, `mois` (nullable), `version_formule: int`,
    `valeur: float`

  Tous portent en plus `niveau_confiance_derive`,
  `niveau_confiance_override`, `niveau_effectif` (résolu) et `statut`
  (voir 5.2 et 5.3).

- Format CSV (`format=csv`) : header générique `code_serie, type, annee,
  mois, instant_mesure, periode_type, annee_debut, annee_fin,
  version_formule, valeur, niveau_effectif, statut`, une ligne par mesure.

- Erreur 404 : `RESSOURCE_SERIE_INCONNUE` si le code de série n'existe pas.

### 3.5 `GET /v1/localites` : référentiel géographique (listing)

- Auth : Bearer requise
- Pagination : offset-based, `limit` défaut 100, max 1000.
- Tri : `ORDER BY code ASC`.
- Paramètres query :

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `pays_iso3` | `str` | | Filtre ISO 3166-1 alpha-3 (ex. `GIN`) |
| `type_localite` | `str` | | `continent`, `region_supranationale`, `pays`, `region_administrative`, `commune`, `site` |
| `parent_code` | `str` | | Filtre par code de la localité parente |
| `actif` | `bool` | `true` | Inclut les soft-deleted si `false` |
| `limit` | `int [1, 1000]` | `100` | Pagination |
| `offset` | `int >= 0` | `0` | Pagination |

- Réponse 200, exemple Kindia :

```json
{
  "items": [
    {
      "id": 13,
      "code": "gin_kindia",
      "nom": "Kindia",
      "type_localite": "commune",
      "parent_id": 7,
      "parent_code": "gin_kindia_region",
      "pays_iso3": "GIN",
      "latitude": 10.04972222,
      "longitude": -12.85416667,
      "altitude_metres": 368,
      "population_estimee": 169119,
      "annee_population": 2014,
      "fuseau_horaire": "Africa/Conakry",
      "created_at": "2026-05-10T09:00:00Z",
      "updated_at": "2026-05-10T09:00:00Z",
      "actif": true
    }
  ],
  "total": 20,
  "limit": 100,
  "offset": 0
}
```

- 16 champs par item. `parent_code` dénormalisé via self-JOIN : un appel
  suffit pour reconstruire la hiérarchie ligne par ligne. La hiérarchie
  récursive complète (chaîne `pays > région > commune`) n'est pas exposée
  v1.

### 3.6 `GET /v1/localites/{code}` : détail d'une localité

- Auth : Bearer requise
- Paramètres path : `code` (slug ASCII pour racines, ou
  `<code_pays>_<slug>` pour entités administratives, voir 5.5).
- Réponse 200 : identique à un item du listing (16 champs).
- Erreur 404 : `RESSOURCE_LOCALITE_INCONNUE`.
- Pas de filtre `actif` sur le détail : qui appelle un code précis assume
  la ressource ciblée.

### 3.7 Les 11 routes `GET /v1/grandeurs/<code>`

Le préfixe `/v1/grandeurs/` expose 11 routes : 6 grandeurs F2
paramétrables (calcul à la volée piloté par des paramètres physiques
utilisateur) et 5 routes F1 calculées à la volée (dérivations sans
paramètre libre, path-based).

| Route | Famille | Sortie |
|---|---|---|
| `GET /v1/grandeurs/poa_parametrable` | F2 | journalier ou horaire |
| `GET /v1/grandeurs/poa_bifacial` | F2 | journalier ou horaire |
| `GET /v1/grandeurs/productible_correction_thermique` | F2 | journalier ou horaire |
| `GET /v1/grandeurs/productible_pr_fourni` | F2 | journalier, mensuel ou horaire |
| `GET /v1/grandeurs/energie_utile_ecs` | F2 | journalier ou horaire |
| `GET /v1/grandeurs/degre_jour_climatisation` | F2 | mensuel |
| `GET /v1/grandeurs/ghi_exceedance/{code_localite}` | F1 | fiche P50/P90 |
| `GET /v1/grandeurs/taux_salissure_proxy/{code_serie_source}` | F1 | journalier |
| `GET /v1/grandeurs/pr_realiste/{code_serie_source}` | F1 | journalier + mensuel |
| `GET /v1/grandeurs/incertitude_inter_source/{code_localite}` | F1 | fiche |
| `GET /v1/grandeurs/incertitude_inter_source` | F1 | collection paginée |

#### 3.7.1 Modèles physiques (F2)

| Route | Modèle de référence |
|---|---|
| `poa_parametrable` | Perez 1990 si DNI+DHI disponibles, sinon fallback Liu-Jordan isotrope (décomposition Erbs 1982) |
| `poa_bifacial` | Infinite-sheds row-aware (pvlib), face arrière : DNI+DHI obligatoires, pas de fallback |
| `productible_correction_thermique` | NOCT simple (Ross 1980) |
| `productible_pr_fourni` | PR brut (Marion 2005) ou PR_T corrigé température (Dierauf 2013) |
| `energie_utile_ecs` | Hottel-Whillier-Bliss bord-capteur (η = η₀ − a₁·ΔT/G − a₂·ΔT²/G) |
| `degre_jour_climatisation` | Moyenne journalière (défaut) ou intégration horaire (Erbs 1983), agrégation mensuelle |

#### 3.7.2 Paramètres communs des routes F2

| Paramètre | Type | Obligatoire | Description |
|---|---|---|---|
| `code_serie_source` | `str (1..80)` | oui | Code d'une série F1 source (ex. `gin_conakry_ghi_nasa_power_2021_2025`) |
| `periode_debut` | `YYYY-MM-DD` | oui | Borne basse inclusive |
| `periode_fin` | `YYYY-MM-DD` | oui | Borne haute inclusive, `>= periode_debut` |
| `format` | `json` / `csv` | non | `json` par défaut |

#### 3.7.3 Paramètres spécifiques par route F2

| Route | Paramètres techniques |
|---|---|
| `poa_parametrable` | `inclinaison_deg` `[0..90]`, `orientation_deg` `[0..360[` (0=N, 90=E, 180=S, 270=O), `albedo_sol` `[0..1]` (défaut 0.2), `methode` `moyenne_journaliere` (défaut) ou `integration_horaire` |
| `poa_bifacial` | `inclinaison_deg` `[0..90]`, `orientation_deg` `[0..360[`, `gcr` `]0..1]`, `hauteur_m > 0`, `pitch_m > 0`, `bifacialite` `[0..1]` (défaut 0.8), `albedo_sol` `[0..1]` (repli si série `albedo_surface` absente), `methode` |
| `productible_correction_thermique` | `noct_degc` `[40..50]`, `coeff_temp_pourcent_par_degc` `[-0.6..-0.1]`, `puissance_stc_wc > 0`, `methode` |
| `productible_pr_fourni` | `pr_fourni` `[0..1]`, `correction` `aucune` ou `temperature`, `puissance_stc_wc > 0`, `noct_degc` et `coeff_temp_pourcent_par_degc` (obligatoires si `correction=temperature`), `methode` |
| `energie_utile_ecs` | `rendement_optique_eta0` `[0.5..0.9]`, `pertes_lineaires_a1` `[1..8]` W/(m²·K), `pertes_quadratiques_a2` `[0..0.05]` W/(m²·K²), `temperature_fluide_entree_degc` `[10..90]`, `methode` |
| `degre_jour_climatisation` | `base_temperature_degc` `[10..35]`, `methode` |

`methode=integration_horaire` exige une série source de granularité
`horaire` (plus les compagnes horaires requises) ; elle lève le biais de
moyennage journalier. Une série non horaire avec ce mode renvoie
`400 VALIDATION_VALEUR_INVALIDE`.

#### 3.7.4 Pattern auto-compagne (F2)

Plusieurs routes F2 ont besoin de plusieurs séries d'entrée. Le routeur
cherche automatiquement les séries compagnes sur la même `localite_id` +
`source_id` + granularité + fenêtre temporelle. Le consommateur fournit
uniquement la série principale.

| Route | Série principale | Compagnes auto | Si compagne manquante |
|---|---|---|---|
| `poa_parametrable` | `grandeur_code=ghi` | DNI, DHI | Fallback Liu-Jordan (précision dégradée en ciel partiellement couvert) |
| `poa_bifacial` | `ghi` | DNI, DHI (albédo via `albedo_surface`) | `400 INCOMPATIBILITE_SOURCE_GRANDEUR` (pas de fallback) |
| `productible_correction_thermique` | `ghi` | T2M | `400 INCOMPATIBILITE_SOURCE_GRANDEUR` |
| `productible_pr_fourni` (`correction=aucune`) | `ghi` | | |
| `productible_pr_fourni` (`correction=temperature`) | `ghi` | T2M | `400 INCOMPATIBILITE_SOURCE_GRANDEUR` |
| `energie_utile_ecs` | `ghi` | T2M | `400 INCOMPATIBILITE_SOURCE_GRANDEUR` |
| `degre_jour_climatisation` | `t2m` | aucune | |

Pour `productible_pr_fourni`, la table-cible est dispatchée selon la
source : une série mensuelle climatologique n'accepte que
`correction=aucune` ; une série calculée Kuma (`kuma_calculs`) est
rejetée en `400 INCOMPATIBILITE_SOURCE_GRANDEUR` (une F1 calculée n'est
pas admissible comme source brute d'un calcul F2).

#### 3.7.5 Format de réponse F2 (JSON)

```json
{
  "code_grandeur": "poa_parametrable",
  "code_serie_source": "gin_conakry_ghi_nasa_power_2021_2025",
  "parametres_appliques": {
    "inclinaison_deg": 20.0,
    "orientation_deg": 180.0,
    "albedo_sol": 0.2,
    "methode": "moyenne_journaliere"
  },
  "resultats": [
    {
      "granularite": "journalier",
      "instant": "2024-01-01",
      "valeur": 5.83,
      "unite": "kWh/m²/jour",
      "niveau_confiance": "B"
    }
  ]
}
```

Résultats discriminés par `granularite` : `journalier` (`instant: date`)
ou `mensuel` (`instant` au format `YYYY-MM`). `degre_jour_climatisation`
sort en mensuel. Le niveau de confiance des sorties F2 est `B`.

Format CSV (`format=csv`) : header `granularite, instant, valeur, unite,
niveau_confiance`.

#### 3.7.6 Routes F1 calculées à la volée

Ces routes dérivent une grandeur éditoriale à partir de séries déjà
ingérées ou déjà matérialisées, sans paramètre physique libre. Toutes
portent un champ `limite` : un avertissement éditorial explicite sur la
portée du résultat.

`ghi_exceedance/{code_localite}` : exceedance inter-annuelle P50/P90 de
l'irradiation annuelle, dérivée de la série GHI mensuelle climatologique
1991-2020 de la localité. P50 = médiane, P90 = percentile 10 (scénario
conservateur, P90 < P50 par construction). Réponse : `p50`, `p90` en
kWh/m²/an, `base_annees`, `methode_percentile`, `niveau_confiance`,
`limite`. 404 `RESSOURCE_LOCALITE_INCONNUE` si la localité n'a pas de
série climatologique. Le `limite` signale que c'est de la variabilité
inter-annuelle, pas un P90 bancable propageant l'incertitude de modèle.

`taux_salissure_proxy/{code_serie_source}` : perte de transmission par
salissure (`% = (1 − ratio HSU) × 100`, modèle HSU pvlib), à partir
d'une série PM2.5 (source `cams_eac4`). Compagnes automatiques : PM10
(même source) et précipitation journalière (source `nasa_power`,
résolveur cross-source dédié). Alignement par intersection des dates,
garde-fou de contiguïté (le modèle HSU est path-dependant). Réponse :
`mesures` (perte par jour), `surface_tilt_deg`, `cleaning_threshold_mm`,
`limite`. 400 `INCOMPATIBILITE_SOURCE_GRANDEUR` si la série n'est pas une
PM2.5 ou si une compagne manque.

`pr_realiste/{code_serie_source}` : PR effectif site-spécifique = `PR
fourni × ratio thermique × (1 − salissure)` selon le mode `correction`
(`aucune`, `temperature`, `salissure`, `temperature_salissure`, défaut
`temperature_salissure`). Série source = GHI ; compagnes selon le mode
(T2M et pluie même source, PM cross-source `cams_eac4`). Paramètres
query : `pr_fourni` `[0..1]`, `correction`, `noct_degc` et
`coeff_temp_pourcent_par_degc` (obligatoires si la correction inclut la
température, sinon `422 VALIDATION_CHAMP_MANQUANT`). Réponse :
`mesures_journalier` et `mesures_mensuel` (la courbe mensuelle est la PR
saisonnière), `limite`.

`incertitude_inter_source/{code_localite}` : fiche d'incertitude
inter-source d'une localité, en lecture/assemblage de grandeurs déjà
matérialisées (aucun calcul de substrat). Deux axes distincts, non
fusionnés : `ecarts` (écart inter-source par paire de sources et
grandeur, GHI = NASA POWER vs SARAH-3, DNI = NASA POWER vs CAMS, fenêtre
2021-2023) et `degenerescence` (propriété niveau-localité liée à la
grille CERES). `ecart_abs_pct` (médiane des écarts absolus mensuels) est
le signal primaire ; `ecart_signe_pct` est orientationnel, jamais une
correction de biais. `niveau_confiance` : B, lu et vérifié (jamais A :
inter-source, pas terrain). 404 `RESSOURCE_LOCALITE_INCONNUE` si la
localité n'est pas couverte par l'atlas.

`incertitude_inter_source` (collection) : toutes les fiches des points
de l'atlas, paginées, enveloppe identique à `/v1/series` (`items`,
`total`, `limit`, `offset`). Chaque item est la fiche par-localité
augmentée de `latitude_deg`/`longitude_deg`, pour poser chaque point sur
une carte sans second appel. Le périmètre est data-driven (les localités
portant l'écart inter-source récent), robuste à une densification.

#### 3.7.7 Erreurs des routes grandeurs

| Code | HTTP | Condition |
|---|---|---|
| `RESSOURCE_SERIE_INCONNUE` | 404 | `code_serie_source` introuvable |
| `RESSOURCE_LOCALITE_INCONNUE` | 404 | localité hors périmètre de la route F1 |
| `INCOMPATIBILITE_SOURCE_GRANDEUR` | 400 | série de mauvaise grandeur, source non admissible, ou compagne requise absente |
| `VALIDATION_VALEUR_INVALIDE` | 422 ou 400 | paramètre Pydantic hors plage, ou `integration_horaire` sur série non horaire |
| `VALIDATION_CHAMP_MANQUANT` | 422 | paramètre conditionnel obligatoire absent |

### 3.8 `GET /v1/horaire/{localite}/{grandeur}`

Localités : toute localité du référentiel par son **code complet**
(ex. `gin_kankan`) ; les codes courts historiques des 6 villes
pilotes (`kankan`, `kindia`...) restent acceptés en alias de
compatibilité. Un code inconnu répond 404
`RESSOURCE_LOCALITE_INCONNUE` (et non plus 422 : l'énumération fermée
a disparu avec la généricité pays).

Cet endpoint sert d'abord l'horaire stocké et validé par contrôle
qualité, avec repli passe-plat sur la source amont sinon. Il n'est plus
un pur passe-plat.

Comportement :

1. Si une série horaire stockée couvre la plage demandée, l'endpoint
   renvoie les points validés (`mesures_ressource_horaires`, statut
   `valide_auto`, confiance B). Les lignes rejetées par le contrôle
   qualité (statut `brut`) sont exclues.
2. Sinon, l'API relaie la requête vers le service amont (NASA POWER),
   convertit la réponse au format Kuma et l'étiquète
   `passe_plat_non_valide`.

Le champ `statut_editorial` de chaque point vaut donc `valide_auto`
(stocké validé) ou `passe_plat_non_valide` (relais non validé).

- Auth : Bearer requise
- Paramètres path :

| Paramètre | Valeurs autorisées |
|---|---|
| `{localite}` | `conakry_kaloum`, `kankan`, `kindia`, `labe`, `mamou`, `nzerekore` |
| `{grandeur}` | `ghi`, `dni`, `dhi`, `t2m`, `rh2m`, `kt` |

- Paramètres query :

| Paramètre | Type | Plage | Obligatoire |
|---|---|---|---|
| `periode_debut` | `YYYY-MM-DD` | `>= 2001-01-01` | oui |
| `periode_fin` | `YYYY-MM-DD` | `>= periode_debut`, plage `<= 366` jours | oui |
| `format` | `json` / `csv` | | non (`json` défaut) |

- Réponse 200 JSON :

```json
{
  "localite": "kankan",
  "grandeur": "ghi",
  "periode_demandee": {
    "debut": "2018-06-01",
    "fin": "2018-06-02"
  },
  "resultats": [
    {
      "instant": "2018-06-01T00:00:00",
      "valeur": null,
      "unite": "Wh/m²",
      "statut_editorial": "valide_auto"
    },
    {
      "instant": "2018-06-01T12:00:00",
      "valeur": 893.4,
      "unite": "Wh/m²",
      "statut_editorial": "valide_auto"
    }
  ]
}
```

- 24 points par jour, instant en UTC.
- `valeur: null` pour les heures où l'indice n'est pas physiquement
  défini (cas `kt` la nuit) ou une donnée manquante amont en mode repli.
- Format CSV : header `instant, valeur, unite, statut_editorial`.

### 3.9 `GET /v1/horaire/{localite}/{grandeur}/disponibilite`

Retourne la plage temporelle utilisable pour cette grandeur.

- Auth : Bearer requise
- Réponse 200 :

```json
{
  "localite": "kindia",
  "grandeur": "ghi",
  "plage_disponible": {
    "debut": "2001-01-01",
    "fin": "2025-12-13"
  },
  "statut_editorial": "passe_plat_non_valide"
}
```

- `debut` est fixé à `2001-01-01` (borne historique du substrat solaire
  amont).
- `fin` est dynamique : `aujourd'hui − 5 mois − 1 jour` (reflète la
  latence temps-réel du service amont).

### 3.10 `GET /v1/edition` : édition publiée servie

Fraîcheur affichée (ADR-0003, D7) : chaque déploiement public sert une
édition datée de la base de référence, et l'API dit laquelle.

- Auth : non requise (même statut public que `/v1/health`)
- Réponse 200 :

```json
{
  "edition_id": "edition_20260702",
  "date_publication": "2026-07-02",
  "revision_source": "<hash git court>",
  "couverture_resumee": {
    "localites": 81,
    "series": 1388
  }
}
```

- `revision_source` désigne la révision du dépôt public au moment de
  l'export de l'édition. Les métadonnées sont injectées par le script
  d'export dans l'édition elle-même, jamais devinées côté serveur.
- Erreurs : `404 RESSOURCE_INTROUVABLE` si le déploiement ne sert pas
  une édition publiée (base de développement) - c'est l'état normal du
  régime local.

### 3.11 `POST /v1/cles` et `DELETE /v1/cles/{prefixe}` : clés self-service

Cycle de vie des clés self-service (ADR-0003, D3). Disponible sur le
profil serveur public uniquement : sans base de service configurée,
l'émission renvoie `404 CLES_EMISSION_NON_ACTIVEE`.

**Émission** - `POST /v1/cles`, non authentifié (c'est l'inscription) :

```json
{"email": "dev@exemple.org", "usage_prevu": "outil de dimensionnement"}
```

- Réponse 201 :

```json
{
  "cle": "kuma_<43 caractères URL-safe>",
  "prefixe": "kuma_xxxxxxxx",
  "quota_journalier": 5000
}
```

- La clé est montrée **une seule fois** : le serveur n'en conserve que
  l'empreinte SHA-256. Le `prefixe` est l'identifiant public de la clé
  (support, révocation).
- L'émission est bornée par adresse IP (3 par 24 h glissantes) :
  `429 CLES_LIMITE_EMISSION_ATTEINTE` au-delà. C'est la seule surface
  d'écriture publique du serveur.

**Quota journalier** : chaque requête authentifiée par une clé
self-service consomme son quota du jour (fenêtre calendaire UTC,
compteur Redis indexé sur l'empreinte). Dépassement :
`429 CLES_QUOTA_JOURNALIER_DEPASSE`. Le compteur est fail-open : une
panne du cache ne rend pas les données indisponibles. Les clés
d'environnement ne sont jamais limitées.

**Révocation** - `DELETE /v1/cles/{prefixe}`, réservé à la clé
administrateur. Révoque (soft delete) toutes les clés actives du
préfixe ; `404 RESSOURCE_INTROUVABLE` si aucune. Une clé valide mais
non administrative reçoit le même `401 AUTH_CLE_INVALIDE` qu'une clé
inconnue.

### 3.11 bis `GET /v1/localites/resolution` : résolution d'un point quelconque

Authentifié. Paramètres : `lat` (`[-90, 90]`), `lon` (`[-180, 180]`),
`grandeur` (optionnel, `ghi` seul admis à ce stade).

Pour un point WGS84 quelconque, retourne la localité du référentiel
dont la climatologie mensuelle (période de référence 1991-2020)
échantillonne la **cellule de grille** contenant le point. La grille
de la source de climatologie est de 1 degré x 1 degré, frontières aux
degrés entiers (vérification empirique du 2026-07-20 : la moyenne
1991-2020 de la série de Kérouané reproduit le relevé au point de
Tokounou, même cellule, écart nul sur les 12 mois).

Le plus-proche-voisin naïf est faux et c'est la raison d'être de
l'endpoint : la localité la plus proche d'un point peut appartenir à
une autre cellule (Tokounou est à ~74 km de Kankan mais dans la
cellule échantillonnée par Kérouané, ~99 km). La résolution est un
savoir éditorial du Core, pas des consommateurs (ADR-0004).

Réponse : `point`, `grandeur`, `cellule` (bornes de la cellule),
`localite` (`code`, `nom`, coordonnées), `distance_km`,
`meme_cellule`, et `serie_climatologie` : le code de la série de
climatologie mensuelle de la localité retenue - le Core dit quelle
série consommer pour ce point, les clients ne le reconstruisent
jamais par convention de nommage (généricité pays). Quand aucune candidate ne partage la cellule,
`meme_cellule` vaut `false` et la candidate la plus proche est
renvoyée : le consommateur affiche alors l'hypothèse de transport.
404 `RESSOURCE_INTROUVABLE` si le référentiel ne porte aucun point
d'ingestion pour la grandeur.

### 3.11 ter `GET /v1/calage/{localite}/{grandeur}` : référentiel de calage satellite/sol

Authentifié. Codes localité complets (`gin_kankan`), alignés sur
`/v1/series` et `/v1/localites`.

Sert les biais saisonniers satellite moins sol mesurés aux stations
de référence, publiés comme donnée éditoriale de l'édition (table
`referentiels_calage`, ADR-0004) : pour chaque saison, le nom, les
mois couverts, le biais relatif mesuré et le facteur dérivé
`k = 1 / (1 + biais)`. La réponse porte la provenance (note de
calage, script reproductible, série sol de référence) et la portée
de transport : jamais un nombre nu.

Première entrée du référentiel : le GHI de la station ESMAP/WAPP de
Kankan (harmattan +4,4 %, mousson +1,5 %, intersaison +1,9 %). 404
`RESSOURCE_INTROUVABLE` pour un couple sans référentiel publié.

`GET /v1/calage` (sans paramètre) liste les référentiels publiés :
une entrée par référentiel avec station, grandeur, version, **série
sol de fondation** (`serie_sol` : la séquence horaire de référence à
utiliser avec ce calage) et localités couvertes. C'est l'endpoint de
découverte des consommateurs d'étude : ajouter une station = publier
son référentiel, aucun changement côté consommateurs. Le détail
porte aussi `serie_sol`.

La réponse porte aussi le **domaine de couverture** du transport
(`localites_couvertes`, `justification_couverture`) : les codes des
localités qualifiées pour appliquer ce calage (couverture
progressive, ADR-0004). Domaine initial : les 5 communes points
d'ingestion de la région administrative de Kankan. Un consommateur
d'étude calée doit vérifier que la localité résolue de son site en
fait partie ; l'extension du domaine passe par la recherche et les
éditions, jamais par les consommateurs.

### 3.12 Codes d'erreur exposés par l'API

| Code | Statut HTTP type | Sens |
|---|---|---|
| `AUTH_HEADER_MANQUANT` | 401 | header `Authorization` absent |
| `AUTH_FORMAT_INVALIDE` | 401 | préfixe `Bearer ` manquant |
| `AUTH_CLE_INVALIDE` | 401 | clé absente du jeu valide |
| `VALIDATION_CHAMP_MANQUANT` | 422 | champ requis absent |
| `VALIDATION_VALEUR_INVALIDE` | 422 / 400 | valeur hors plage Pydantic, ou mode horaire sur série non horaire |
| `VALIDATION_FORMAT_DATE_INVALIDE` | 400 | date pas `YYYY-MM-DD` ni `YYYY-MM` |
| `VALIDATION_FORMAT_NON_SUPPORTE` | 400 | format autre que `json` ou `csv` |
| `VALIDATION_LIMIT_HORS_BORNES` | 400 | `limit` hors `[1, max]` |
| `RESSOURCE_INTROUVABLE` | 404 | code générique de ressource manquante |
| `RESSOURCE_SERIE_INCONNUE` | 404 | série introuvable |
| `RESSOURCE_LOCALITE_INCONNUE` | 404 | localité introuvable |
| `GRANDEUR_F2_INCONNUE` | 404 | grandeur F2 hors catalogue |
| `INCOMPATIBILITE_SOURCE_GRANDEUR` | 400 | série incompatible ou compagne manquante |
| `PLAGE_TEMPORELLE_NON_DISPONIBLE` | 400 | requête horaire hors plage utilisable (ou hors stocké en profil édition figée) |
| `PASSE_PLAT_INDISPONIBLE` | 503 | service amont temporairement indisponible |
| `CLES_EMISSION_NON_ACTIVEE` | 404 | self-service de clés non disponible sur ce déploiement |
| `CLES_LIMITE_EMISSION_ATTEINTE` | 429 | limite d'émission de clés par IP atteinte |
| `CLES_QUOTA_JOURNALIER_DEPASSE` | 429 | quota journalier de la clé self-service dépassé |
| `INFRASTRUCTURE_BASE_INDISPONIBLE` | 503 | PostgreSQL injoignable |
| `INFRASTRUCTURE_CACHE_INDISPONIBLE` | 503 | cache (Redis) indisponible (déclaré, non levé : les compteurs sont fail-open) |
| `SERVEUR_ERREUR_INTERNE` | 500 | filet de sécurité, aucune fuite technique |

Le contrat des codes est stable : un code publié ne change pas de sens,
ne disparaît pas. Pour faire évoluer, un nouveau code est créé.

## 4. Les grandeurs disponibles

Le catalogue des grandeurs vit dans la table `grandeurs_referentiel` et
se découvre via l'API. Chaque grandeur expose :

- `code` : identifiant ASCII stable, snake_case (ex. `ghi`, `hep`).
- `libelle` : titre humain (ex. Irradiation globale horizontale).
- `unite` : code et symbole d'unité issus de la table `unites`.
- `famille` : `F1` (ontologique) ou `F2` (paramétrable, calcul
  nécessitant des paramètres utilisateur).
- `strategie_calcul` : `stockee` (persistée) ou `calculee_volee`
  (recalculée à chaque consultation).
- `version_formule_actuelle` : compteur applicatif, incrémenté à chaque
  révision méthodologique.

### 4.1 Grandeurs brutes ingérées depuis sources externes (F1 stockée)

| Code | Libellé | Unité Kuma | Source primaire | Paramètre amont | Méthode amont |
|---|---|---|---|---|---|
| `ghi` | Irradiation globale horizontale | kWh/m²/jour | NASA POWER | `ALLSKY_SFC_SW_DWN` | CERES SYN1deg + FLASHFlux |
| `dni` | Irradiation normale directe | kWh/m²/jour | NASA POWER, CAMS | `ALLSKY_SFC_SW_DNI` | CERES SYN1deg |
| `dhi` | Irradiation diffuse horizontale | kWh/m²/jour | NASA POWER | `ALLSKY_SFC_SW_DIFF` | CERES SYN1deg + FLASHFlux |
| `t2m` | Température à 2 m | °C | NASA POWER | `T2M` | MERRA-2 GMAO |
| `rh2m` | Humidité relative à 2 m | % | NASA POWER | `RH2M` | MERRA-2 GMAO |
| `kt` | Indice de clarté (`ghi` / extraterrestre) | sans dimension | NASA POWER | `ALLSKY_KT` | CERES SYN1deg + FLASHFlux |
| `precipitation` | Précipitation | mm/jour | NASA POWER | | MERRA-2 GMAO |
| `pm2_5`, `pm10` | Particules fines / grossières | µg/m³ | CAMS EAC4 | | réanalyse atmosphérique |
| `vent`, `albedo_surface` | Vent, albédo de surface | m/s, sans dimension | NASA POWER | | modèle satellitaire / réanalyse |

Les grandeurs radiatives et météo de base sont ingérées en journalier.
Le GHI est aussi disponible en mensuel : climatologie NASA POWER
1991-2020 (référence inter-temporelle) et SARAH-3 2021-2023 (cross-check
mensuel). Le DNI dispose d'un cross-check CAMS. Une partie du substrat
existe en horaire (voir 4.5). Les grandeurs et fenêtres exactes présentes
se lisent via `/v1/series`.

### 4.2 Grandeurs F1 stockée calculées par Kuma (couche éditoriale)

Calculées à partir des grandeurs brutes, persistées dans
`grandeurs_metier`, exposées via la vue `v_grandeurs_metier_courantes`.

| Code | Libellé | Unité | Calcul | Source amont |
|---|---|---|---|---|
| `hep` | Heures équivalentes pleines | h_eq | Convention `1 kWh/m²/j <-> 1 h_eq/j à 1 kW/m² STC` ; agrégation mensuelle/annuelle de GHI | GHI NASA POWER |
| `fraction_diffuse` | Fraction diffuse | sans dimension | `Σ DHI / Σ GHI` sur la période | `dhi` + `ghi` NASA POWER |
| `humidex` | Indice de confort Humidex | °C apparents | Masterton & Richardson 1979, constantes Magnus | `t2m` + `rh2m` NASA POWER |
| `productible_specifique_theorique` | Productible spécifique théorique | kWh/kWc | `hep × pr_theorique`, `pr_theorique = 0.8` | `hep` calculée Kuma |
| `variabilite_journaliere` | Coefficient de variation journalier | sans dimension | CoV annuel = `σ(GHI_jour) / μ(GHI_jour)` | `ghi` NASA POWER |
| `indicateur_qualite_donnees` | Score qualité de série (1-5) | sans dimension | `0.5·complétude + 0.3·confiance_moyenne + 0.2·fiabilité_source` | méta de la série |
| `degenerescence_pixel` | Degénérescence de pixel | sans dimension | Nombre de localités partageant la cellule CERES | grille NASA CERES |

### 4.3 Grandeurs F1 calculées à la volée (référentielles)

| Code | Libellé | Unité | Calcul |
|---|---|---|---|
| `ecart_relatif_referentiel` | Écart relatif GHI à un référentiel | % | Écart d'une série mensuelle NASA POWER à SARAH-3, ou à la moyenne 1991-2020 stratifiée par mois calendaire |
| `ecart_relatif_dni_cams` | Écart relatif DNI NASA vs CAMS | % | Écart mensuel de la série DNI NASA POWER à la référence CAMS |
| `rang_referentiel_temporel` | Rang dans la climatologie 1991-2020 | sans dimension | Percentile d'une valeur mensuelle dans la distribution 1991-2020 du même mois |
| `rang_referentiel_spatial` | Rang ordinal dans le pool des villes | sans dimension | Position dans le pool des localités pour le même mois |

### 4.4 Grandeurs F2 paramétrables

Voir 3.7 pour les routes, modèles physiques et paramètres.

| Code | Libellé | Unité | Modèle physique |
|---|---|---|---|
| `poa_parametrable` | POA paramétrable | kWh/m²/jour | Perez 1990 + fallback Liu-Jordan (Erbs 1982) |
| `poa_bifacial` | POA bifacial | kWh/m²/jour | Infinite-sheds row-aware (pvlib) |
| `productible_correction_thermique` | Productible corrigé thermique | kWh/kWc/jour | NOCT simple (Ross 1980) |
| `productible_pr_fourni` | Productible avec PR fourni | kWh/kWc/jour | PR brut (Marion 2005) ou PR_T (Dierauf 2013) |
| `energie_utile_ecs` | Énergie utile ECS bord-capteur | kWh/m²/jour | Hottel-Whillier-Bliss 1958 |
| `degre_jour_climatisation` | Degrés-jours de climatisation | °C·j | Moyenne journalière ou Erbs 1983 |

### 4.5 Grandeurs horaires

Une partie du substrat solaire existe en granularité horaire (GHI, DNI,
DHI, T2M et compagnes selon la localité), stockée dans
`mesures_ressource_horaires` avec passage par contrôle qualité (statut
`valide_auto`, confiance B). Ces séries alimentent l'endpoint horaire
(3.8) et le mode `integration_horaire` des routes F2. La couverture
horaire par localité se découvre via `/v1/series` (filtre sur la
granularité).

### 4.6 Détails méthodologiques

Le dépôt contient une fiche méthodologique par grandeur calculée Kuma
sous `docs/methodologie/grandeurs/`. Chacune documente définition
formelle, politique de complétude, hypothèses physiques, limites et
historique des versions de formule.

## 5. Structure des données et doctrine

### 5.1 Doctrine des 3 couches de sources

La doctrine éditoriale classe chaque source dans une des 3 couches.

- Couche A, calibration terrain : mesures sol locales. La première ancre
  réelle est la campagne ESMAP/WAPP (station Kankan), présente au dépôt.
- Couche B, substrat modélisé et cross-check inter-source : données
  satellitaires et de réanalyse (NASA POWER en source primaire, SARAH-3,
  CAMS, ERA5-Land).
- Couche C, post-traitement éditorial et conventions normatives :
  grandeurs dérivées Kuma (`kuma_calculs`) et conventions
  méthodologiques internationales appliquées aux données (IEC 61724-1:2021
  pour le PV, WMO-No.8 / CIMO Guide pour la météo).

### 5.2 Niveaux de confiance par mesure

Chaque mesure porte :

- `niveau_confiance_derive` : `A` / `B` / `C`, dérivé automatiquement par
  les règles R1-R4 à partir de la `methode_collecte` de la série et de la
  `fiabilite` de la source.
- `niveau_confiance_override` : `A` / `B` / `C` ou `null`. Override
  éditorial avec justification obligatoire.
- `niveau_effectif` (calculé) : `override` si non null, sinon `derive`.

Règles de dérivation (`editorial/niveaux_confiance.py`), évaluées dans
l'ordre, la première qui matche l'emporte :

| Ordre | Condition | Résultat |
|---|---|---|
| R1 | `source.fiabilite = 'faible'` | `C` |
| R2 | `methode_collecte = 'expertise_humaine'` (R1 négative) | `C` |
| R3 | `methode_collecte = 'mesure_directe'` ET `source.fiabilite = 'haute'` | `A` |
| R4 | tous les autres cas (catch-all) | `B` |

Interprétation :

- `A` : haute confiance, réservée aux mesures terrain. Seule une source à
  méthode `mesure_directe` et `fiabilite=haute` (une station sol) satisfait
  R3. La campagne ESMAP/WAPP Kankan est la première série en confiance A.
- `B` : confiance moyenne (modèle satellitaire ou réanalyse, source haute
  fiabilité), niveau dominant du substrat modélisé.
- `C` : confiance basse (source faible, ou expertise sans validation
  instrumentale).

La confiance A n'est pas un champ de `sources` : elle est dérivée. Une
source ne porte que sa `fiabilite` ; le A émerge de la combinaison R3 sur
une mesure directe terrain.

### 5.3 Statut éditorial

Chaque mesure et chaque ligne de `grandeurs_metier` porte un statut parmi
5 valeurs (CHECK constraint) :

| Statut | Sens |
|---|---|
| `brut` | Importé/calculé non validé (défaut à l'ingestion) |
| `valide_auto` | Contrôle qualité automatique passé |
| `valide_humain` | Validation éditoriale humaine confirmée |
| `publie` | Publié publiquement |
| `deprecie` | Retiré du circuit éditorial |

Les transitions sont encadrées par la couche service Python ; l'API les
expose en lecture. La vue `v_grandeurs_metier_courantes` filtre
nativement les lignes `deprecie` et les versions de formule non
actuelles.

### 5.4 Convention de nommage des codes de série

Format général :

```
<prefixe_localite>_<grandeur>_<source>[_<plage_annees>]
```

Exemples :

| Code | Décomposition |
|---|---|
| `gin_conakry_ghi_nasa_power_2021_2025` | localité `gin_conakry_kaloum` (préfixe historique `gin_conakry`), grandeur `ghi`, source `nasa_power`, plage 2021-2025 |
| `gin_kindia_hep_kuma_calculs_2021_2025` | grandeur `hep`, source `kuma_calculs` (couche éditoriale) |
| `gin_labe_ghi_sarah3_2021_2023` | série mensuelle SARAH-3, plage 2021-2023 |
| `gin_kankan_ghi_power_1991_2020` | climatologie 30 ans NASA POWER |

Règles :

- Préfixe pays : code ISO 3166-1 alpha-3 en minuscules (`gin` pour la
  Guinée).
- Exception historique : Conakry-Kaloum utilise `gin_conakry` (sans
  suffixe `_kaloum`) dans les codes de série, bien que sa localité
  s'appelle `gin_conakry_kaloum`.
- Caractères : ASCII pur, snake_case.

### 5.5 Convention de nommage des codes de localité

| Type | Format | Exemples |
|---|---|---|
| `continent`, `region_supranationale` | slug ASCII | `afrique` |
| `pays` | ISO 3166-1 alpha-3 minuscule | `gin` |
| `region_administrative`, `commune`, `site` | `<code_pays>_<slug>` | `gin_conakry`, `gin_kindia`, `gin_conakry_kaloum` |

### 5.6 Données stockées vs calculées à la volée

| Stockage | Quoi |
|---|---|
| `mesures_ressource` (journalier) | Grandeurs brutes journalières (GHI/DNI/DHI/T2M/RH2M/Kt, précipitation, PM, vent, albédo) |
| `mesures_ressource_mensuelles` | GHI mensuel SARAH-3, GHI mensuel climatologie 1991-2020, DNI mensuel CAMS, ERA5-Land mensuel |
| `mesures_ressource_horaires` | Horaire stocké validé par contrôle qualité (statut `valide_auto`, confiance B) |
| `grandeurs_metier` | Grandeurs F1 calculées Kuma (HEP, fraction diffuse, humidex, etc.) et écarts référentiels matérialisés |
| Calculé à la volée | Routes F1 (`ghi_exceedance`, `taux_salissure_proxy`, `pr_realiste`, `incertitude_inter_source`) et F2 paramétrables |
| Passe-plat à la volée | Horaire non couvert par le stocké (relais amont) |

## 6. Versioning temporel des données

### 6.1 Versioning non destructif des mesures

Toute mesure est temporellement versionnée par un couple :

- `valide_du` `TIMESTAMPTZ NOT NULL` : début de la fenêtre de validité.
- `valide_au` `TIMESTAMPTZ NULL` : fin de validité, `NULL` signifiant
  encore courante.

Une contrainte EXCLUDE BTree-GiST garantit qu'au plus une ligne est
courante (`valide_au IS NULL`) pour une identité métier donnée. Une
révision crée une nouvelle ligne courante après avoir clôturé la
précédente.

### 6.2 Versioning des formules de calcul

Pour les grandeurs calculées Kuma, chaque ligne porte aussi
`version_formule` (entier `>= 1`). L'identité métier inclut ce champ :
les valeurs v1 et v2 coexistent après une révision méthodologique, et la
vue `v_grandeurs_metier_courantes` expose la version en vigueur.

### 6.3 Ce que l'API expose en lecture

En v1, les endpoints `/v1/series/{code}` filtrent automatiquement sur
`valide_au IS NULL` (lignes courantes) et `statut <> 'deprecie'`. Le
ciblage explicite d'une version antérieure n'est pas exposé publiquement
v1 (l'historique reste en base pour audit interne).

### 6.4 Audit

Une table `audit_log` capture les opérations INSERT / UPDATE / DELETE sur
toutes les tables auditées via trigger PL/pgSQL `kuma_log_audit()`.
L'identifiant applicatif est propagé via
`current_setting('kuma.auteur_applicatif', true)`. Cette table n'est pas
exposée par l'API publique.

## 7. Sources de données

Chaque série pointe vers exactement une source via `source_id`. Le
listing `/v1/series` expose `source_code`, `source_label` et `source_url`
directement. La liste des sources effectivement porteuses de séries dans
un déploiement se lit via `/v1/series` (filtre `source`).

### 7.1 Sources du substrat et de la couche éditoriale

| Code | Organisme | Rôle Kuma | Couche |
|---|---|---|---|
| `nasa_power` | NASA Langley Research Center | Source primaire du substrat (satellite/réanalyse), radiatif et météo | B |
| `sarah3_monthly` | CM SAF / EUMETSAT (via PVGIS JRC) | Cross-check mensuel GHI | B |
| `cams_radiation` | Copernicus Atmosphere Monitoring Service / ECMWF | DNI et cross-check DNI | B |
| `cams_eac4` | Copernicus Atmosphere Monitoring Service / ECMWF | Particules PM2.5/PM10 (proxy salissure) | B |
| `ecmwf_era5_land` | ECMWF (Copernicus C3S) | Réanalyse land haute résolution | B |
| `esmap_wapp` | World Bank / ESMAP / WAPP (opérateur CSP Services) | Mesures sol Tier-1 (stations Kankan, Tarambaly), première ancre confiance A | A |
| `kuma_calculs` | Kuma | Couche éditoriale (grandeurs dérivées) | C |

`esmap_wapp` porte `fiabilite=haute` et une méthode de collecte
`mesure_directe` : c'est la combinaison qui déclenche la règle R3 et
produit la première confiance A du catalogue (station Kankan,
co-localisée à moins de 2 km du pilote `gin_kankan`).

### 7.2 Normes techniques mobilisées (couche C)

| Code | Norme | Rôle |
|---|---|---|
| `iec_61724_1_2021` | IEC 61724-1:2021 PV system performance - Monitoring | Conventions PV Kuma |
| `wmo_8_2024` | WMO-No.8 (CIMO Guide) Vol I 2024 | Conventions météo Kuma |

### 7.3 Sources de référence et structurelles au catalogue

Déclarées au référentiel pour la traçabilité ou l'ingestion future, sans
série active à ce jour dans le déploiement de référence :

| Code | Organisme | Rôle |
|---|---|---|
| `ecmwf_era5` | ECMWF (Copernicus C3S) | Cross-check inter-modèle, référencé doctrinairement |
| `anm_guinee_stations` | Agence Nationale de la Météorologie de Guinée | Voie complémentaire de calibration terrain (accès à convenir) |
| `wmo_grdc`, `wwf_hydrosheds`, `iec_60041_1991`, `wmo_168_2008` | divers | Vecteur hydro structurel (schéma prévu, ingestion différée) |

L'ANM Guinée est une voie de calibration terrain parmi d'autres, pas un
préalable : la confiance A est déjà atteinte via ESMAP/WAPP.

## 8. Découvrir la couverture

Les volumes (nombre de séries, de mesures) et la liste exacte des
localités couvertes dépendent du mode d'ingestion du déploiement et se
découvrent via l'API, pas via des compteurs figés dans ce document :

- `GET /v1/series` : catalogue des séries (filtres `localite`,
  `grandeur`, `source`, granularité) ; le champ `total` donne le nombre
  matchant les filtres.
- `GET /v1/localites` : référentiel géographique et hiérarchie.
- `GET /v1/grandeurs/incertitude_inter_source` : périmètre de l'atlas
  d'incertitude (points portant l'écart inter-source).
- `/docs` (OpenAPI, hors production) : schémas complets et essai
  interactif.

Faits de couverture durables (indépendants du volume ingéré) :

- Granularités : journalier, mensuel, horaire.
- Horaire : borne historique 2001.
- Climatologie mensuelle NASA POWER : 1991-2020.
- Cross-check DNI CAMS : 2004-2020 (climatologie) et 2021-2023 (récent).
- Journalier radiatif et météo : 2021-2025.
- Cross-check mensuel GHI SARAH-3 et atlas d'incertitude inter-source :
  2021-2023.
