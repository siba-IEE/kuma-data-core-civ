# Référence de l'API Kuma Data Core

> Référence technique de l'API, dérivée du code (routeurs, schémas
> Pydantic, règles de confiance) et des seeds. Le moteur est générique :
> le pays est un axe de classification, jamais une constante du code.
> Les exemples portent sur l'instance **Côte d'Ivoire** (base à la
> révision 0044) ; ils illustrent les contrats, ils ne figent pas le
> catalogue. Le catalogue et les volumes se découvrent via l'API
> elle-même (listing `/v1/series`, doc interactive `/docs`), pas via des
> compteurs figés dans ce document : ils dépendent du mode d'ingestion
> du déploiement.
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
| Documentation interactive | OpenAPI à `/docs` et `/redoc`, activable hors production, interdite en production par le validateur de configuration |
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
/v1/localites/resolution                          résolution d'un point quelconque
/v1/localites/{code}                              détail d'une localité
/v1/grandeurs/<code>                              11 routes grandeurs (F1 calculées, F2 paramétrables)
/v1/horaire/{localite}/{grandeur}                 horaire stocké validé, repli passe-plat
/v1/horaire/{localite}/{grandeur}/disponibilite   plage temporelle disponible
/v1/calage                                        référentiels de calage publiés
/v1/calage/{localite}/{grandeur}                  référentiel de calage d'un couple
/v1/etudes/capsule                                ressource d'étude au point
```

26 endpoints en tout : santé (2), édition (1), clés (2), séries (2),
localités (3), grandeurs (11), horaire (2), calage (2), études (1). Le
préfixe `/v1/grandeurs/` n'agrège pas dynamiquement, il expose 11
routes distinctes (détail en 3.7).

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
  publique n'est autorisée par défaut. L'en-tête `X-Kuma-Mesures-Total`
  (3.4) est exposé aux clients navigateur.

## 3. Endpoints (détail)

### 3.1 `GET /v1/health` : santé publique

- Auth : non requise
- Réponse 200 :

```json
{
  "statut": "operationnel",
  "edition": "edition_AAAAMMJJ"
}
```

- Indique que l'API répond. `edition` est lu en best-effort (identifiant
  de l'édition publiée servie, `null` hors régime édition ou si la
  lecture échoue) : le health ne dépend de rien et ne renvoie jamais de
  5xx. Le détail de l'édition vit sur `GET /v1/edition` (3.10).
- La version logicielle et l'environnement ne sont **pas** renvoyés par
  cet endpoint non authentifié (ils aideraient à cibler des
  vulnérabilités connues) : ils sont servis par `GET /v1/health/db`.

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
| `localite` | `str` | | Filtre par code localité complet (ex. `civ_dep_abidjan`) |
| `grandeur` | `str` | | Filtre par code grandeur (ex. `ghi`, `hep`) |
| `source` | `str` | | Filtre par code source (ex. `nasa_power`, `kuma_calculs`) |
| `granularite` | `journalier`, `mensuel` ou `horaire` | | Filtre par granularité des mesures brutes. Les grandeurs calculées (`kuma_calculs`) n'en ont pas : les filtrer par `source` |
| `actif` | `bool` | `true` | Inclut les séries soft-deleted si `false` |
| `limit` | `int [1, 1000]` | `100` | Pagination |
| `offset` | `int >= 0` | `0` | Pagination |

- Réponse 200 (envelope paginée), exemple
  `?localite=civ_dep_abidjan&grandeur=ghi&source=nasa_power&granularite=mensuel` :

```json
{
  "items": [
    {
      "id": 1,
      "code": "nasa_power_ghi_mensuel_civ_dep_abidjan",
      "libelle": "GHI mensuel NASA POWER — Abidjan (1991-2025)",
      "localite_id": 156,
      "localite_code": "civ_dep_abidjan",
      "localite_nom": "Abidjan",
      "localite_iso3": "CIV",
      "grandeur_code": "ghi",
      "grandeur_label": "Irradiation globale horizontale",
      "grandeur_unit": "kWh/m²/jour",
      "source_id": 1,
      "source_code": "nasa_power",
      "source_label": "NASA POWER - Prediction Of Worldwide Energy Resources : Solar and Meteorological Data Archive",
      "source_url": "https://power.larc.nasa.gov/",
      "periode_debut": "1991-01-01",
      "periode_fin": "2025-12-31",
      "granularite": "mensuel",
      "methode_collecte": "modele_satellitaire",
      "notes_fr": "GHI mensuel NASA POWER (moyenne journalière du mois, kWh/m²/jour), climatologie 1991-2020. Confiance B (satellite/réanalyse). Prolongée jusqu'en 2025 (ADR-0018).",
      "created_at": "2026-10-15T05:42:39.089514Z",
      "updated_at": "2026-10-15T05:42:39.089514Z",
      "actif": true
    }
  ],
  "total": 1,
  "limit": 100,
  "offset": 0
}
```

- 22 champs par item, dénormalisés (localité, grandeur, source) pour
  éviter au consommateur de chaîner les appels. Le champ `total` reflète
  le nombre de séries matchant les filtres dans le déploiement interrogé.
- `granularite` vaut `journalier`, `mensuel`, `horaire`, ou `null` pour
  une grandeur calculée (source `kuma_calculs`, dont le pas est porté
  par chaque valeur). Pour un même lieu, une même source et une même
  grandeur, plusieurs granularités peuvent coexister : à Abidjan, NASA
  POWER sert le GHI en mensuel **et** en journalier (ADR-0016) ; seul ce
  champ les distingue.
- Une valeur hors domaine (`granularite=annuel`, `limit=0`...) répond
  `422 VALIDATION_VALEUR_INVALIDE`.
- Note de stabilité : le contrat de cet endpoint est figé ; `granularite`
  est un ajout rétrocompatible (ADR-0029). Les renommages publics
  `cree_le` vers `created_at`, `modifie_le` vers `updated_at`,
  `note_publique` vers `notes_fr`, `sources.titre` vers `source_label`
  sont assumés et ne dérivent pas du nom de colonne DB.

### 3.4 `GET /v1/series/{code_serie}` : détail d'une série + mesures

- Auth : Bearer requise
- Paramètres path : `code_serie` (identifiant opaque, voir 5.4)
- Paramètres query :

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `from` | `YYYY-MM-DD` ou `YYYY-MM` | | Borne basse temporelle inclusive (`YYYY-MM` = 1er du mois) |
| `to` | `YYYY-MM-DD` ou `YYYY-MM` | | Borne haute temporelle inclusive |
| `format` | `json` ou `csv` | `json` | Format de réponse |
| `limit` | `int [1, 10000]` | `1000` | Pagination des mesures |
| `offset` | `int >= 0` | `0` | Pagination |

- Résolution de la table-cible (`api/services/serie_lecture.py`),
  **source d'abord, puis granularité** : une série `kuma_calculs` est
  lue dans `grandeurs_metier` via la vue `v_grandeurs_metier_courantes` ;
  toute autre série par sa `granularite` (`journalier` :
  `mesures_ressource` ; `mensuel` : `mesures_ressource_mensuelles`).
  Une série `horaire` n'est pas servie ici :
  `404 RESSOURCE_INTROUVABLE`, avec renvoi vers `/v1/horaire` (3.8).

- Pagination des mesures (ADR-0029) : le détail renvoie au plus `limit`
  mesures et le bloc `pagination_mesures` dit combien la fenêtre
  `from`/`to` en contient, toutes pages confondues. Page suivante :
  `offset + limit`, tant que `offset + limit < total`. Une série
  journalière de 1991-2025 compte 12 784 mesures : sans pagination, une
  moyenne calculée sur la réponse par défaut ne porterait que sur
  1991-1993.

- Tri des mesures : `instant_mesure` (journalier) ; `(annee, mois)`
  (mensuel) ; `(annee_debut, mois, annee_fin, periode_type, id)` pour
  les valeurs calculées (la valeur annuelle avant les mois de son
  année), ordre total qui pagine sans perte ni doublon une série mêlant
  valeurs annuelles et mensuelles. Sur les séries mensuelles et
  calculées, `from` et `to` sont lus au mois. Pour les valeurs
  calculées, la fenêtre compare `(annee_debut, mois)` à `from` et
  `(annee_fin, mois)` à `to`, un mois absent valant janvier côté `from`
  et décembre côté `to` : une valeur annuelle n'entre dans la fenêtre
  que si celle-ci va de janvier à décembre de son année.

- Réponse 200 JSON, exemple
  `nasa_power_ghi_journalier_civ_dep_abidjan?from=2024-01-01&to=2024-01-01` :

```json
{
  "id": 372,
  "code": "nasa_power_ghi_journalier_civ_dep_abidjan",
  "libelle": "GHI journalier NASA POWER — Abidjan (1991-2025)",
  "grandeur_code": "ghi",
  "grandeur_unit": "kWh/m²/jour",
  "source_code": "nasa_power",
  "periode_debut": "1991-01-01",
  "periode_fin": "2025-12-31",
  "granularite": "journalier",
  "unite_code": "kwh_par_m2_jour",
  "pagination_mesures": {"total": 1, "limit": 1000, "offset": 0},
  "mesures": [
    {
      "type": "journalier",
      "instant_mesure": "2024-01-01",
      "valeur": 5.0429,
      "niveau_confiance_derive": "B",
      "niveau_confiance_override": null,
      "niveau_effectif": "B",
      "statut": "brut"
    }
  ]
}
```

(Les champs d'en-tête dénormalisés sont identiques à ceux du listing,
omis ici pour la lisibilité ; `unite_code` et `pagination_mesures`
s'y ajoutent.)

- Trois formes de mesures discriminées (champ `type`) :

  - `journalier` : `instant_mesure: date`, `valeur: float`
  - `mensuel` : `annee: int` (1981-2099, bornes de la contrainte de
    base), `mois: int`, `valeur: float`
  - `grandeur_metier` : `periode_type` (`mensuel`, `annuel`, `statique`),
    `annee_debut`, `annee_fin`, `mois` (nullable), `version_formule: int`,
    `valeur: float | null` (nullable comme la colonne)

  Tous portent en plus `niveau_confiance_derive`,
  `niveau_confiance_override`, `niveau_effectif` (résolu) et `statut`
  (voir 5.2 et 5.3).

- Format CSV (`format=csv`) : header générique `code_serie, type, annee,
  mois, instant_mesure, periode_type, annee_debut, annee_fin,
  version_formule, valeur, niveau_effectif, statut`, une ligne par mesure
  de la page. Le total de la fenêtre voyage dans l'en-tête HTTP
  **`X-Kuma-Mesures-Total`** (le CSV ne porte que des lignes) : la même
  série sans fenêtre répond 1000 lignes et `X-Kuma-Mesures-Total: 12784`.

- Erreurs : `404 RESSOURCE_SERIE_INCONNUE` si le code de série
  n'existe pas ; `400 VALIDATION_FORMAT_DATE_INVALIDE` (`from`/`to`
  ni `YYYY-MM-DD` ni `YYYY-MM`) ; `400 VALIDATION_FORMAT_NON_SUPPORTE`
  (`format` autre que `json`/`csv`) ; `422 VALIDATION_VALEUR_INVALIDE`
  (`limit` ou `offset` hors bornes).

### 3.5 `GET /v1/localites` : référentiel géographique (listing)

- Auth : Bearer requise
- Pagination : offset-based, `limit` défaut 100, max 1000.
- Tri : `ORDER BY code ASC`.
- Paramètres query :

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `pays_iso3` | `str` | | Filtre ISO 3166-1 alpha-3 (ex. `CIV`) |
| `type_localite` | `str` | | `continent`, `region_supranationale`, `pays`, `region_administrative`, `prefecture`, `commune`, `site` |
| `parent_code` | `str` | | Filtre par code de la localité parente |
| `q` | `str (1..100)` | | Recherche textuelle sur le nom ou le code (ci-dessous) |
| `actif` | `bool` | `true` | Inclut les soft-deleted si `false` |
| `limit` | `int [1, 1000]` | `100` | Pagination |
| `offset` | `int >= 0` | `0` | Pagination |

- **Recherche `q`** (ADR-0029) : une localité est retenue si son **nom**
  contient le texte saisi (insensible à la casse) **ou** si son **code**
  contient la forme normalisée du texte (minuscules, accents retirés,
  toute suite de caractères hors `[a-z0-9]` ramenée à `_`). Le code
  étant le slug ASCII du nom, la recherche devient insensible aux
  accents et à la ponctuation sans extension ni table de
  correspondance : `q=Agneby` trouve `civ_agneby_tiassa`
  (« Agnéby-Tiassa ») ; `q=san-pedro` trouve `civ_dep_san_pedro` et
  `civ_san_pedro` (« San-Pédro »). `%` et `_` saisis sont pris
  littéralement ; `q` vide répond `422 VALIDATION_VALEUR_INVALIDE`.

- **Niveaux** : `type_localite` est un axe technique générique à sept
  niveaux, pas le nom d'un palier national (ADR-0005). Mapping de
  l'instance Côte d'Ivoire :

| Palier ivoirien | `type_localite` | Parent | Exemple |
|---|---|---|---|
| Pays | `pays` | `afrique` | `civ` |
| District (14, dont 2 autonomes) | `region_administrative` | `civ` | `civ_savanes` |
| Région (31) | `prefecture` | le district | `civ_poro` |
| Département (111) | `commune` | la région (le district autonome pour Abidjan, Yamoussoukro et Attiégouakro) | `civ_dep_korhogo` |

  Le niveau `prefecture` porte donc ici les **régions** ivoiriennes ;
  le libellé humain est dans `nom`. Exemple :
  `?type_localite=prefecture&parent_code=civ_savanes` renvoie Bagoué,
  Poro et Tchologo.

- Réponse 200, exemple `?q=Korhogo` :

```json
{
  "items": [
    {
      "id": 126,
      "code": "civ_dep_korhogo",
      "nom": "Korhogo",
      "type_localite": "commune",
      "parent_id": 39,
      "parent_code": "civ_poro",
      "pays_iso3": "CIV",
      "latitude": 9.41666667,
      "longitude": -5.61666667,
      "altitude_metres": null,
      "population_estimee": 748393,
      "annee_population": 2021,
      "fuseau_horaire": "Africa/Abidjan",
      "created_at": "2026-10-15T05:42:39.089514Z",
      "updated_at": "2026-10-15T05:42:39.089514Z",
      "actif": true
    }
  ],
  "total": 1,
  "limit": 100,
  "offset": 0
}
```

- 16 champs par item. `parent_code` dénormalisé via self-JOIN : un appel
  suffit pour reconstruire la hiérarchie ligne par ligne. La hiérarchie
  récursive complète (chaîne `pays > district > région > département`)
  n'est pas exposée v1.

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
paramètre libre, path-based). Le choix des séries lues (ADR-0028)
repose sur la granularité et le recouvrement des périodes, lus dans les
métadonnées des séries, jamais sur une date de début ou une localité
codée en dur.

| Route | Famille | Sortie |
|---|---|---|
| `GET /v1/grandeurs/poa_parametrable` | F2 | journalier |
| `GET /v1/grandeurs/poa_bifacial` | F2 | journalier |
| `GET /v1/grandeurs/productible_correction_thermique` | F2 | journalier |
| `GET /v1/grandeurs/productible_pr_fourni` | F2 | journalier ou mensuel |
| `GET /v1/grandeurs/energie_utile_ecs` | F2 | journalier |
| `GET /v1/grandeurs/degre_jour_climatisation` | F2 | mensuel |
| `GET /v1/grandeurs/ghi_exceedance/{code_localite}` | F1 | fiche P50/P90 |
| `GET /v1/grandeurs/taux_salissure_proxy/{code_serie_source}` | F1 | journalier |
| `GET /v1/grandeurs/pr_realiste/{code_serie_source}` | F1 | journalier + mensuel |
| `GET /v1/grandeurs/incertitude_inter_source/{code_localite}` | F1 | fiche |
| `GET /v1/grandeurs/incertitude_inter_source` | F1 | collection paginée |

En `methode=integration_horaire`, les routes F2 intègrent heure par
heure (série source horaire) mais rendent toujours des résultats
journaliers (mensuels pour `degre_jour_climatisation`).

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
| `code_serie_source` | `str (1..80)` | oui | Code d'une série F1 source active (ex. `nasa_power_ghi_journalier_civ_dep_abidjan`) |
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

**Garde de granularité** : la granularité de la série source doit
correspondre à `methode`. `moyenne_journaliere` exige une série
**journalière** (`productible_pr_fourni` admet aussi une série
**mensuelle**) ; `integration_horaire` exige une série **horaire** (plus
les compagnes horaires requises) et lève le biais de moyennage
journalier. Sinon : `400 VALIDATION_VALEUR_INVALIDE`, au lieu d'une
lecture dans la mauvaise table qui rendrait une liste vide. Exemple :
`poa_parametrable` sur `nasa_power_ghi_mensuel_civ_dep_abidjan`
répond 400 (« methode='moyenne_journaliere' exige une serie source de
granularite 'journalier' ») ; `degre_jour_climatisation` refuse de même
une T2M mensuelle, dont la moyenne écraserait les écarts journaliers.

#### 3.7.4 Pattern auto-compagne (F2)

Plusieurs routes F2 ont besoin de plusieurs séries d'entrée. Le
consommateur fournit uniquement la série principale ; le routeur
cherche les séries compagnes (`_chercher_serie_compagne`) parmi les
séries actives :

- de la même localité et de la même source ;
- de la même **granularité** que la série principale (journalier,
  mensuel ou horaire) : une compagne d'une autre granularité serait lue
  dans la mauvaise table ;
- qui **recouvrent** la période demandée (`periode_debut <= fin` et
  `periode_fin` nulle ou `>= debut`).

La date de début n'est **pas** une identité de famille : les grandeurs
d'une même source n'ont pas toutes la même profondeur (GHI NASA POWER
depuis 1991, DNI et DHI depuis 2001). Ordre déterministe si plusieurs
candidates : plus grand recouvrement de la période demandée, puis même
`periode_debut` que la série principale, puis `id`.

| Route | Série principale | Compagnes auto | Si compagne manquante |
|---|---|---|---|
| `poa_parametrable` (journalier) | `grandeur_code=ghi` | DNI, DHI | Fallback Liu-Jordan (précision dégradée en ciel partiellement couvert) |
| `poa_parametrable` (`integration_horaire`) | `ghi` horaire | DNI, DHI horaires | `400 VALIDATION_VALEUR_INVALIDE` (pas de fallback en horaire) |
| `poa_bifacial` | `ghi` | DNI, DHI (albédo : série `albedo_surface` journalière de la même localité et source) | `400 INCOMPATIBILITE_SOURCE_GRANDEUR` (pas de fallback) ; albédo absent : repli `albedo_sol` |
| `productible_correction_thermique` | `ghi` | T2M | `400 INCOMPATIBILITE_SOURCE_GRANDEUR` |
| `productible_pr_fourni` (`correction=aucune`) | `ghi` | | |
| `productible_pr_fourni` (`correction=temperature`) | `ghi` | T2M | `400 INCOMPATIBILITE_SOURCE_GRANDEUR` |
| `energie_utile_ecs` | `ghi` | T2M | `400 INCOMPATIBILITE_SOURCE_GRANDEUR` |
| `degre_jour_climatisation` | `t2m` | aucune | |

Seuls les jours (ou les heures) portés par toutes les séries lues sont
calculés, sauf en `poa_parametrable` journalier où un jour sans DNI ou
DHI bascule sur le fallback.

Pour `productible_pr_fourni`, la table-cible est dispatchée selon la
source : une série mensuelle n'accepte que `correction=aucune`
(résultats mensuels `YYYY-MM`, productible quotidien moyen du mois ;
`correction=temperature` y répond `400 INCOMPATIBILITE_SOURCE_GRANDEUR`) ;
une série calculée Kuma (`kuma_calculs`) est rejetée en
`400 INCOMPATIBILITE_SOURCE_GRANDEUR` (une F1 calculée n'est pas
admissible comme source brute d'un calcul F2).

**Instance Côte d'Ivoire** (révision 0044) : les 34 localités dotées du
GHI journalier NASA POWER (1991-2025) portent aussi le DNI et le DHI
journaliers (2001-2025). Sur une période dans 2001-2025, POA paramétrable
(Perez) et POA bifacial y sont calculés ; avant 2001, faute de compagnes
recouvrant la période, POA paramétrable bascule sur le repli Liu-Jordan
et POA bifacial répond 400. La météo NASA POWER y est aussi gravée en
journalier (température, humidité, vent, pluie 1991-2025, albédo
2001-2025 ; migration 0035, ADR-0020) : POA bifacial lit l'albédo
journalier, et les routes qui demandent une T2M journalière (correction
thermique, énergie ECS, degrés-jours) aboutissent. La recherche de
compagnes étant générique, ces séries sont trouvées sans code propre à
l'instance. Sur le GHI mensuel des
142 localités, seul `productible_pr_fourni` en `correction=aucune`
s'applique.

#### 3.7.5 Format de réponse F2 (JSON)

Exemple `poa_parametrable?code_serie_source=nasa_power_ghi_journalier_civ_dep_abidjan&periode_debut=2022-01-01&periode_fin=2022-01-02&inclinaison_deg=10&orientation_deg=180` :

```json
{
  "code_grandeur": "poa_parametrable",
  "code_serie_source": "nasa_power_ghi_journalier_civ_dep_abidjan",
  "parametres_appliques": {
    "inclinaison_deg": 10.0,
    "orientation_deg": 180.0,
    "albedo_sol": 0.2,
    "methode": "moyenne_journaliere"
  },
  "resultats": [
    {
      "granularite": "journalier",
      "instant": "2022-01-01",
      "valeur": 5.107580862340342,
      "unite": "kWh/m²/jour",
      "niveau_confiance": "B"
    },
    {
      "granularite": "journalier",
      "instant": "2022-01-02",
      "valeur": 4.117968404867951,
      "unite": "kWh/m²/jour",
      "niveau_confiance": "B"
    }
  ]
}
```

Résultats discriminés par `granularite` : `journalier` (`instant: date`)
ou `mensuel` (`instant` au format `YYYY-MM`). `degre_jour_climatisation`
sort en mensuel. Chaque résultat porte son unité : `kWh/m²/jour` (POA),
`kWh` (productibles, pour la puissance `puissance_stc_wc` fournie),
`kWh/m²` (ECS), `°C·j` (degrés-jours). Le niveau de confiance des
sorties F2 est `B`. La réponse ne dit pas quel modèle POA a été
appliqué (Perez ou repli Liu-Jordan).

Format CSV (`format=csv`) : header `granularite, instant, valeur, unite,
niveau_confiance`.

#### 3.7.6 Routes F1 calculées à la volée

Ces routes dérivent une grandeur éditoriale à partir de séries déjà
ingérées ou déjà matérialisées, sans paramètre physique libre. Toutes
portent un champ `limite` : un avertissement éditorial explicite sur la
portée du résultat. Elles répondent en JSON seulement.

**`ghi_exceedance/{code_localite}`** : exceedance inter-annuelle P50/P90
de l'irradiation annuelle.

- Série source : la série GHI **NASA POWER mensuelle** active de la
  localité qui **couvre** la normale 1991-2020 (`periode_debut <=
  1991-01-01` et `periode_fin` nulle ou `>= 2020-12-31`) ; une série
  prolongée au-delà de 2020 convient. Ordre déterministe si plusieurs :
  début le plus récent, puis `id`. À défaut :
  `404 RESSOURCE_LOCALITE_INCONNUE` (cas d'un district ivoirien, qui ne
  porte aucune série).
- Seules les mesures **1991-2020** sont lues, même si la série va plus
  loin. Totaux annuels en kWh/m²/an par pondération journalière (jours
  du mois, années bissextiles incluses), **années complètes
  seulement** (12 mois). Moins de 2 années complètes :
  `422 PLAGE_TEMPORELLE_NON_DISPONIBLE`.
- P50 = médiane, P90 = percentile 10 (scénario conservateur, P90 < P50
  par construction), interpolation `linear` de numpy.
- Réponse : `code_localite`, `code_serie_source`, `periode`
  (`1991-2020`), `base_annees`, `p50`, `p90`, `unite` (`kWh/m²/an`),
  `methode_percentile`, `niveau_confiance` (B), `limite`.
- `limite` signale que c'est de la variabilité inter-annuelle, pas un
  P90 bancable propageant l'incertitude de modèle, et cite les
  **jumeaux de pixel** : les autres localités dont la série GHI NASA
  POWER mensuelle 1991-2020 est strictement identique, détectées à la
  lecture (égalité exacte des séries, aucune grille supposée) ; leurs
  P50 et P90 sont identiques.
- Exemple `civ_dep_abidjan` : série `nasa_power_ghi_mensuel_civ_dep_abidjan`,
  30 années, P50 1718,80 et P90 1679,57 kWh/m²/an ; `limite` cite 6
  jumeaux (Agboville, Dabou, Jacqueville, Sikensi, Tiassalé et la
  région des Grands-Ponts). `civ_dep_tengrela`, seule dans sa cellule,
  n'en cite aucun.

**`taux_salissure_proxy/{code_serie_source}`** : perte de transmission
par salissure (`% = (1 − ratio HSU) × 100`, modèle HSU pvlib), à partir
d'une série PM2.5 **journalière** (source `cams_eac4`). Compagnes
automatiques : PM10 (même source, pattern 3.7.4) et précipitation
journalière (source `nasa_power`, résolveur cross-source dédié qui
retient la série recouvrant la plage des PM). Alignement par
intersection des dates. Réponse : `periode`, `mesures` (perte par jour),
`surface_tilt_deg`, `cleaning_threshold_mm`, `limite`. Erreurs :
`400 INCOMPATIBILITE_SOURCE_GRANDEUR` si la série n'est pas une PM2.5,
n'est pas journalière, ou si une compagne manque ;
`422 PLAGE_TEMPORELLE_NON_DISPONIBLE` si l'index journalier commun a un
trou (le modèle HSU est path-dependant).

**`pr_realiste/{code_serie_source}`** : PR effectif site-spécifique =
`PR fourni × ratio thermique × (1 − salissure)` selon le mode
`correction` (`aucune`, `temperature`, `salissure`,
`temperature_salissure`, défaut `temperature_salissure`). Série source
= GHI **journalière** (sinon `400 INCOMPATIBILITE_SOURCE_GRANDEUR`) ;
compagnes selon le mode : T2M et précipitation (même source et même
granularité que le GHI, pattern 3.7.4), PM2.5 et PM10 cross-source
`cams_eac4`. Paramètres query : `pr_fourni` `[0..1]` (obligatoire),
`correction`, `noct_degc` et `coeff_temp_pourcent_par_degc`
(obligatoires si la correction inclut la température, sinon
`422 VALIDATION_CHAMP_MANQUANT`). Compagne absente :
`400 INCOMPATIBILITE_SOURCE_GRANDEUR` ; trou dans l'index commun :
`422 PLAGE_TEMPORELLE_NON_DISPONIBLE`. Réponse : `periode`,
`correction`, `pr_fourni`, `mesures_journalier` et `mesures_mensuel` (la
courbe mensuelle est la PR saisonnière), `limite`. Dans l'instance Côte
d'Ivoire à la révision 0044, `correction=aucune` et
`correction=temperature` aboutissent aux 34 localités du GHI journalier
(T2M journalière NASA POWER) ; les modes qui demandent la salissure
attendent les séries journalières de PM2.5/PM10 CAMS EAC4.

**`incertitude_inter_source/{code_localite}`** : fiche d'incertitude
inter-source d'une localité, en lecture/assemblage de grandeurs déjà
matérialisées (aucun calcul de substrat). Deux axes distincts, non
fusionnés :

- `ecarts` : un écart par grandeur (GHI, DNI), fenêtre **2021-2023**
  (valeurs mensuelles dont `annee_debut` est dans la fenêtre). Paires
  candidates, dans l'ordre, la première portant des écarts étant
  retenue : GHI `ecart_relatif_ghi_sarah3_nasa` (« PVGIS-SARAH3 vs NASA
  POWER ») puis `ecart_relatif_referentiel` (« NASA POWER vs
  PVGIS-SARAH3 ») ; DNI `ecart_relatif_dni_cams_nasa` (« CAMS vs NASA
  POWER ») puis `ecart_relatif_dni_cams` (« NASA POWER vs CAMS »).
  **Convention de signe** : `paire = "A vs B"` signifie que l'écart
  stocké vaut `(A − B) / B × 100` (référence nommée en second, au
  dénominateur) ; un écart positif veut dire que A est au-dessus de B.
  Les valeurs sont lues telles quelles, jamais converties.
  `ecart_abs_pct` (médiane des écarts absolus mensuels) est le signal
  primaire ; `ecart_signe_pct` (moyenne signée) est orientationnel,
  jamais une correction de biais ; `n_mois` compte les mois comparés.
- `degenerescence` : propriété niveau-localité, rendue une fois. Elle
  est **lue** si la grandeur `degenerescence_pixel` est gravée (ligne
  rattachée à la série GHI NASA POWER mensuelle de la localité) ; à
  défaut elle est **détectée à la lecture** par égalité exacte des
  séries GHI NASA POWER mensuelles 1991-2020 (même méthode que la
  grandeur), confiance B. Champs : `n_jumeaux` (autres localités de même
  série), `grille` (libellé de la grille NASA, CERES SYN1deg), `note`
  (commentaire éditorial gravé, ou note de détection).

`niveau_confiance` vaut B, lu et vérifié sur toutes les lignes lues
(jamais A : inter-source, pas terrain ; une ligne qui ne serait pas B
fait répondre 500). `404 RESSOURCE_LOCALITE_INCONNUE` si la localité ne
porte aucun écart sur la fenêtre (cas des districts ivoiriens).

Exemple `civ_dep_abidjan` : GHI « PVGIS-SARAH3 vs NASA POWER »,
`ecart_abs_pct` 6,70 et `ecart_signe_pct` +7,29 (SARAH-3 au-dessus de
NASA) ; DNI « CAMS vs NASA POWER », 29,63 et +30,44 ; 36 mois chacun ;
`degenerescence.n_jumeaux` = 6.

**`incertitude_inter_source`** (collection) : toutes les fiches des
points de l'atlas, paginées (`limit` défaut 100, max 1000), triées par
code, enveloppe identique à `/v1/series` (`items`, `total`, `limit`,
`offset`). Chaque item est la fiche par-localité augmentée de
`latitude_deg`/`longitude_deg`, pour poser chaque point sur une carte
sans second appel. Le périmètre est data-driven (les localités portant
un écart de l'une des paires candidates sur la fenêtre), robuste à une
densification : 142 points dans l'instance Côte d'Ivoire.

#### 3.7.7 Erreurs des routes grandeurs

| Code | HTTP | Condition |
|---|---|---|
| `RESSOURCE_SERIE_INCONNUE` | 404 | `code_serie_source` introuvable ou inactif |
| `RESSOURCE_LOCALITE_INCONNUE` | 404 | `ghi_exceedance` : aucune série GHI NASA POWER mensuelle couvrant 1991-2020 ; `incertitude_inter_source` : aucun écart sur 2021-2023 |
| `INCOMPATIBILITE_SOURCE_GRANDEUR` | 400 | série de mauvaise grandeur, source non admissible (`kuma_calculs` en F2), série mensuelle avec `correction=temperature`, compagne requise absente, route F1 (`taux_salissure_proxy`, `pr_realiste`) sur une série non journalière |
| `VALIDATION_VALEUR_INVALIDE` | 400 | granularité de la série source qui ne correspond pas à `methode` (3.7.3), ou POA horaire sans DNI/DHI horaires |
| `VALIDATION_VALEUR_INVALIDE` | 422 | paramètre absent, de mauvais type ou hors bornes (validation Pydantic) |
| `VALIDATION_CHAMP_MANQUANT` | 422 | `pr_realiste` : correction incluant la température sans `noct_degc` ou `coeff_temp_pourcent_par_degc` |
| `PLAGE_TEMPORELLE_NON_DISPONIBLE` | 422 | `ghi_exceedance` : moins de 2 années complètes sur 1991-2020 ; `taux_salissure_proxy`, `pr_realiste` : trou dans l'index journalier |
| `SERVEUR_ERREUR_INTERNE` | 500 | `incertitude_inter_source` : donnée incohérente (confiance autre que B, écart sans dégénérescence lisible ni détectable) |

Les contrôles qui croisent plusieurs paramètres (`periode_fin >=
periode_debut` des routes F2 et de `/v1/horaire` ; plage horaire de 366
jours au plus ; `noct_degc` et `coeff_temp_pourcent_par_degc` exigés par
`productible_pr_fourni` en `correction=temperature`) répondent
`422 VALIDATION_VALEUR_INVALIDE`, comme les bornes de chaque paramètre
pris isolément (base commune des modèles de paramètres,
`api/v1/schemas/parametres.py`).

### 3.8 `GET /v1/horaire/{localite}/{grandeur}`

Cet endpoint sert d'abord l'horaire stocké et validé par contrôle
qualité, avec repli passe-plat sur la source amont sinon. Il n'est plus
un pur passe-plat.

- Auth : Bearer requise
- Paramètres path :

| Paramètre | Valeurs autorisées |
|---|---|
| `{localite}` | toute localité active du référentiel, par son **code complet** (`^[a-z0-9_]+$`, 1 à 100 caractères), ou par un alias court (ci-dessous) |
| `{grandeur}` | `ghi`, `dni`, `dhi`, `t2m`, `rh2m`, `kt`, `vent_2m`, `vent_10m`, `precipitation` |

- **Résolution de la localité** (aucune liste de villes, aucun préfixe
  codé en dur) : le code complet est cherché tel quel ; à défaut, il est
  lu comme un **alias court** sans préfixe pays, ce préfixe étant le
  code d'un pays présent au référentiel (`type_localite = 'pays'`).
  Dans l'instance Côte d'Ivoire, `dep_abidjan` désigne
  `civ_dep_abidjan` et `abidjan` le district `civ_abidjan`. Un alias qui
  désignerait des localités de plusieurs pays est ambigu :
  `404 RESSOURCE_LOCALITE_INCONNUE` avec la liste des candidats dans
  `details.candidats`. Un code inconnu répond aussi
  `404 RESSOURCE_LOCALITE_INCONNUE` (et non 422 : l'énumération fermée a
  disparu avec la généricité pays).

- Paramètres query :

| Paramètre | Type | Plage | Obligatoire |
|---|---|---|---|
| `periode_debut` | `YYYY-MM-DD` | `>= 2001-01-01` | oui |
| `periode_fin` | `YYYY-MM-DD` | `>= periode_debut`, plage `<= 366` jours | oui |
| `format` | `json` / `csv` | | non (`json` défaut) |

Une `periode_debut` antérieure à 2001 répond
`422 VALIDATION_VALEUR_INVALIDE` ; les deux contrôles croisés sur
`periode_fin` relèvent de la limite connue décrite en 3.7.7 (réponse
500).

Comportement :

1. La fenêtre doit tenir dans la plage disponible (3.9), sinon
   `400 PLAGE_TEMPORELLE_NON_DISPONIBLE` (détails : plage demandée et
   plage disponible).
2. Si une série horaire active **portant des mesures stockées** couvre
   toute la plage demandée, l'endpoint renvoie ses points validés
   (`mesures_ressource_horaires`, statuts `valide_auto`, `valide_humain`
   ou `publie`, servis avec `statut_editorial = valide_auto`, confiance
   B). Les lignes rejetées par le contrôle qualité (statut `brut`) sont
   exclues.
3. Sinon, en profil édition figée (ADR-0003, D6), aucun relais n'est
   tenté : `400 PLAGE_TEMPORELLE_NON_DISPONIBLE` (raison
   `edition_figee_sans_relais_temps_reel`).
4. Sinon, l'API relaie la requête vers le service amont (NASA POWER) aux
   coordonnées de la localité, convertit la réponse au format Kuma et
   l'étiquète `passe_plat_non_valide`. Une localité sans coordonnées
   (racine continentale) répond `404 RESSOURCE_INTROUVABLE` ; un service
   amont indisponible, `503 PASSE_PLAT_INDISPONIBLE`.

Le champ `statut_editorial` de chaque point vaut donc `valide_auto`
(stocké validé) ou `passe_plat_non_valide` (relais non validé).
L'instance Côte d'Ivoire ne porte aucune série horaire
(`/v1/series?granularite=horaire` : `total` 0) : toute requête y passe
par le relais, ou répond 400 en édition figée.

- Réponse 200 JSON, exemple `civ_dep_korhogo/ghi?periode_debut=2024-01-15&periode_fin=2024-01-15`
  (relais, 2 des 24 points) :

```json
{
  "localite": "civ_dep_korhogo",
  "grandeur": "ghi",
  "periode_demandee": {
    "debut": "2024-01-15",
    "fin": "2024-01-15"
  },
  "resultats": [
    {
      "instant": "2024-01-15T00:00:00",
      "valeur": 0.0,
      "unite": "Wh/m²",
      "statut_editorial": "passe_plat_non_valide"
    },
    {
      "instant": "2024-01-15T12:00:00",
      "valeur": 875.4,
      "unite": "Wh/m²",
      "statut_editorial": "passe_plat_non_valide"
    }
  ]
}
```

- 24 points par jour, instant en UTC.
- `valeur: null` pour les heures où l'indice n'est pas physiquement
  défini (cas `kt` la nuit) ou une donnée manquante amont en mode repli.
- Format CSV : header `instant, valeur, unite, statut_editorial`.

### 3.9 `GET /v1/horaire/{localite}/{grandeur}/disponibilite`

Retourne la plage temporelle utilisable pour le passe-plat horaire.

- Auth : Bearer requise
- Réponse 200 (exemple interrogé le 2026-10-15) :

```json
{
  "localite": "civ_dep_abidjan",
  "grandeur": "ghi",
  "plage_disponible": {
    "debut": "2001-01-01",
    "fin": "2026-05-17"
  },
  "statut_editorial": "passe_plat_non_valide"
}
```

- `debut` est fixé à `2001-01-01` (borne historique du substrat solaire
  amont).
- `fin` est dynamique : `aujourd'hui − 151 jours` (latence de 5 mois
  approchée à 5 × 30 jours, plus 1 jour), reflet de la latence
  temps-réel du service amont.
