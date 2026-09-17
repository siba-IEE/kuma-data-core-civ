# ADR-0001 · Contrat `/v1/series` enrichi

> **Statut** · Accepté · 2026-05-18

## Contexte

Une revue du contrat `/v1/series` a identifié un drift majeur entre :

- ce qu'exposait le contrat `/v1/series` (9 champs minimalistes, tableau JSON nu)
- ce qu'attendait un consommateur type (23 champs avec dénormalisations + envelope paginée)

L'approche retenue est hybride : enrichir l'API sur ce qui est déjà en base, laisser le consommateur adapter son schéma pour les champs lourds qui demandent une décision méthodologique.

Cet ADR documente la mise en œuvre de la partie courte terme côté API.

## Décision

### Périmètre retenu

| Catégorie de drift | Statut | Lignes Python |
|---|---|---|
| **9 champs dénormalisés** déjà présents en base | Livré | 30 |
| **10 drifts nom/type** (renames + types `int`) | Livré | inline |
| **Envelope paginée** `{items, total, limit, offset}` | Livré | 15 |

### Périmètre reporté

| Catégorie | Pourquoi reporté |
|---|---|
| **5 champs au niveau MESURE** (`niveau_confiance_derive`, `niveau_confiance_override`, `statut_editorial`, `valide_du`, `valide_au`) | Nécessite une décision méthodologique d'agrégation mesure->série. Choix possibles : max, mode, niveau le plus représenté, pondération par récence. À arbitrer. |
| **`indicateur_qualite_donnees`** (formule 5 axes) | La formule (50 % complétude + 30 % confiance moyenne + 20 % fiabilité source) est documentée côté consommateur mais n'a pas d'implémentation API. Nécessite migration + service de calcul + décision méthodologique. |
| **Drift sémantique `grandeur_family`** | Décision en suspens : ajouter un champ `famille_metier` côté API ou laisser le consommateur accepter la sémantique actuelle. |
| **Endpoint dédié `/v1/series/{code}/mesures`** | Gap fonctionnel mineur. Aujourd'hui les mesures sont paginées via le détail, ce qui force à re-télécharger les métadonnées série à chaque page. |
| **Limite par défaut du détail (1000 mesures)** | Tronque silencieusement les séries 5 ans journalières (1826 points). Soit augmenter le défaut à 10 000, soit séparer méta/mesures via l'endpoint ci-dessus. |

## Implémentation

### Schéma Pydantic - `SerieListee` enrichi (18 champs)

`src/kuma_data_core/api/v1/schemas/series.py` :

```python
class SerieListee(BaseModel):
    # Identifiants (BigInteger natif, pas UUID - cf. §nommage public)
    id: int
    code: str = Field(min_length=1, max_length=80)
    libelle: str

    # Localité (dénormalisée)
    localite_id: int
    localite_code: str
    localite_nom: str
    localite_iso3: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    # Grandeur (dénormalisée)
    grandeur_code: str
    grandeur_label: str  # ← grandeurs_referentiel.libelle
    grandeur_unit: str   # ← unites.symbole

    # Source (dénormalisée)
    source_id: int
    source_code: str
    source_label: str  # ← sources.titre
    source_url: str | None

    # Période et méta éditoriales
    periode_debut: date
    periode_fin: date | None
    methode_collecte: str | None
    notes_fr: str | None  # ← series_metadonnees.commentaire_editorial

    # Audit
    created_at: datetime  # ← cree_le
    updated_at: datetime  # ← modifie_le

    # Flag actif
    actif: bool
```

### Schéma Pydantic - `SerieListeePaginee` (envelope)

```python
class SerieListeePaginee(BaseModel):
    items: list[SerieListee]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
```

### Schéma Pydantic - `SerieDetail` (héritage automatique)

Hérite des 18 champs de `SerieListee` enrichi + ses propres `unite_code` et `mesures: list[MesureLue]`.

### Requête SQL - JOINs ajoutés

`src/kuma_data_core/api/v1/series.py` - listing et détail :

