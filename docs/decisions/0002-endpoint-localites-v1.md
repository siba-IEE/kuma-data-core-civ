# ADR-0002 · Endpoint `/v1/localites` pour outils consommateurs

> **Statut** · Accepté · 2026-05-18

## Contexte

L'[ADR-0001](./0001-contrat-v1-series-enrichi.md) a enrichi `/v1/series` avec dénormalisations location/grandeur/source. Mais les pages localités d'un consommateur ont besoin de **métadonnées de localité riches** qui ne sont pas exposées dans `/v1/series` :

- Coordonnées géographiques précises (latitude, longitude décimales Numeric(11,8)/(12,8))
- Altitude
- Population estimée + année du décompte
- Fuseau horaire IANA
- Type de localité (continent, pays, region_administrative, commune, site)
- Hiérarchie parent (`parent_id` + `parent_code` direct)

Toutes ces données existent en base (table `localites`, modèle SQLAlchemy `Localite`). Elles ne sont juste pas exposées via l'API.

Cet ADR documente l'ajout d'un nouveau routeur `/v1/localites` cohérent avec le pattern `/v1/series` (ADR-0001) pour servir les pages localités des consommateurs.

## Décision

### Nouveau routeur `/v1/localites`

Deux endpoints exposés sous le préfixe `/v1/localites` :

| Verbe + Path | Description | Réponse |
|---|---|---|
| `GET /v1/localites` | Listing paginé avec filtres | Enveloppe `LocaliteListeePaginee` `{items, total, limit, offset}` |
| `GET /v1/localites/{code}` | Détail individuel | `LocaliteDetail` (alias de `LocaliteListee` pour cette itération) |

### Schéma Pydantic `LocaliteListee` (16 champs)

| Catégorie | Champs |
|---|---|
| Identifiants | `id`, `code`, `nom` |
| Type et hiérarchie | `type_localite`, `parent_id`, `parent_code` |
| Géolocalisation | `pays_iso3`, `latitude`, `longitude`, `altitude_metres` |
| Démographie | `population_estimee`, `annee_population` |
| Métadonnées techniques | `fuseau_horaire` |
| Audit | `created_at`, `updated_at` |
| Flag actif | `actif` |

### Filtres listing

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `pays_iso3` | `str \| None` | `None` | Filtre ISO 3166-1 alpha-3 (ex. `GIN`) |
| `type_localite` | `str \| None` | `None` | Filtre type (`continent`, `pays`, `commune`, `site`, …) |
| `parent_code` | `str \| None` | `None` | Filtre code de la localité parente |
| `actif` | `bool \| None` | `True` | Filtre soft-delete |
| `limit` | `int [1, 1000]` | `100` | Pagination - cohérent avec `/v1/series` |
| `offset` | `int >= 0` | `0` | Pagination |

### Conventions alignées sur `/v1/series` (ADR-0001)

- **Routes au pluriel** (`/localites` et `/series`) - cohérent avec le pattern producteur API
- **IDs en `int` natif** (`BigInteger DB`), pas UUID. Mapping `z.number().int().positive()` côté consommateur
- **Datetimes en ISO-8601 UTC** avec suffixe `Z`
- **Renommage public** ≠ noms DB internes (mapping via `AS` en SQL, pas `Field(alias=...)`) :
  - `created_at` ← `localites.cree_le`
  - `updated_at` ← `localites.modifie_le`
- **`parent_code` dénormalisé** via self-JOIN `LEFT JOIN localites P ON L.parent_id = P.id` - évite un appel en cascade côté consommateur pour résoudre la hiérarchie
- **`latitude`/`longitude` exposés en `float`** (converti depuis Numeric DB). Précision pratique 7-8 décimales (1 cm), suffisante pour la cartographie éditoriale Kuma
- **Authentification** Bearer admin obligatoire (`CleApiValidee`)
- **Erreur 404** typée via `ExceptionKuma` + `CodeErreur.RESSOURCE_LOCALITE_INCONNUE` (nouveau code ajouté au catalogue stable)
- **COUNT séparé** du SELECT items pour lisibilité - acceptable jusqu'à plusieurs centaines de localités

### Périmètre non couvert

- Pas de hiérarchie récursive complète exposée (juste `parent_id` + `parent_code` direct). Pour afficher "Guinée > Conakry > Kaloum", le consommateur fait 2-3 appels en cascade. Stratégie `WITH RECURSIVE` reportée si le besoin est exprimé
- Pas d'expansion des séries associées dans le détail localité (le consommateur fait `GET /v1/series?localite={code}` séparément - pattern série/mesures déjà éprouvé)
- Pas d'endpoint `/v1/series/by-localite/{code}` raccourci. Si pattern d'usage récurrent, à arbitrer ultérieurement
- Pas de versioning du contrat (toujours implicitement v1 sous le path)