- Méta-endpoint permissif : il ne valide ni la localité ni la grandeur
  et ne consulte pas l'horaire stocké.

### 3.10 `GET /v1/edition` : édition publiée servie

Fraîcheur affichée (ADR-0003, D7) : chaque déploiement public sert une
édition datée de la base de référence, et l'API dit laquelle.

- Auth : non requise (même statut public que `/v1/health`)
- Réponse 200 :

```json
{
  "edition_id": "edition_AAAAMMJJ",
  "date_publication": "AAAA-MM-JJ",
  "revision_source": "<hash git court>",
  "couverture_resumee": {
    "localites": "<localités actives>",
    "series": "<séries actives>"
  }
}
```

- `revision_source` désigne la révision du dépôt public au moment de
  l'export de l'édition. Les métadonnées sont injectées par le script
  d'export dans l'édition elle-même, jamais devinées côté serveur.
- `couverture_resumee` est compté à la lecture (entiers) : localités et
  séries actives de la base servie.
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
`grandeur` (optionnel, `ghi` seul admis à ce stade ; toute autre valeur
répond `422 VALIDATION_VALEUR_INVALIDE`).

Pour un point WGS84 quelconque, retourne la localité du référentiel
dont la climatologie mensuelle échantillonne la **cellule de grille**
contenant le point. Sont candidates les localités actives à
coordonnées portant une série mensuelle active de la grandeur qui
**couvre** la normale de référence 1991-2020 (`periode_debut <=
1991-01-01` et `periode_fin` nulle ou `>= 2020-12-31`, ADR-0029) : une
série prolongée au-delà de 2020 (ADR-0018) reste candidate. La grille
est de 1 degré x 1 degré, frontières aux degrés entiers. Convention
vérifiée sur les données ivoiriennes : les 142 localités porteuses
d'une série GHI mensuelle NASA POWER donnent 35 séries distinctes pour
35 cellules occupées, y compris pour les 9 localités posées sur une
frontière entière (ADR-0029).

