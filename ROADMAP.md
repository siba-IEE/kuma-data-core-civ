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
- [ ] 31 régions (`prefecture`) avec coordonnées, population et sourçage
      (Wikidata, HDX/COD-AB, INS Côte d'Ivoire).
- [ ] 108 départements (niveau `commune` ou `site` selon le mapping retenu), même
      exigence de sourçage.
- [ ] Arrêter le mapping de la hiérarchie ivoirienne (district, région,
      département, sous-préfecture, commune) sur les 7 niveaux du schéma.

## Jalon 2 : donnée solaire brute

- [ ] Séries et mesures brutes par source (NASA POWER, SARAH-3 via PVGIS, CAMS,
      ERA5-Land) aux points ivoiriens, en confiance B.
- [ ] Chaîne d'ingestion reproductible.

## Jalon 3 : grandeurs et qualité

- [ ] Grandeurs métier calculées (POA, productible, P50/P90, salissure, PR
      réaliste) exposées par l'API.
- [ ] Contrôle qualité horaire.

## Jalon 4 : terrain (confiance A)

- [ ] Intégrer des stations sol ouvertes en Côte d'Ivoire comme première ancre de
      confiance A, et le calage terrain associé.

## Documentation

- [ ] Adapter `docs/` au contexte ivoirien.
