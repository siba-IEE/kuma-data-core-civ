# Guide de contribution de données

Ce dépôt est le moteur. Les données nationales vivent dans des dépôts RDS par
pays ([rds-guinee](https://github.com/siba-IEE/rds-guinee), puis d'autres). Ce
guide explique comment une donnée est modélisée dans le Core, pour que vous
sachiez ce que vous contribuez, quel que soit l'endroit où elle atterrit.

## Le modèle, entité par entité

- **Localité** : le lieu. Une hiérarchie à sept niveaux (continent, région
  supranationale, pays, région administrative, préfecture, commune, site) avec
  un code `pays_iso3`. Le pays est un niveau de cette hiérarchie, pas une
  notion câblée en dur (voir [généricité pays](genericite-pays.md)).
- **Source** : la provenance. Une source ouverte (satellite, réanalyse,
  station) porte une fiabilité (`haute`, `moyenne`, `faible`).
- **Grandeur** : ce qui est mesuré. Deux niveaux : le référentiel
  (`grandeurs_referentiel`, la définition catalogue) et la valeur métier
  (`grandeurs_metier`, une valeur calculée ou stockée).
- **Série** (`series_metadonnees`) : un quadruplet (localité, grandeur, source,
  période). Elle porte la méthode de collecte (`mesure_directe`,
  `modele_satellitaire`, `expertise_humaine`, entre autres).
- **Mesure** : la valeur elle-même, journalière, mensuelle ou horaire, avec sa
  date, sa valeur, sa confiance, son statut et sa validité temporelle.

## Trois propriétés de première classe

Chaque valeur porte, en plus de sa source et de sa méthode :

- une **confiance** A/B/C dérivée par des règles, avec override motivé ;
- un **statut éditorial** (de `brut` à `publie`) ;
- une **validité temporelle** : rien n'est écrasé en place. Une nouvelle valeur
  supplante l'ancienne par versionnement (`valide_du`, `valide_au`) ; les
  lectures ne renvoient que la version courante.

Le détail est dans [confiance et statuts](confiance-et-statuts.md).

## Comment une donnée entre aujourd'hui

L'insertion passe par la couche d'ingestion (`kuma_data_core.ingestion`), des
fonctions qui insèrent à partir d'une session (par exemple
`ingerer_serie_daily(*, session, ...)`). Ces fonctions sont appelées par les
migrations. Un chemin de contribution direct, un loader qui verse un RDS
national sans écrire de migration, est en construction (voir la [feuille de
route](../../ROADMAP.md)).

## Où contribuer

- **Données nationales** : dans le dépôt RDS du pays concerné.
- **Moteur, connecteurs, méthodes** : ici, via les [issues](https://github.com/siba-IEE/kuma-data-core/issues).

Conventions de nommage et de schéma :
[docs/conventions/01-naming.md](../conventions/01-naming.md).