Le plus-proche-voisin naïf est faux et c'est la raison d'être de
l'endpoint : la localité la plus proche d'un point peut appartenir à
une autre cellule. Exemple : le point (5,35 ; −3,98) est à 9,5 km du
département d'Abidjan, mais dans la cellule [5, 6] × [−4, −3] ; il se
résout sur Grand-Bassam (32,0 km, `meme_cellule: true`), dont la série
NASA diffère de celle d'Abidjan. La résolution est un savoir éditorial
du Core, pas des consommateurs (ADR-0004).

Réponse : `point`, `grandeur`, `cellule` (bornes de la cellule),
`localite` (`code`, `nom`, coordonnées), `distance_km`,
`meme_cellule`, et `serie_climatologie` : le code de la série de
climatologie mensuelle de la localité retenue (ici
`nasa_power_ghi_mensuel_civ_dep_grand_bassam`) - le Core dit quelle
série consommer pour ce point, les clients ne le reconstruisent
jamais par convention de nommage (généricité pays). Quand aucune
candidate ne partage la cellule, `meme_cellule` vaut `false` et la
candidate la plus proche est renvoyée : le consommateur affiche alors
l'hypothèse de transport. 404 `RESSOURCE_INTROUVABLE` si le référentiel
ne porte aucune candidate pour la grandeur.

