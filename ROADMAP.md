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
  - [x] GHI mensuel ERA5 (réanalyse, via PVGIS), 2005-2020, mêmes 3 points
        (migration 0012, ADR-0010) — 3ᵉ source, classe de méthode indépendante
        (réanalyse) pour la triangulation inter-source.
  - [x] GHI **et** DNI mensuels CAMS Radiation (Heliosat-4, ADS Copernicus),
        2005-2020, mêmes 3 points (migration 0014, ADR-0011) — 4ᵉ source GHI
        et **2ᵉ source DNI** ; source existante `cams_radiation` (id 13).
  - [x] DNI mensuel SARAH-3 et ERA5 (PVGIS, `Hb(n)_m` via `mr_dni=1`),
        2005-2020, mêmes 3 points (migrations 0017-0018, ADR-0012) — DNI à
        4 sources ; sources existantes, ingesteurs PVGIS paramétrés GHI + DNI.
  - [ ] DHI, autres points.
- [ ] Chaîne d'ingestion reproductible.
  - [x] Ingesteur NASA POWER mensuel (`scripts/ingest_nasa_power_mensuel.py`,
        paramétré par grandeur, hors-ligne → seed → migration ; garde-fous
        bornes/complétude/anti-remplissage).

## Jalon 3 : grandeurs et qualité

- [x] **Première grandeur dérivée** : écart inter-source relatif du GHI
      SARAH-3 vs NASA POWER (`ecart_relatif_ghi_sarah3_nasa`, `stockee`),
      matérialisé dans `grandeurs_metier` sur la fenêtre commune 2005-2020
      (576 lignes, confiance B) — migration 0011, [ADR-0009](decisions/0009-grandeur-derivee-ecart-inter-source-ghi.md).
- [x] **Triangulation inter-source GHI** : 2ᵉ écart dérivé ERA5 vs NASA POWER
      (`ecart_relatif_ghi_era5_nasa`), même référence commune que l'écart
      SARAH-3 → localisation de l'aberrant par (localité, mois) — migration
      0013, [ADR-0010](decisions/0010-triangulation-ghi-era5-troisieme-source.md).
- [x] **Triangulation GHI à 4 sources** : 3ᵉ écart CAMS vs NASA POWER
      (`ecart_relatif_ghi_cams_nasa`, migration 0015), et **premier écart DNI**
      (`ecart_relatif_dni_cams_nasa`, migration 0016, CAMS +31 à +78 % au-dessus
      de NASA en moyenne des ratios mensuels gravés, pic en mousson plutôt
      qu'en Harmattan). Même référence NASA POWER pour tous les écarts —
      [ADR-0011](decisions/0011-cams-radiation-ghi-dni-quatrieme-source.md).
- [x] **Triangulation DNI à 4 sources** : écarts SARAH-3 et ERA5 vs NASA POWER
      (`ecart_relatif_dni_sarah3_nasa`, `ecart_relatif_dni_era5_nasa`,
      migrations 0019-0020). NASA POWER ressort comme l'aberrant bas du DNI ;
      le motif saisonnier (Harmattan vs mousson) dépend de la source —
      [ADR-0012](decisions/0012-triangulation-dni-pvgis-sarah3-era5.md).
- [ ] Grandeurs métier calculées (POA, productible, P50/P90, salissure, PR
      réaliste) exposées par l'API.
- [ ] Contrôle qualité horaire.

## Jalon 4 : terrain (confiance A)

- [ ] Intégrer des stations sol ouvertes en Côte d'Ivoire comme première ancre de
      confiance A, et le calage terrain associé.

## Documentation

- [ ] Adapter `docs/` au contexte ivoirien.
