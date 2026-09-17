# Feuille de route

Instance dédiée à la Côte d'Ivoire du moteur Kuma Data Core. Le moteur est
générique (le pays est un axe de classification) ; cette feuille de route couvre
l'amorçage et la montée en charge de la donnée ivoirienne.

## Jalon 1 : localités

- [x] Pays `civ` et 14 districts (`region_administrative`), nomenclature
      ISO 3166-2:CI.
- [x] Densification sourcée des 14 districts : coordonnées (Wikidata `P625`),
      population RGPH 2021 (INS Côte d'Ivoire), chef-lieu (migration 0004).
- [x] Densification du pays `civ` : centroïde (Wikidata Q1008) et population
      nationale RGPH 2021 (migration 0005).
- [x] Arrêter le mapping de la hiérarchie ivoirienne sur les 7 niveaux du
      schéma (modèle générique A) : district → `region_administrative`,
      région → `prefecture`, département → `commune`, sous-préfecture →
      `site`. Voir [ADR-0005](decisions/0005-mapping-hierarchie-administrative-civ.md).
- [x] 31 régions (`prefecture`) avec coordonnées (Wikidata `P625`),
      population RGPH 2021 (INS) et rattachement au district (Wikidata `P131`),
      migration 0006.
- [x] 111 départements (`commune`) : 108 sous région + 3 sous districts
      autonomes, rattachement Wikidata `P131`, coordonnées `P625`, et
      population RGPH 2021 (INS, via data.gouv.ci / citypopulation.de ; somme
      départements = total région, national 29 389 150 exact) — migration 0007.

## Jalon 2 : donnée solaire brute

- [ ] Séries et mesures brutes par source (NASA POWER, SARAH-3 via PVGIS, CAMS,
      ERA5-Land) aux points ivoiriens, en confiance B.
  - [x] GHI mensuel NASA POWER, 1991-2020, 3 points (Abidjan, Yamoussoukro,
        Korhogo), confiance B (migration 0008, ADR-0007).
  - [x] DNI mensuel NASA POWER, 2001-2020 (couverture DNI NASA POWER), mêmes
        3 points (migration 0009).
  - [x] GHI mensuel SARAH-3 (PVGIS), 2005-2020, mêmes 3 points (migration
        0010, ADR-0008) — 2ᵉ source, écart inter-source calculable en base
        (SARAH-3 systématiquement plus haut que NASA POWER, +7 à +17 %).
  - [ ] DHI, autres points, CAMS/ERA5-Land.
- [ ] Chaîne d'ingestion reproductible.
  - [x] Ingesteur NASA POWER mensuel (`scripts/ingest_nasa_power_mensuel.py`,
        paramétré par grandeur, hors-ligne → seed → migration ; garde-fous
        bornes/complétude/anti-remplissage).

## Jalon 3 : grandeurs et qualité

- [x] **Première grandeur dérivée** : écart inter-source relatif du GHI
      SARAH-3 vs NASA POWER (`ecart_relatif_ghi_sarah3_nasa`, `stockee`),
      matérialisé dans `grandeurs_metier` sur la fenêtre commune 2005-2020
      (576 lignes, confiance B) — migration 0011, [ADR-0009](decisions/0009-grandeur-derivee-ecart-inter-source-ghi.md).
- [ ] Grandeurs métier calculées (POA, productible, P50/P90, salissure, PR
      réaliste) exposées par l'API.
- [ ] Contrôle qualité horaire.

## Jalon 4 : terrain (confiance A)

- [ ] Intégrer des stations sol ouvertes en Côte d'Ivoire comme première ancre de
      confiance A, et le calage terrain associé.

## Documentation

- [ ] Adapter `docs/` au contexte ivoirien.