### 3.11 ter `GET /v1/calage/{localite}/{grandeur}` : référentiel de calage satellite/sol

Authentifié. Codes localité complets (`<pays>_<slug>`), alignés sur
`/v1/series` et `/v1/localites`.

Sert les biais saisonniers satellite moins sol mesurés aux stations
de référence, publiés comme donnée éditoriale de l'édition (table
`referentiels_calage`, ADR-0004) : pour chaque saison, le nom, les
mois couverts, le biais relatif mesuré et le facteur dérivé
`k = 1 / (1 + biais)`. La réponse porte la provenance (note de
calage, script reproductible, série sol de référence) et la portée
de transport : jamais un nombre nu. 404 `RESSOURCE_INTROUVABLE` pour un
couple sans référentiel publié.

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
progressive, ADR-0004). Un consommateur d'étude calée doit vérifier
que la localité résolue de son site en fait partie ; l'extension du
domaine passe par la recherche et les éditions, jamais par les
consommateurs.

Une instance sans mesure sol publie un listing vide : c'est le cas de
l'instance Côte d'Ivoire (`GET /v1/calage` :
`{"items": [], "total": 0}`).

### 3.11 quater `GET /v1/etudes/capsule` : ressource d'étude au point

Authentifié. Assemble, pour un point (`lat`, `lon`), la ressource
complète du moteur d'étude au format `kuma-ressource-1` (réponse
`text/plain`).

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `lat` | `float [-90, 90]` | | Latitude WGS84 du point |
| `lon` | `float [-180, 180]` | | Longitude WGS84 du point |
| `calage` | `bool` | `false` | `true` : ressource calibrée en ligne (appel serveur à serveur à kuma-calage) ; `false` : capsule brute, base du Core seule |
| `annee_min`, `annee_max` | `int [1900, 2100]` | | Fenêtre de la séquence horaire servie |

