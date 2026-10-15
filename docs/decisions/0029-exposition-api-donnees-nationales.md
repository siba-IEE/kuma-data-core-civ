# ADR-0029 : exposer les données nationales par l'API (localités, séries, études)

Date : 2026-10-15. Statut : accepté.

## Contexte

Les lots nationaux (ADR-0015 à ADR-0018) ont porté la base à 157 localités
ivoiriennes (1 pays, 14 districts, 31 régions, 111 départements), 2 658 séries,
381 696 mesures mensuelles, 1 055 564 journalières et 283 006 valeurs dérivées.
Chaque endpoint du périmètre « données » a été appelé sur ces données réelles.
Quatre défauts relevaient d'hypothèses de l'instance pilote, figées dans le
code plutôt que lues dans la donnée :

1. **Résolution au point** (`/v1/localites/resolution`, ADR-0004) : les
   candidates étaient les séries de période **exactement** 1991-2020. Depuis
   l'extension 2021-2025 (ADR-0018), les séries vont jusqu'en 2025 : aucune
   candidate, 404 sur tout le territoire. La normale 1991-2020 reste la
   référence ; c'est l'égalité qui était fausse.
2. **Troncature silencieuse** (`/v1/series/{code}`) : le détail renvoie
   1 000 mesures par défaut, sans dire combien la série en compte. Une série
   journalière de 35 ans en compte 12 784 ; une moyenne calculée sur la
   réponse par défaut portait sur 1991-1993. ADR-0001 l'avait consigné en
   dette.
3. **Granularité invisible** : le catalogue ne permettait ni de filtrer ni de
   lire la granularité d'une série (mensuelle et journalière NASA coexistent
   pour la même localité, la même source et la même grandeur).
4. **Constantes d'instance** : préfixe pays `gin_` codé pour les alias courts
   de `/v1/horaire`, fenêtre `annee_min`/`annee_max` de `/v1/etudes/capsule`
   bornée à 2001-2025, années de mesure bornées à partir de 1991 dans les
   schémas de réponse (la base admet 1981).

## Décision

### Résolution : couvrir la normale, pas l'égaler

Une série mensuelle est candidate si `periode_debut <= 1991-01-01` et
`periode_fin >= 2020-12-31` (ou ouverte). La convention de cellule (1 degré,
frontières entières) est **vérifiée sur les données ivoiriennes** : sur les
142 localités porteuses d'une série GHI mensuelle NASA POWER, 35 empreintes
distinctes de série correspondent exactement à 35 cellules, y compris pour les
9 localités posées sur une frontière entière. Un test d'intégration garde
cette propriété.

### Pagination explicite des mesures

`SerieDetail` porte `pagination_mesures = {total, limit, offset}` : `total`
compte les mesures de la fenêtre `from`/`to`, toutes pages confondues. Le
défaut (1 000) et le maximum (10 000) ne changent pas. La réponse CSV porte le
même total dans l'en-tête `X-Kuma-Mesures-Total`. Le tri des valeurs dérivées
est rendu total (`annee_debut`, `mois`, puis `annee_fin`, `periode_type`, `id`)
pour paginer sans perte ni doublon une série qui mêle valeurs annuelles et
mensuelles.

### Granularité au catalogue

Champ `granularite` (`journalier`, `mensuel`, `horaire`, ou `null` pour les
grandeurs calculées, routées par source) et filtre `?granularite=` sur
`GET /v1/series`. Ajouts rétrocompatibles.

### Recherche de localités

Paramètre `?q=` sur `GET /v1/localites` : le nom contient le texte saisi
(insensible à la casse) **ou** le code contient sa forme normalisée (sans
accents, ponctuation ramenée à `_`). Le code étant le slug ASCII du nom, la
recherche devient insensible aux accents sans extension ni table de
correspondance (« Agneby » trouve « Agnéby-Tiassa », « san pedro » trouve
« San-Pédro »).

### Plus de constante d'instance

- Alias courts de `/v1/horaire` : le préfixe est le code d'un pays présent au
  référentiel (`type_localite = 'pays'`) ; un code court qui désigne des
  localités de plusieurs pays est ambigu (404 avec la liste des candidats).
- Fenêtre horaire des études : bornes de plausibilité (1900-2100) ; une
  fenêtre sans donnée répond 404.
- Schémas de réponse : bornes recopiées des contraintes de la base (mensuel
  1981-2099 ; dérivées non bornées, `valeur` nullable comme la colonne).
- Relais horaire d'une localité sans coordonnées : 404 explicite au lieu
  d'une erreur 500.

## Conséquences

- Les données ivoiriennes sont lisibles de bout en bout par l'API ; les
  absences (aucune donnée horaire, aucune mesure sol) répondent par une
  erreur propre et typée.
- Le contrat ne perd rien : deux champs (`granularite`,
  `pagination_mesures`), deux paramètres (`granularite`, `q`) et un en-tête
  CSV s'ajoutent.
- **Reste à appliquer hors de ce périmètre** : l'acquisition de la capsule
  d'étude (`services/capsule/acquisition.py`) porte la même égalité stricte
  1991-2020 que la résolution ; sans la même correction, `/v1/etudes/capsule`
  répond « aucun point d'ingestion de climatologie » au lieu de l'absence de
  séquence horaire. L'index `grandeurs_metier (series_metadonnees_id, …)
  WHERE valide_au IS NULL` est proposé pour que la lecture d'une série
  dérivée cesse de parcourir toute la table.
