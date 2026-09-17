# Changelog

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et
le projet suit le versionnement sémantique.

## Non publié

### Ajouté

- Densification sourcée des 14 districts de Côte d'Ivoire (migration 0004) :
  coordonnées (point représentatif Wikidata `P625`), population RGPH 2021
  (INS Côte d'Ivoire, total district agrégé des régions) et chef-lieu.
  Doctrine « aucune coordonnée inventée » respectée ; l'altitude d'une région
  reste `NULL`.
- Densification sourcée du pays `civ` (migration 0005) : centroïde Wikidata
  Q1008 (`P625`) et population nationale RGPH 2021 (29 389 150 hab.), recoupée
  par la somme des 14 districts.

## 0.1.0

Amorçage de l'instance Côte d'Ivoire, à partir d'un socle propre.

- Schéma : baseline unique regroupant le schéma complet du moteur (tables, vues,
  contraintes, index, fonctions PL/pgSQL, triggers d'audit et de validation
  hiérarchique, extension `btree_gist`), sans donnée.
- Référentiels génériques : unités, catalogue des grandeurs, sources amont (NASA
  POWER, ERA5 et ERA5-Land, SARAH-3 via PVGIS, CAMS, ESMAP/WAPP, normes IEC et
  WMO).
- Localités : le pays `civ` (ISO 3166-1 alpha-3 : CIV) et les 14 districts (dont
  Abidjan et Yamoussoukro, autonomes), nomenclature ISO 3166-2:CI. Coordonnées,
  population et niveaux inférieurs (régions, départements) à venir.
- Ingestion en mode direct (appel des sources amont), sans repli hors-ligne sur
  seed.