- Contenu : résolution du point (même règle que 3.11 bis : la série
  candidate couvre la normale 1991-2020), climatologie mensuelle (12
  valeurs, moyenne par mois de la série GHI NASA POWER mensuelle la plus
  profonde de la localité), séquence GHI horaire satellite stockée et
  validée, et records de température quand des séries journalières
  `t2m_min`/`t2m_max` existent.
- **Bornes de la fenêtre** (ADR-0029) : `annee_min` et `annee_max` ne
  contrôlent que la plausibilité (1900-2100, sinon
  `422 VALIDATION_VALEUR_INVALIDE`) ; une période de données figée
  refuserait à tort toute année ajoutée par une édition ultérieure.
  `annee_min > annee_max` : `400 VALIDATION_VALEUR_INVALIDE`. Sans
  fenêtre, toute la profondeur stockée est servie.
- Erreurs : `404 RESSOURCE_INTROUVABLE` si le point ne se résout sur
  aucune localité, si la localité résolue n'a pas de climatologie
  mensuelle NASA ou de série GHI horaire satellite, ou si la fenêtre ne
  contient aucun point horaire validé ; `503 CALAGE_INDISPONIBLE` si
  `calage=true` sur un serveur où le calage en ligne n'est pas configuré
  ou ne répond pas.
