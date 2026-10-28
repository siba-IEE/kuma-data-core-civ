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

- [x] Séries et mesures brutes par source (NASA POWER, SARAH-3 et ERA5 via
      PVGIS, CAMS) sur tout le pays (111 départements, 31 régions), en
      confiance B.
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
  - [x] DHI mensuel NASA POWER 2001-2020 (rupture NASA avant 2001) et CAMS
        2005-2020, mêmes 3 points (migrations 0021-0022, ADR-0013). PVGIS ne
        sert que le ratio `Kd` arrondi : non ingéré (DHI reconstruit, pas natif).
  - [x] **Lot régions** : les 31 régions, 4 sources × GHI/DNI/DHI aux contrats
        pilotes, 310 séries, 67 704 mesures (migration 0025, ADR-0015) — seeds
        en CSV gzip déterministes.
  - [x] **Lot départements** : 108 départements hors pilotes, 4 sources,
        1080 séries, 235 872 mesures (migration 0027, ADR-0015) — avec les
        pilotes, les 111 départements sont couverts.
  - [x] **Extension 2021-2025** des séries déjà gravées : NASA et CAMS
        jusqu'en 2025, SARAH-3 et ERA5 jusqu'en 2023 (dernière année PVGIS),
        journalier NASA jusqu'au 31/12/2025, écarts et fraction diffuse
        prolongés (migrations 0030-0032, ADR-0018) — couvre la fenêtre des
        mesures sol ESMAP (2022-2024).
  - [x] **Lot journalier** NASA POWER : GHI 1991-2020, DNI et DHI 2001-2020
        aux 3 pilotes + 31 régions, 869 312 mesures (migration 0026,
        ADR-0016) ; cohérent avec le mensuel à l'arrondi près.
- [x] **Météo** (grandeurs du référentiel `t2m`, `rh2m`, `vent_2m`,
      `vent_10m`, `precipitation`, `albedo_surface`) :
  - [x] NASA POWER **mensuel aux 142 localités** (MERRA-2 1991-2025, albédo
        CERES 2001-2025), 852 séries, 340 800 mesures (migration 0034,
        [ADR-0019](decisions/0019-meteo-nasa-power-mensuelle.md)).
  - [x] NASA POWER **journalier aux 34 localités** (pilotes + régions), 204
        séries, 2 483 734 mesures (migration 0035,
        [ADR-0020](decisions/0020-meteo-nasa-power-journaliere.md)) — entrées
        de la correction thermique, des degrés-jours, de l'humidex, de la
        salissure et du POA bifacial. Pluie NASA aberrante gravée avec mise en
        garde (septembre 2022, hausse des fortes pluies depuis 2017).
  - [x] **ERA5 du CDS** (2ᵉ source) : température, vent à 10 m, pluie,
        1991-2025, 142 localités (migration 0036,
        [ADR-0021](decisions/0021-meteo-era5-cds.md)) ; humidité ERA5 non
        gravée (biais du recalcul mensuel).
- [x] **Particules fines PM2.5 et PM10** (CAMS EAC4, 2003-2025) : mensuel aux
      142 localités, journalier aux 34 localités (migration 0037,
      [ADR-0022](decisions/0022-particules-cams-eac4.md)) — entrées du proxy
      de salissure et du PR réaliste.
- [x] **Pluie journalière ERA5** (CDS) aux 142 localités et **recoupement de la
      pluie NASA** (migrations 0050-0051,
      [ADR-0032](decisions/0032-pluie-nasa-recoupement-era5.md)) : jours extrêmes
      et rupture de 2016-2017 propres à NASA (recalage pentadaire sur CMAP
      temps réel) ; pluie journalière NASA à ne pas utiliser pour les épisodes.
  - [x] Pluie journalière **GPM IMERG** (via NASA POWER) aux 142 localités,
        source de la salissure et du PR réaliste (migration 0052,
        [ADR-0033](decisions/0033-pluie-imerg-salissure.md)).
- [x] **Température et vent journaliers ERA5** (CDS) aux 142 localités,
      1991-2025 (migration 0053,
      [ADR-0034](decisions/0034-meteo-era5-journaliere.md)) : deuxième source
      journalière de la météo ; vent recalculé depuis les composantes, un peu
      sous le mensuel ERA5 (écart publié).
- [x] **Rayonnement journalier CAMS** (GHI, DNI, DHI) aux 142 localités,
      2005-2025 (migration 0054,
      [ADR-0035](decisions/0035-rayonnement-cams-journalier.md)) : 126 séries
      distinctes (35 pour NASA) ; lacunes CAMS explicites, jamais bouchées ;
      révision CAMS de 2021-2025 constatée sur le mensuel gravé.
  - [x] Révision 2021-2025 du mensuel CAMS gravée par versionnement
        temporel (migration 0056,
        [ADR-0037](decisions/0037-revision-cams-mensuel.md)) : valeurs
        remplacées closes, jamais supprimées ; grandeurs dérivées CAMS
        recalculées et versionnées de même.