- JOIN `grandeurs_referentiel gr ON gr.code = sm.grandeur_code`
- JOIN `unites u ON u.id = gr.unite_id`
- Enrichissement des projections sur les JOINs existants `localites` et `sources`

Performance : 4 JOINs au lieu de 2. Acceptable sur 96 séries (FK indexées). À monitorer si la couverture passe à plusieurs centaines de séries : possibilité de basculer sur une vue matérialisée `v_series_catalogue_enrichi` si nécessaire.

### Stratégie `total` - COUNT séparé

Option simple retenue : `SELECT COUNT(*) FROM series_metadonnees ... WHERE <mêmes filtres>` exécuté séparément du SELECT items. Plus lisible et suffisant pour 96 séries. Window function `COUNT(*) OVER()` à considérer si benchmark le justifie ultérieurement.

## Nommage public côté contrat ≠ nommage DB

Convention assumée : les noms exposés côté API publique sont alignés sur le contrat attendu par les consommateurs, **pas** sur les noms internes des colonnes DB.

Mapping :

| Côté contrat public | ← | Colonne DB |
|---|---|---|
| `source_label` | ← | `sources.titre` |
| `grandeur_label` | ← | `grandeurs_referentiel.libelle` |
| `grandeur_unit` | ← | `unites.symbole` |
| `notes_fr` | ← | `series_metadonnees.commentaire_editorial` |
| `created_at` | ← | `series_metadonnees.cree_le` |
| `updated_at` | ← | `series_metadonnees.modifie_le` |
| `localite_nom` | ← | `localites.nom` |
| `localite_iso3` | ← | `localites.pays_iso3` |
| `source_url` | ← | `sources.url` |

Justification :

- Stabilité du contrat public face aux évolutions DB internes
- Lisibilité pour les consommateurs externes qui ne connaissent pas la convention de nommage interne (FR vs EN, abréviations, etc.)
- Cohérence sémantique : `source_label` est plus clair que `titre`, `created_at` est le standard de l'industrie pour les timestamps

Le mapping est porté par les `AS` dans les SELECT SQL, pas par des `Field(alias=...)` Pydantic. Ce choix garde la cohérence Pydantic↔code (les attributs Python correspondent exactement aux clés JSON exposées).

## Décision sur les IDs - BigInteger natif

Les IDs `id`, `localite_id`, `source_id` sont exposés en `int` natif (sérialisé en JSON number), pas en string UUID. Cohérent avec le modèle relationnel Data Core qui utilise `BigInteger Identity` partout.

**Conséquence côté consommateur** : un schéma de validation `z.uuid()` doit être adapté en `z.number().int().positive()`. C'est un changement trivial (5 lignes).

## Conséquences

### Positives

- Un consommateur peut désormais construire son catalogue avec les 96 vraies séries de l'API (au lieu d'un jeu factice)
- Les vues catalogue et fiches détail disposent de la localité, la grandeur et la source dénormalisées, ainsi que de la période complète
- L'envelope paginée résout un drift documenté côté consommateur : c'est un *alignement* de contrat, pas une introduction de drift
- Les performances JOIN sont mesurées et acceptables sur 96 séries (50 ms par requête en local)

### Dettes acceptées

- Les zones « qualité » et « confiance / couche » restent sur des valeurs dégradées côté consommateur tant que les champs mesure et l'indicateur de qualité ne sont pas livrés
- La limite par défaut du détail (1000 mesures) reste imprécise pour les séries journalières 5 ans, à corriger ultérieurement
- Pas de versioning d'URL (`/v1/` reste `/v1/`) malgré le breaking change envelope -> tableau. Risque limité car l'API est privée Bearer admin

### Breaking change documenté

`GET /v1/series` retourne désormais un objet `{items, total, limit, offset}` au lieu d'un tableau nu. Tout consommateur doit adapter son parsing. Si un autre consommateur émerge, il faudra arbitrer un versioning `/v2/series` ou adapter le consommateur.

## Cross-references

- Tests d'intégration : `tests/integration/api/test_series.py`