- Instance Côte d'Ivoire : faute de série horaire, la capsule répond
  `404 RESSOURCE_INTROUVABLE` (« pas de série GHI horaire satellite pour
  la localité … ») après une résolution réussie.

### 3.12 Codes d'erreur exposés par l'API

| Code | Statut HTTP type | Sens |
|---|---|---|
| `AUTH_HEADER_MANQUANT` | 401 | header `Authorization` absent |
| `AUTH_FORMAT_INVALIDE` | 401 | préfixe `Bearer ` manquant |
| `AUTH_CLE_INVALIDE` | 401 | clé absente du jeu valide |
| `VALIDATION_CHAMP_MANQUANT` | 422 | paramètre conditionnel absent (`pr_realiste`, 3.7.6) |
| `VALIDATION_VALEUR_INVALIDE` | 422 / 400 | 422 : paramètre absent, de mauvais type ou hors bornes (toute erreur de validation de requête, détail dans `details.erreurs`) ; 400 : granularité de série incompatible avec `methode` (3.7.3), POA horaire sans compagnes DNI/DHI horaires (3.7.4), `annee_min > annee_max` (3.11 quater) |
| `VALIDATION_FORMAT_DATE_INVALIDE` | 400 | date pas `YYYY-MM-DD` ni `YYYY-MM` |
| `VALIDATION_FORMAT_NON_SUPPORTE` | 400 | format autre que `json` ou `csv` |
| `VALIDATION_LIMIT_HORS_BORNES` | 400 | déclaré, non levé : un `limit` hors bornes répond `422 VALIDATION_VALEUR_INVALIDE` |
| `RESSOURCE_INTROUVABLE` | 404 | code générique de ressource manquante (édition, calage, capsule, résolution sans candidate, série horaire au détail, localité sans coordonnées, préfixe de clé) |
| `RESSOURCE_SERIE_INCONNUE` | 404 | série introuvable |
| `RESSOURCE_LOCALITE_INCONNUE` | 404 | localité introuvable, ou hors périmètre d'une route F1 |
| `CALAGE_INDISPONIBLE` | 503 | calage en ligne demandé mais non configuré ou injoignable |
| `GRANDEUR_F2_INCONNUE` | 404 | déclaré, non levé |
| `INCOMPATIBILITE_SOURCE_GRANDEUR` | 400 | série incompatible ou compagne manquante |
| `PLAGE_TEMPORELLE_NON_DISPONIBLE` | 400 / 422 | 400 : requête horaire hors plage utilisable (ou hors stocké en profil édition figée) ; 422 : grandeur F1 sans base temporelle suffisante (3.7.7) |
| `PASSE_PLAT_INDISPONIBLE` | 503 | service amont temporairement indisponible |
| `CLES_EMISSION_NON_ACTIVEE` | 404 | self-service de clés non disponible sur ce déploiement |
| `CLES_LIMITE_EMISSION_ATTEINTE` | 429 | limite d'émission de clés par IP atteinte |
| `CLES_QUOTA_JOURNALIER_DEPASSE` | 429 | quota journalier de la clé self-service dépassé |
| `INFRASTRUCTURE_BASE_INDISPONIBLE` | 503 | PostgreSQL injoignable |
| `INFRASTRUCTURE_CACHE_INDISPONIBLE` | 503 | cache (Redis) indisponible (déclaré, non levé : les compteurs sont fail-open) |
| `SERVEUR_ERREUR_INTERNE` | 500 | filet de sécurité, aucune fuite technique |

Le contrat des codes est stable : un code publié ne change pas de sens,
ne disparaît pas. Pour faire évoluer, un nouveau code est créé. Une
route ou une méthode HTTP inexistante échappe à l'enveloppe : elle
répond par défaut du framework (`404 {"detail": "Not Found"}`,
`405 {"detail": "Method Not Allowed"}`).

## 4. Les grandeurs disponibles

Le catalogue des grandeurs vit dans la table `grandeurs_referentiel`,
commune à toutes les instances. Chaque grandeur expose :

- `code` : identifiant ASCII stable, snake_case (ex. `ghi`, `hep`).
- `libelle` : titre humain (ex. Irradiation globale horizontale).
- `unite` : code et symbole d'unité issus de la table `unites`.
- `famille` : `F1` (ontologique) ou `F2` (paramétrable, calcul
  nécessitant des paramètres utilisateur).
- `strategie_calcul` : `stockee` (persistée) ou `calculee_volee`
  (recalculée à chaque consultation).
- `version_formule_actuelle` : compteur applicatif, incrémenté à chaque
  révision méthodologique.

Une instance n'alimente qu'une partie du référentiel : les séries
effectivement présentes se lisent via `/v1/series`.

### 4.1 Grandeurs brutes ingérées depuis sources externes (F1 stockée)