## Conséquences

### Positives

- **Pages localités consommateur** : elles peuvent être construites sans appel cascade complexe - un seul appel `/v1/localites/{code}` retourne les 16 champs métadonnées
- **Pattern de "ressource métadonnées" établi** : peut être étendu à d'autres tables référentiel (`sources`, `grandeurs_referentiel`, `unites`) pour en faire des pages catalogue dédiées
- **Aucun impact sur `/v1/series` existant** : cet ajout est un endpoint complémentaire, ne modifie aucun contrat existant. Pas de risque de régression
- **Aucune migration Alembic** : tous les champs existent déjà (migration 003 `localites` + migration 005 FK contributeurs)

### Acceptées comme dette

- Pas de hiérarchie complète exposée - si le besoin se confirme, ajouter une résolution récursive (30 lignes SQL `WITH RECURSIVE` + champ `parents: list[str]`)
- Pas d'expansion des séries associées dans le détail - si pattern d'usage récurrent, considérer un champ `nb_series` dénormalisé (compteur) avant de basculer sur expansion complète

### Côté consommateurs

- Un consommateur peut récupérer les localités et en générer un snapshot statique plutôt que d'appeler l'API au runtime
- **Outils futurs** : pattern à réutiliser pour d'autres ressources référentiel

## Implémentation

### Fichiers ajoutés / modifiés

| Fichier | Action | Lignes |
|---|---|---|
| `src/kuma_data_core/api/v1/schemas/localites.py` | créé | 85 |
| `src/kuma_data_core/api/v1/localites.py` | créé | 270 |
| `src/kuma_data_core/api/v1/routeur.py` | +1 ligne `include_router(localites.routeur)` |
| `src/kuma_data_core/api/codes_erreur.py` | +1 ligne `RESSOURCE_LOCALITE_INCONNUE` |
| `tests/integration/api/test_localites.py` | créé (9 tests) | 210 |
| `docs/decisions/0002-endpoint-localites-v1.md` | créé | ce document |

### Stratégie SQL `parent_code` dénormalisé

```sql
SELECT
    L.id, L.code, L.nom, L.type_localite,
    L.parent_id, P.code AS parent_code,   -- ← self-JOIN
    L.pays_iso3, L.latitude, L.longitude, L.altitude_metres,
    L.population_estimee, L.annee_population,
    L.fuseau_horaire,
    L.cree_le AS created_at, L.modifie_le AS updated_at,
    L.actif
FROM localites L
LEFT JOIN localites P ON L.parent_id = P.id
WHERE <filtres conditionnels>
ORDER BY L.code
LIMIT :limit OFFSET :offset
```

Performance : self-JOIN sur 10-20 localités = trivial. À monitorer si la table dépasse plusieurs milliers d'entrées (cas non anticipé). Pas d'index supplémentaire nécessaire - l'index existant `idx_localites_parent_id` couvre le `LEFT JOIN`.

### Stratégie conversion `Decimal` → `float`

Les colonnes `latitude` / `longitude` sont déclarées en `Numeric(11,8)` / `Numeric(12,8)` côté DB pour la précision (8 décimales = 1 mm à l'équateur, niveau levés professionnels). SQLAlchemy les retourne comme `decimal.Decimal`, non sérialisable en JSON natif.

Helper `_to_float_optional()` converti vers `float | None` avant l'instanciation Pydantic. Précision pratique conservée : float64 IEEE 754 -> 15-17 chiffres significatifs, largement supérieur aux 7-8 décimales nécessaires pour la cartographie éditoriale.

**Acceptation explicite** : pour des usages métrologiques rigoureux (jamais sur cet endpoint), il faudrait conserver `Decimal` jusqu'à la sortie texte CSV. Ici, JSON + cartographie web = float64 suffit.

## Validation

- **Tests d'intégration** (9 tests) :
  - 401 sans auth, 200 listing avec envelope + 16 champs, filtres `pays_iso3`/`type_localite`/`parent_code`/`actif`, pagination cohérente, détail Kaloum avec coordonnées plausibles, 404 typé sur code inconnu
- **`ruff check`** sur nouveaux fichiers : 0 violation
- **`mypy --strict`** sur nouveaux fichiers : 0 erreur
- **Pas d'impact** sur les suites `test_series.py`, `test_grandeurs.py`, `test_horaire.py`, `test_health.py`

## Cross-references

- [ADR-0001](./0001-contrat-v1-series-enrichi.md) - Contrat `/v1/series` enrichi
- Modèle SQLAlchemy : [`src/kuma_data_core/db/models/localites.py`](../../src/kuma_data_core/db/models/localites.py)
