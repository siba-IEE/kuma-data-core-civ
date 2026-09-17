# Changelog

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et
le projet suit le versionnement sémantique.

## Non publié

### Ajouté

- Jalon 2 (donnée solaire brute) — irradiation mensuelle **NASA POWER** aux
  départements d'Abidjan, Yamoussoukro et Korhogo, confiance B (satellite),
  unité kWh/m²/jour héritée de la grandeur (contrat de série ADR-0007) :
  - **GHI** 1991-2020, 3 séries × 360 mesures (migration 0008) ;
  - **DNI** 2001-2020, 3 séries × 240 mesures (migration 0009) — NASA POWER ne
    fournit le DNI qu'à partir de 2001 ; chaque série documente sa période.
  Ingesteur reproductible hors-ligne, paramétré par grandeur
  (`scripts/ingest_nasa_power_mensuel.py`) → seed → migration ; garde-fous
  bornes physiques, complétude et anti-remplissage (`-999`).
- Densification sourcée des 14 districts de Côte d'Ivoire (migration 0004) :
  coordonnées (point représentatif Wikidata `P625`), population RGPH 2021
  (INS Côte d'Ivoire, total district agrégé des régions) et chef-lieu.
  Doctrine « aucune coordonnée inventée » respectée ; l'altitude d'une région
  reste `NULL`.
- Densification sourcée du pays `civ` (migration 0005) : centroïde Wikidata
  Q1008 (`P625`) et population nationale RGPH 2021 (29 389 150 hab.), recoupée
  par la somme des 14 districts.
- 111 départements ivoiriens au niveau générique `commune` (migration 0007) :
  108 rattachés à une région, 3 aux districts autonomes (Abidjan,
  Yamoussoukro) via `commune → region_administrative`. Rattachement Wikidata
  `P131` (Kani → Worodougou, lacune P131 comblée par source), coordonnées
  `P625` (Attiégouakro : repli chef-lieu, sans P625). 6 anciens départements
  dissous écartés. Aucun code ISO (standard limité aux districts).
  **Population RGPH 2021** (INS, via data.gouv.ci / citypopulation.de) portée
  par chaque département : la somme par région reproduit le total régional
  (écart ≤ 1) et le total national vaut 29 389 150 (exact). Deux libellés
  corrigés : `Oumé` (ex `d'Oumé`) et `Niakaramandougou` (orthographe officielle).
- 31 régions ivoiriennes au niveau générique `prefecture` (migration 0006,
  cf. ADR-0005) : rattachées à leur district (Wikidata `P131`), coordonnées
  `P625`, population RGPH 2021 (somme exacte par district). Réserves tracées
  en notes : N'Zi/La Mé mono-sourcées, coordonnée Hambol repliée sur son
  chef-lieu (P625 région erroné), anciens codes ISO 3166-2 région (périmés
  depuis la révision 2020) jamais gravés comme courants.

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