| Code | Libellé | Unité Kuma | Sources (instance Côte d'Ivoire) | Paramètre NASA POWER |
|---|---|---|---|---|
| `ghi` | Irradiation globale horizontale | kWh/m²/jour | NASA POWER, CAMS Radiation, SARAH-3 et ERA5 (PVGIS) | `ALLSKY_SFC_SW_DWN` |
| `dni` | Irradiation normale directe | kWh/m²/jour | NASA POWER, CAMS Radiation, SARAH-3 et ERA5 (PVGIS) | `ALLSKY_SFC_SW_DNI` |
| `dhi` | Irradiation diffuse horizontale | kWh/m²/jour | NASA POWER, CAMS Radiation | `ALLSKY_SFC_SW_DIFF` |
| `t2m` | Température à 2 m | °C | NASA POWER (MERRA-2), ERA5 (CDS) | `T2M` |
| `rh2m` | Humidité relative à 2 m | % | NASA POWER (MERRA-2) | `RH2M` |
| `vent_2m`, `vent_10m` | Vent à 2 m, à 10 m | m/s | NASA POWER (MERRA-2) ; ERA5 (CDS) pour `vent_10m` | `WS2M`, `WS10M` |
| `precipitation` | Précipitation | mm/jour | NASA POWER (MERRA-2 corrigé), ERA5 (CDS) | `PRECTOTCORR` |
| `albedo_surface` | Albédo de surface | sans dimension | NASA POWER (CERES) | `ALLSKY_SRF_ALB` |
| `pm2_5`, `pm10` | Particules fines / grossières | µg/m³ | aucune série (source prévue : CAMS EAC4) | |

Granularités de l'instance Côte d'Ivoire (révision 0044) : tout est
**mensuel** aux 142 localités (31 régions, 111 départements) ; le GHI,
le DNI, le DHI et la météo NASA POWER existent aussi en **journalier**
aux 34 localités du lot « pilotes + régions » (ADR-0016, ADR-0020). Aucune série horaire
(4.5). Les granularités et fenêtres exactes se lisent via `/v1/series`
(`granularite`, `periode_debut`, `periode_fin`).

### 4.2 Grandeurs F1 stockées calculées par Kuma (couche éditoriale)

Calculées à partir des grandeurs brutes, persistées dans
`grandeurs_metier`, exposées via la vue `v_grandeurs_metier_courantes`
(séries `kuma_calculs`, lues par `/v1/series/{code}`).

| Code | Libellé | Unité | Calcul | Entrées (instance Côte d'Ivoire) |
|---|---|---|---|---|
| `hep` | Heures équivalentes pleines | h_eq | Convention `1 kWh/m²/j <-> 1 h_eq/j à 1 kW/m² STC` ; agrégation mensuelle/annuelle de GHI | GHI mensuel des 4 sources (ADR-0023) |
| `productible_specifique_theorique` | Productible spécifique théorique | kWh/kWc (sur la période) | `hep × pr_theorique`, `pr_theorique = 0.8` ; lignes mensuelles et annuelles | `hep` calculée Kuma (ADR-0023) |
| `fraction_diffuse` | Fraction diffuse | sans dimension | `Σ DHI / Σ GHI` sur la période | DHI et GHI mensuels NASA POWER et CAMS (ADR-0014, ADR-0025) |
| `kt` | Indice de clarté | sans dimension | `Σ GHI / Σ H0` (irradiation extraterrestre calculée) | GHI mensuel des 4 sources (ADR-0026) |
| `variabilite_journaliere` | Coefficient de variation journalier | sans dimension | CoV annuel = `σ(GHI_jour) / μ(GHI_jour)`, écart-type de population | GHI journalier NASA POWER (ADR-0024) |
| `ecart_relatif_<g>_<src>_nasa` | Écarts inter-sources (7 codes) | % | `(comparée − NASA) / NASA × 100`, mensuel | GHI, DNI et DHI mensuels (ADR-0009 à ADR-0017) |
| `degenerescence_pixel` | Dégénérescence de pixel | sans dimension | Nombre d'**autres** localités dont la série mensuelle de la même famille (source, grandeur) est strictement identique ; une ligne `statique` par série mensuelle brute | Toutes les familles mensuelles brutes, rayonnement et météo (ADR-0027) |
| `humidex` | Indice de confort Humidex | °C apparents | Masterton & Richardson 1979, constantes Magnus | non calculé dans l'instance |
| `indicateur_qualite_donnees` | Score qualité de série (1-5) | sans dimension | `0.5·complétude + 0.3·confiance_moyenne + 0.2·fiabilité_source` | non calculé dans l'instance |

La dégénérescence de pixel est **mesurée**, pas déduite d'une grille :
c'est une égalité exacte des séries. Elle vaut pour toute source
maillée, pas seulement pour la cellule CERES de NASA POWER : dans
l'instance Côte d'Ivoire, le rayonnement NASA (CERES SYN1deg, 1°)
donne 35 séries distinctes pour 142 localités, la météo NASA (MERRA-2)
77, ERA5 servi par le CDS (0,25°) 110, et les sources au point
(SARAH-3, ERA5 servi par PVGIS, CAMS) 126, leurs seuls jumeaux étant
les paires région/département de mêmes coordonnées. Le commentaire de
chaque ligne dit ce que signifie le compte (maille partagée, même
point, ou point seul, qui ne vaut pas résolution au point).

### 4.3 Grandeurs F1 calculées à la volée (référentielles)

| Code | Libellé | Unité | Calcul |
|---|---|---|---|
| `ecart_relatif_referentiel` | Écart relatif GHI à un référentiel | % | Écart d'une série mensuelle NASA POWER à SARAH-3, ou à la moyenne 1991-2020 stratifiée par mois calendaire |
| `ecart_relatif_dni_cams` | Écart relatif DNI NASA vs CAMS | % | Écart mensuel de la série DNI NASA POWER à la référence CAMS |
| `rang_referentiel_temporel` | Rang dans la climatologie 1991-2020 | sans dimension | Percentile d'une valeur mensuelle dans la distribution 1991-2020 du même mois |
| `rang_referentiel_spatial` | Rang ordinal dans le pool des villes | sans dimension | Position dans le pool des localités pour le même mois |

Codes de l'instance d'origine ; aucune route ne les expose et
l'instance Côte d'Ivoire n'en grave aucune valeur. Ses écarts
inter-sources sont les grandeurs stockées `ecart_relatif_<g>_<src>_nasa`
(4.2), que la fiche `incertitude_inter_source` lit en priorité (3.7.6).

### 4.4 Grandeurs F2 paramétrables

Voir 3.7 pour les routes, modèles physiques et paramètres.

| Code | Libellé | Unité (référentiel) | Modèle physique |
|---|---|---|---|
| `poa_parametrable` | POA paramétrable | kWh/m²/jour | Perez 1990 + fallback Liu-Jordan (Erbs 1982) |
| `poa_bifacial` | POA bifacial | kWh/m²/jour | Infinite-sheds row-aware (pvlib) |
| `productible_correction_thermique` | Productible corrigé thermique | kWh/kWc/jour | NOCT simple (Ross 1980) |
| `productible_pr_fourni` | Productible avec PR fourni | kWh/kWc/jour | PR brut (Marion 2005) ou PR_T (Dierauf 2013) |
| `energie_utile_ecs` | Énergie utile ECS bord-capteur | kWh/m²/jour | Hottel-Whillier-Bliss 1958 |
| `degre_jour_climatisation` | Degrés-jours de climatisation | °C·jour | Moyenne journalière ou Erbs 1983 |

L'unité du référentiel est celle de la grandeur ; chaque résultat
renvoyé par l'API porte sa propre unité (3.7.5) : les productibles y
sont exprimés en `kWh` pour la puissance `puissance_stc_wc` demandée.

### 4.5 Grandeurs horaires

Le moteur sait stocker du substrat en granularité horaire (GHI, DNI,
DHI, T2M et compagnes selon la localité) dans
`mesures_ressource_horaires`, avec passage par contrôle qualité (statut
`valide_auto`, confiance B). Ces séries alimentent l'endpoint horaire
(3.8), le mode `integration_horaire` des routes F2 et la capsule
d'étude (3.11 quater). La couverture horaire se découvre via
`/v1/series?granularite=horaire` ; l'instance Côte d'Ivoire n'en porte
aucune.

### 4.6 Détails méthodologiques

Le dépôt contient une fiche méthodologique par grandeur calculée Kuma
sous `docs/methodologie/grandeurs/`. Chacune documente définition
formelle, politique de complétude, hypothèses physiques, limites et
historique des versions de formule ; les fiches `hep`,
`productible_specifique_theorique`, `variabilite_journaliere` et
`fraction_diffuse` ont une section « Application Côte d'Ivoire ».

## 5. Structure des données et doctrine

### 5.1 Doctrine des 3 couches de sources

La doctrine éditoriale classe chaque source dans une des 3 couches.

- Couche A, calibration terrain : mesures sol locales (au référentiel :
  la campagne ESMAP/WAPP, source `esmap_wapp`). L'instance Côte d'Ivoire
  ne grave encore aucune série sol.
- Couche B, substrat modélisé et cross-check inter-source : données
  satellitaires et de réanalyse (dans l'instance Côte d'Ivoire : NASA
  POWER, CAMS Radiation, SARAH-3 et ERA5 servis par PVGIS, ERA5 servi
  par le CDS).
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
  R3.
- `B` : confiance moyenne (modèle satellitaire ou réanalyse, source haute
  fiabilité), niveau dominant du substrat modélisé. C'est le niveau de
  toutes les mesures et valeurs calculées de l'instance Côte d'Ivoire,
  qui n'a pas encore de mesure sol.
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

### 5.4 Codes de série

Un code de série est un **identifiant opaque** : un consommateur le
découvre par le catalogue (`/v1/series` filtré par `localite`,
`grandeur`, `source`, `granularite`) ou par l'API qui le désigne
(`serie_climatologie` de la résolution, 3.11 bis), et ne le reconstruit
jamais par convention de nommage. Chaque instance nomme ses séries ;
ASCII pur, snake_case, 80 caractères au plus.

Formes de l'instance Côte d'Ivoire (à titre de lecture, pas de contrat) :

| Famille | Forme | Exemple |
|---|---|---|
| Série brute | `<source>_<grandeur>_<granularite>_<localite>` | `nasa_power_ghi_mensuel_civ_dep_abidjan`, `nasa_power_ghi_journalier_civ_dep_abidjan`, `ecmwf_era5_t2m_mensuel_civ_poro` |
| Grandeur calculée | `<grandeur>_<source>_<localite>` | `hep_nasa_power_civ_dep_abidjan`, `kt_cams_civ_dep_abidjan`, `fraction_diffuse_cams_civ_dep_abidjan` |
| Écart inter-sources | `ecart_<grandeur>_<source>_nasa_<localite>` | `ecart_ghi_sarah3_nasa_civ_dep_abidjan` |

Le jeton de source d'un code n'est pas toujours le code de la source :
`cams_ghi_mensuel_…` appartient à `cams_radiation`, `sarah3_…` à
`sarah3_monthly`, `era5_…` à `era5_pvgis` (et `ecmwf_era5_…` à
`ecmwf_era5`). Seuls `source_code` et `granularite` font foi.

### 5.5 Convention de nommage des codes de localité

| Type | Format | Exemples |
|---|---|---|
| `continent`, `region_supranationale` | slug ASCII | `afrique` |
| `pays` | ISO 3166-1 alpha-3 minuscule | `civ` |
| `region_administrative`, `prefecture`, `commune`, `site` | `<code_pays>_<slug>` | `civ_savanes` (district), `civ_poro` (région), `civ_dep_korhogo` (département) |

Dans l'instance Côte d'Ivoire, les départements portent le slug
`dep_<nom>` : un district ou une région et un département de même nom
restent distincts (`civ_abidjan`, district ; `civ_dep_abidjan`,
département ; `civ_san_pedro`, région ; `civ_dep_san_pedro`,
département).

### 5.6 Données stockées vs calculées à la volée

| Stockage | Quoi |
|---|---|
| `mesures_ressource` (journalier) | Grandeurs brutes journalières (instance Côte d'Ivoire à la révision 0044 : GHI, DNI, DHI et météo NASA POWER aux 34 localités du lot journalier) |
| `mesures_ressource_mensuelles` | Grandeurs brutes mensuelles (instance Côte d'Ivoire : rayonnement des 4 sources et météo NASA POWER et ERA5 aux 142 localités) |
| `mesures_ressource_horaires` | Horaire stocké validé par contrôle qualité (statut `valide_auto`, confiance B) ; vide dans l'instance Côte d'Ivoire |
| `grandeurs_metier` | Grandeurs F1 calculées Kuma (HEP, productible théorique, fraction diffuse, `kt`, variabilité journalière, écarts inter-sources, dégénérescence de pixel) |
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
`valide_au IS NULL` (lignes courantes) et, pour les valeurs calculées,
`statut <> 'deprecie'` (vue `v_grandeurs_metier_courantes`). Le
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

### 7.1 Sources porteuses de séries (instance Côte d'Ivoire)

| Code | Organisme | Rôle Kuma | Couche |
|---|---|---|---|
| `nasa_power` | NASA Langley Research Center | Source primaire du substrat (référence des écarts inter-sources et de la normale 1991-2020) : rayonnement (CERES) et météo (MERRA-2), mensuel et journalier | B |
| `cams_radiation` | Copernicus Atmosphere Monitoring Service / ECMWF | GHI, DNI et DHI au point, mensuels | B |
| `sarah3_monthly` | CM SAF / EUMETSAT (via PVGIS JRC) | GHI et DNI au point, mensuels | B |
| `era5_pvgis` | ECMWF, servi par PVGIS (JRC) | GHI et DNI mensuels, source de comparaison (saut de 2021 signalé dans les notes) | B |
| `ecmwf_era5` | ECMWF (Copernicus C3S), accès direct CDS | Météo mensuelle (T2M, vent à 10 m, précipitation), seconde source météo | B |
| `kuma_calculs` | Kuma | Couche éditoriale (grandeurs dérivées) | C |

### 7.2 Normes techniques mobilisées (couche C)

| Code | Norme | Rôle |
|---|---|---|
| `iec_61724_1_2021` | IEC 61724-1:2021 PV system performance - Monitoring | Conventions PV Kuma |
| `wmo_8_2024` | WMO-No.8 (CIMO Guide) Vol I 2024 | Conventions météo Kuma |

### 7.3 Sources de référence et structurelles au catalogue

Déclarées au référentiel pour la traçabilité ou l'ingestion future, sans
série dans l'instance Côte d'Ivoire :

| Code | Organisme | Rôle |
|---|---|---|
| `esmap_wapp` | World Bank / ESMAP / WAPP | Mesures sol Tier-1 (couche A, `mesure_directe`) |
| `cams_eac4` | Copernicus Atmosphere Monitoring Service / ECMWF | Particules PM2.5/PM10 (proxy salissure) |
| `ecmwf_era5_land` | ECMWF (Copernicus C3S) | Réanalyse land haute résolution |
| `wmo_grdc`, `wwf_hydrosheds`, `iec_60041_1991`, `wmo_168_2008` | divers | Vecteur hydro structurel (schéma prévu, ingestion différée) |

## 8. Découvrir la couverture

Les volumes (nombre de séries, de mesures) et la liste exacte des
localités couvertes dépendent du mode d'ingestion du déploiement et se
découvrent via l'API, pas via des compteurs figés dans ce document :

- `GET /v1/series` : catalogue des séries (filtres `localite`,
  `grandeur`, `source`, `granularite`) ; le champ `total` donne le
  nombre matchant les filtres.
- `GET /v1/localites` : référentiel géographique, hiérarchie et
  recherche `q`.
- `GET /v1/grandeurs/incertitude_inter_source` : périmètre de l'atlas
  d'incertitude (points portant l'écart inter-source).
- `/docs` (OpenAPI, hors production) : schémas complets et essai
  interactif.

Faits de couverture de l'instance Côte d'Ivoire à la révision 0044
(indépendants du volume ingéré) :

- Localités : le pays, 14 districts, 31 régions, 111 départements. Les
  séries sont portées par les 31 régions et les 111 départements ; les
  districts n'en portent aucune.
- Granularités : mensuel et journalier ; pas d'horaire.
- Normale climatologique de référence : 1991-2020, couverte par les
  séries NASA POWER et ERA5 (CDS), qui vont au-delà (ADR-0018).
- Rayonnement mensuel : NASA POWER (GHI 1991-2025, DNI et DHI
  2001-2025), CAMS Radiation 2005-2025, SARAH-3 et ERA5 (PVGIS)
  2005-2023.
- Météo mensuelle : NASA POWER 1991-2025 (albédo 2001-2025), ERA5 (CDS)
  1991-2025.
- Journalier NASA POWER : 34 localités (31 régions, départements
  d'Abidjan, Yamoussoukro et Korhogo), GHI 1991-2025, DNI et DHI
  2001-2025.
- Atlas d'incertitude inter-source : fenêtre 2021-2023.