- [x] **Pluie journalière CHIRPS v3.0** aux 142 localités, 1991-2025
      (migration 0055, [ADR-0036](decisions/0036-pluie-chirps-journaliere.md)) :
      quatrième source de pluie journalière, nouvelle source `chirps` ; le
      journalier répartit les cumuls pentadaires selon ERA5, à utiliser en
      cumuls de pentade ou de mois.
- [ ] Chaîne d'ingestion reproductible.
  - [x] Ingesteur NASA POWER mensuel (`scripts/ingest_nasa_power_mensuel.py`,
        paramétré par grandeur GHI/DNI/DHI, hors-ligne → seed → migration ;
        garde-fous bornes/complétude/anti-remplissage).
  - [x] Ingesteurs PVGIS SARAH-3 et ERA5 (GHI + DNI en une requête) et CAMS
        (GHI + DNI + DHI, clé ADS) ; chaque extension régénère les seeds déjà
        gravés à l'octet près.

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
- [x] **Premier écart DHI** : CAMS vs NASA POWER (`ecart_relatif_dhi_cams_nasa`,
      migration 0023) — le diffus concorde à ±8 % en moyenne, le désaccord
      inter-source porte surtout sur le direct —
      [ADR-0013](decisions/0013-dhi-nasa-cams.md).
- [x] **Fraction diffuse** NASA POWER, mensuelle et annuelle 2001-2020
      (`fraction_diffuse`, migration 0024) — première grandeur métier hors
      écart, calculée en base depuis le mensuel —
      [ADR-0014](decisions/0014-fraction-diffuse-nasa.md).
- [x] **Grandeurs dérivées sur tout le territoire** : les 7 écarts
      inter-sources et la fraction diffuse étendus aux 142 localités
      (migrations 0028-0029, [ADR-0017](decisions/0017-grandeurs-derivees-lots-nationaux.md)) ;
      NASA ressort aberrant bas du DNI dans 142 localités sur 142.
- [x] **Heures équivalentes pleines et productible spécifique théorique**
      aux 142 localités, 4 sources (migration 0038,
      [ADR-0023](decisions/0023-hep-productible-theorique.md)).
- [x] **Variabilité journalière** du GHI (34 localités, migration 0039,
      [ADR-0024](decisions/0024-variabilite-journaliere-ghi-nasa.md)) et
      **fraction diffuse CAMS** (142 localités, migration 0040,
      [ADR-0025](decisions/0025-fraction-diffuse-cams.md)).
- [x] **Indice de clarté `kt`** aux 142 localités, 4 sources (migration 0041,
      [ADR-0026](decisions/0026-indice-de-clarte-kt.md)).
- [x] **Dégénérescence de pixel** matérialisée (migration 0042,
      [ADR-0027](decisions/0027-degenerescence-pixel.md)) : NASA ne distingue
      que 35 séries sur 142 localités.
- [x] **Mise en garde ERA5 précisée** : le saut de 2021 vient de la réanalyse
      elle-même (migration 0043, ADR-0021).
- [ ] Grandeurs métier calculées (POA, productible, P50/P90, salissure, PR
      réaliste) exposées par l'API.
  - [x] POA, productibles, P50/P90 et incertitude inter-source servis sur les
        données nationales ([ADR-0028](decisions/0028-grandeurs-api-series-prolongees.md)) ;
        API des séries et localités (résolution, recherche, pagination,
        [ADR-0029](decisions/0029-exposition-api-donnees-nationales.md)).
  - [x] Correction thermique, degrés-jours, énergie ECS, POA bifacial,
        salissure et PR réaliste vérifiés par l'API sur la météo journalière et
        les particules (34 localités).
  - [x] **Humidex** stocké aux 34 localités (migration 0045,
        [ADR-0030](decisions/0030-humidex-nasa.md)).
  - [x] **Journalier aux 108 départements** (rayonnement, météo, particules,
        variabilité, humidex ; migrations 0046-0049,
        [ADR-0031](decisions/0031-journalier-departements-audit-par-serie.md)) :
        POA, productibles thermiques, salissure et PR réaliste calculables aux
        111 départements ; audit par série des gravures massives.
- [ ] Contrôle qualité horaire.

## Jalon 4 : terrain (confiance A)

- [ ] Intégrer des stations sol ouvertes en Côte d'Ivoire comme première ancre de
      confiance A, et le calage terrain associé.

## Documentation

- [ ] Adapter `docs/` au contexte ivoirien.
  - [x] Référence de l'API, démarrage rapide et fiches de grandeurs (HEP,
        productible, variabilité, fraction diffuse) : moteur générique,
        exemples ivoiriens vérifiés.
