# Changelog

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et
le projet suit le versionnement sémantique.

## Non publié

### Ajouté

- Jalon 3 (grandeurs) — **fraction diffuse** NASA POWER (ADR-0014, migration
  0024) : `fraction_diffuse` (id 3, formule de la fiche, version 1) matérialisée
  aux 3 points, 2001-2020, 720 lignes mensuelles et 60 annuelles, confiance B.
  Calculée en base depuis le mensuel NASA (Σ DHI / Σ GHI sur les jours de la
  période) ; équivalence avec le calcul journalier vérifiée à 4·10⁻⁵ près
  (Abidjan 2005). Annuel 0,48 (Korhogo) à 0,55 (Abidjan, Yamoussoukro).
- Jalon 2/3 — **DHI** (ADR-0013) : irradiation diffuse horizontale mensuelle
  **NASA POWER** 2001-2020 (`ALLSKY_SFC_SW_DIFF`, 720 mesures, migration 0021)
  et **CAMS Radiation** 2005-2020 (colonne `DHI` du CSV ADS, 576 mesures,
  migration 0022), confiance B, sources existantes. Premier écart diffus
  `ecart_relatif_dhi_cams_nasa` (0023, NASA au dénominateur, 576 lignes). Les
  ingesteurs NASA et CAMS, étendus au DHI, régénèrent les seeds GHI/DNI gravés
  à l'octet près. Résultat : le DHI concorde bien mieux que le DNI (moyenne des
  ratios mensuels +7,4 % Abidjan, +6,4 % Yamoussoukro, −2,8 % Korhogo, contre
  +31 à +78 % pour le DNI) — le désaccord inter-source porte surtout sur la
  composante directe. PVGIS ne sert que le ratio `Kd` arrondi au centième :
  non ingéré (DHI reconstruit, erreur d'arrondi jusqu'à ~1,3 %). **Correction** :
  le DHI NASA 1991-2000, d'abord gravé, est en rupture avec 2001+ (saut d'un
  tiers entre 2000 et 2001, DHI > GHI sur 10 mois) ; 0021 ne grave plus que
  2001-2020, et un test `DHI ≤ GHI` par source garde la régression.
- Jalon 2/3 — **triangulation DNI à 4 sources** (ADR-0012) : DNI mensuel
  **SARAH-3** et **ERA5** via PVGIS (champ `Hb(n)_m`, option `mr_dni=1` de
  `MRcalc`), 2005-2020 aux 3 points — migrations 0017 et 0018, 576 mesures
  chacune, confiance B, sources existantes `sarah3_monthly` (id 11) et
  `era5_pvgis` (id 16). Deux écarts dérivés, NASA POWER au dénominateur, même
  contrat qu'ADR-0009 (576 lignes chacun) : `ecart_relatif_dni_sarah3_nasa`
  (0019) et `ecart_relatif_dni_era5_nasa` (0020). Les ingesteurs PVGIS sont
  paramétrés par grandeur (GHI + DNI en une requête par point) et régénèrent
  les seeds GHI gravés **à l'octet près**. Résultats (moyenne des ratios
  mensuels gravés) : **NASA POWER est l'aberrant bas du DNI** — SARAH-3 (+67 à
  +96 %) et ERA5 (+88 à +125 %) sont au-dessus de NASA chaque mois, CAMS
  (+31 à +78 %) sauf 3 mois sur 192 à Abidjan ; entre ces trois sources
  l'étalement reste large. Le pic saisonnier dépend de la source (DJF pour
  SARAH-3 à Abidjan et Yamoussoukro, JJA pour CAMS) : la lecture « Harmattan »
  reste une question ouverte. Caveats gravés : ERA5 source de comparaison
  seulement ; SARAH-3 et CAMS partagent l'imagerie Meteosat.
- Jalon 2/3 — **CAMS Radiation** (Heliosat-4, ADS Copernicus) : GHI **et** DNI
  mensuels all-sky 2005-2020 aux 3 points (migration 0014, ADR-0011), 6 séries
  × 192 = **1152 mesures**, confiance B, source existante `cams_radiation`
  (id 13, satellitaire : aucune extension d'énumération). Deux écarts dérivés,
  **NASA POWER au dénominateur** (même contrat qu'ADR-0009, 576 lignes chacun,
  jointure SQL sur la fenêtre commune) : `ecart_relatif_ghi_cams_nasa` (0015),
  4ᵉ point de la triangulation GHI, et `ecart_relatif_dni_cams_nasa` (0016),
  **premier écart DNI** de l'instance. Résultats : GHI CAMS ≈ NASA à Abidjan
  (−0,8 %), proche de SARAH-3 à Yamoussoukro (+13,7 %), ce qui nuance la lecture
  d'ADR-0010 (CAMS et SARAH-3 partagent l'imagerie Meteosat : pas deux votes
  indépendants) ; DNI CAMS **+31,5 à +78,1 %** au-dessus de NASA (moyenne des
  ratios mensuels gravés ; +29 à +75 % en rapport des moyennes), mais avec un
  pic en **mousson (JJA)** et non en Harmattan (DJF) : l'hypothèse « signature du
  Harmattan » n'est pas confirmée. La grandeur héritée `ecart_relatif_dni_cams`
  (id 27, CAMS au dénominateur) n'est pas réemployée. Seeds générés par
  `scripts/ingest_cams_radiation_mensuel.py` (clé `ADS_API_KEY`) ; migrations
  hors-ligne.
- Jalon 3 (grandeurs) — **triangulation inter-source du GHI** : ajout d'une
  **3ᵉ source**, **ERA5** (réanalyse ECMWF, via PVGIS), aux 3 points sur
  2005-2020 (migration 0012, ADR-0010), et d'un **2ᵉ écart dérivé**
  `ecart_relatif_ghi_era5_nasa` (migration 0013), partageant la référence
  NASA POWER avec l'écart SARAH-3. Deux écarts sur le même dénominateur
  **localisent l'aberrant** par point : à Abidjan ERA5 (+7,3 %) et SARAH-3
  (+6,6 %) concordent → NASA est le point bas ; à Yamoussoukro ERA5 (+1,8 %)
  colle à NASA tandis que SARAH-3 (+16,6 %) s'envole → SARAH-3 est l'aberrant.
  ERA5 est une source de **comparaison**, jamais une référence (réanalyse de
  moindre qualité que le satellite en Afrique de l'Ouest, Sawadogo 2023 —
  caveat gravé). Extension honnête de `methode_collecte` avec `reanalyse`
  (ERA5 n'est pas satellitaire) ; nouvelle source `era5_pvgis` traçant le
  canal PVGIS. Ingesteur dédié (`scripts/ingest_pvgis_era5_mensuel.py`).
- Jalon 3 (grandeurs) — **première grandeur dérivée** de l'instance CIV :
  l'**écart inter-source** relatif du GHI, `ecart_relatif_ghi_sarah3_nasa`
  (migration 0011, ADR-0009). Formule `(sarah3 − nasa) / nasa × 100` (NASA
  POWER en référence au dénominateur), matérialisée dans `grandeurs_metier`
  (`strategie_calcul='stockee'`) par (localité, mois) sur la **fenêtre commune
  2005-2020** — 576 lignes (192 mois × 3 points), confiance dérivée **B**.
  Calculée **en base par jointure SQL** depuis les mesures brutes déjà gravées
  (0008 + 0010), sans seed ni réseau : la cohérence avec les séries sources est
  structurelle. Trois choix tranchés dans l'ADR : `stockee` (déterministe,
  hors périmètre — corrige le drift hérité de `ecart_relatif_dni_cams`),
  fenêtre commune stricte (intersection garantie par la jointure), confiance
  `min` des deux entrées B (jamais A).
- Jalon 2 (donnée solaire brute) — irradiation mensuelle **NASA POWER** aux
  départements d'Abidjan, Yamoussoukro et Korhogo, confiance B (satellite),
  unité kWh/m²/jour héritée de la grandeur (contrat de série ADR-0007) :
  - **GHI** 1991-2020, 3 séries × 360 mesures (migration 0008) ;
  - **DNI** 2001-2020, 3 séries × 240 mesures (migration 0009) — NASA POWER ne
    fournit le DNI qu'à partir de 2001 ; chaque série documente sa période.
  Ingesteur reproductible hors-ligne, paramétré par grandeur
  (`scripts/ingest_nasa_power_mensuel.py`) → seed → migration ; garde-fous
  bornes physiques, complétude et anti-remplissage (`-999`).
- Jalon 2 — 2ᵉ source : **GHI mensuel SARAH-3 (PVGIS)** 2005-2020 aux mêmes
  3 points (migration 0010, ADR-0008). 3 séries × 192 mesures, confiance B,
  valeur normalisée (irradiation mensuelle totale PVGIS ÷ jours du mois →
  moyenne journalière kWh/m²/jour). Amorce l'**écart inter-source** : SARAH-3
  est systématiquement plus haut que NASA POWER (+6,6 à +16,6 % selon le point),
  désaccord réel calculable directement en base. Ingesteur dédié
  (`scripts/ingest_pvgis_sarah3_mensuel.py`).
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
