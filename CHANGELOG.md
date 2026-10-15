# Changelog

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et
le projet suit le versionnement sémantique.

## Non publié

### Ajouté

- Jalon 2/3 — **journalier aux 108 départements** (migrations 0046-0049,
  ADR-0031) : avec les pilotes, les 111 départements ont un journalier complet.
  Rayonnement NASA POWER (324 séries, 3 352 968 mesures), météo NASA POWER (648
  séries, 7 889 508 mesures), particules CAMS EAC4 (216 séries, 1 814 616
  mesures), puis variabilité journalière et humidex (52 920 lignes). Les calculs
  journaliers de l'API (POA, correction thermique, degrés-jours, salissure, PR
  réaliste) et les grandeurs dérivées du journalier couvrent tout le territoire.
  **Audit par série** des gravures massives (décision de l'utilisateur) : une
  entrée d'audit par série, avec le CSV et son empreinte SHA-256, au lieu
  d'environ 11 Go d'audit ligne à ligne. La rupture de la pluie NASA vers 2017
  se confirme aux 108 départements (jours > 50 mm ×11,9).

- Jalon 2 — **météo NASA POWER** : température, humidité relative, vent à 2 et
  10 m, précipitations (MERRA-2, 1991-2025) et albédo de surface (CERES,
  2001-2025). **Mensuel aux 142 localités** (migration 0034, ADR-0019 : 852
  séries, 340 800 mesures) et **journalier aux 34 localités** pilotes + régions
  (migration 0035, ADR-0020 : 204 séries, 2 483 734 mesures par `COPY`). Unités
  servies vérifiées contre le référentiel, aucune conversion. Constats :
  humidité très liée à la latitude (r = −0,97), température surtout liée à
  l'altitude du pixel ; MERRA-2 ne distingue que 76 séries sur 111 départements.
  **Pluie NASA aberrante gravée telle quelle, avec mise en garde** : San-Pédro
  726,74 mm le 16/09/2022 (ERA5 : 0,9 mm), septembre 2022 anormal dans l'ouest,
  et jours de pluie > 50 mm passés d'environ 4 par an (1991-2015) à 40-55 par an
  depuis 2017 sans hausse comparable du cumul annuel (cause non établie).
- Jalon 2 — **météo ERA5 du CDS Copernicus** (migration 0036, ADR-0021) :
  température à 2 m, vent à 10 m (moyenne des vitesses) et précipitations,
  1991-2025, aux 142 localités (426 séries, 178 920 mesures), source
  `ecmwf_era5`. Humidité non gravée (recalcul depuis les moyennes mensuelles
  biaisé de −1,8 point) ; albédo ERA5 non pertinent. Triangulation avec NASA :
  ERA5 +0,27 °C, vent −14 %, pluie −6,6 %.
- Jalon 2 — **particules fines PM2.5 et PM10** (CAMS EAC4, migration 0037,
  ADR-0022), entrées du modèle de salissure : mensuel aux 142 localités et
  journalier aux 34 localités, 2003-2025 (352 séries, 649 652 mesures), point
  de grille 0,75° le plus proche (49 mailles pour 142 localités). Harmattan :
  PM2.5 de décembre-février environ 3,9 fois celles de juin-août ; extrêmes
  journaliers PM10 jusqu'à 1 565 µg/m³ (Bafing, 21/02/2016). Incohérence de la
  source en mars 2024 (journalier ≠ mensuel jusqu'à 6 %) signalée, non
  corrigée.
- Jalon 3 — **heures équivalentes pleines et productible spécifique
  théorique** (migration 0038, ADR-0023) aux 142 localités pour les 4 sources de
  GHI, mensuel et annuel (1 136 séries, 347 048 lignes) ; équivalence avec la
  définition journalière héritée démontrée (écart ≤ 5·10⁻³ h_eq). HEP annuel
  moyen de 1 772 (NASA) à 2 001 h_eq (SARAH-3) ; dispersion inter-source
  médiane de 13,5 % par localité.
- Jalon 3 — **variabilité journalière du GHI** (migration 0039, ADR-0024) aux
  34 localités, 1991-2025 (1 190 lignes), et **fraction diffuse CAMS**
  (migration 0040, ADR-0025), deuxième source aux 142 localités, 2005-2025
  (38 766 lignes) : 6,3 % sous NASA en moyenne, nettement plus basse en
  Harmattan au nord.
- Jalon 3 — **indice de clarté `kt`** (migration 0041, ADR-0026) aux 142
  localités pour les 4 sources, mensuel et annuel (568 séries, 173 524 lignes) ;
  `H0` de Duffie & Beckman (Spencer, 1361 W/m²), validé contre `TOA_SW_DWN` de
  NASA (biais −0,01 %). Janvier le plus clair, août le plus couvert partout.
- Jalon 3 — **humidex** (migration 0045, ADR-0030) aux 34 localités du
  journalier, mensuel et annuel 1991-2025 (34 séries, 15 470 lignes),
  définition héritée inchangée (Masterton & Richardson, moyenne des humidex
  journaliers). Moyenne nationale 34,5 °C apparents (1991-2020), du Tonkpi
  (32,1) à la côte (jusqu'à 36,6) ; écart nord-sud de 9 °C en Harmattan, effacé
  en mousson ; aucun jour ≥ 45. La hausse 2024-2025 suit celle de la T2M NASA,
  que ERA5 ne confirme pas : pas de conclusion de réchauffement.
- Jalon 3 — **dégénérescence de pixel matérialisée** (migration 0042, ADR-0027) :
  une ligne par série mensuelle brute (familles détectées en base) ; NASA ne
  distingue que 35 séries sur 142 localités, les groupes coïncident exactement
  avec les cellules de 1°. La grandeur passe en `stockee`.
- Jalon 3 — **grandeurs métier exposées par l'API sur les données nationales**
  (ADR-0028) : POA, productibles, P50/P90 (`ghi_exceedance`, série couvrant la
  normale 1991-2020, années complètes) aux 142 localités, incertitude
  inter-source ; compagnes cherchées par granularité et recouvrement de période ;
  erreurs explicites quand une donnée manque.
- **API des données nationales** (ADR-0029) : résolution au point sur des séries
  couvrant la normale (404 partout auparavant), recherche de localités `?q=`,
  filtre `granularite`, pagination des mesures (`pagination_mesures`, en-tête
  `X-Kuma-Mesures-Total`, auparavant 1 000 jours renvoyés sans le signaler) ;
  index de lecture des séries dérivées (migration 0044).

### Modifié

- **API : paramètres contradictoires en 422** (`periode_fin < periode_debut`,
  plage horaire de plus de 366 jours, correction thermique sans NOCT), qui
  répondaient 500 ; seules les erreurs des modèles de paramètres sont
  converties. Documentation de l'API et fiches de grandeurs réécrites pour un
  moteur générique avec des exemples ivoiriens.
- **Mise en garde ERA5 précisée** (migration 0043, ADR-0018, ADR-0021) : le saut
  de 2021 vient de la réanalyse ERA5 elle-même (rayonnement ERA5 du CDS +3,6 %,
  rapport PVGIS / CDS stable entre 0,996 et 0,999), pas du traitement PVGIS. La
  phrase est réécrite sur les 994 séries qui la portent (ERA5 brutes, écarts,
  HEP, productible et `kt` dérivés d'ERA5).

### Ajouté (avant le 2026-10-15)

- **Mise en garde ERA5 dans les données** (migration 0033, ADR-0018) : le saut
  probable du produit PVGIS-ERA5 en 2021 est signalé dans la note publique des
  568 séries ERA5 (brutes GHI et DNI, écarts ERA5 − NASA, 142 localités).
  Métadonnées seulement.
- Jalon 2/3 — **extension temporelle 2021-2025** (ADR-0018, migrations
  0030-0032) : les séries déjà gravées sont prolongées sous les mêmes codes,
  jusqu'à la dernière année servie par chaque source — NASA POWER et CAMS 2025,
  SARAH-3 et ERA5 2023 (limite PVGIS). 71 568 mesures mensuelles (142
  localités), 186 252 journalières NASA (34 localités), et 55 238 lignes de
  grandeurs dérivées (écarts jusqu'à la dernière année commune avec NASA,
  fraction diffuse jusqu'en 2025). Valeurs 1991-2020 et normale climatologique
  inchangées. Contrôle de continuité 2020/2021 : NASA, CAMS et SARAH-3
  continus ; **ERA5 saute** (GHI +3,6 %, DNI +7,7 %, environ trois fois sa
  variabilité interannuelle), probablement un changement du produit servi par
  PVGIS — gravé tel quel, avec caveat. Option `--extension` des ingesteurs.
- Jalon 3 — **grandeurs dérivées sur tout le territoire** (ADR-0017) : les 7
  écarts inter-sources (migration 0028, 186 816 lignes) et la fraction diffuse
  NASA (migration 0029, 36 140 lignes) étendus aux 139 localités des lots ;
  chaque grandeur couvre désormais 142 localités. Constats : l'écart DNI moyen
  est positif dans les 142 localités pour les 3 sources comparées (NASA aberrant
  bas du DNI à l'échelle nationale) ; les désaccords se creusent vers la côte ;
  la fraction diffuse va de 0,44 (Minignan) à 0,56 (La Mé).

### Modifié

- **Tests ~10 fois plus rapides** (~4 min 40 → ~26 s), sans perte de
  couverture : `ANALYZE` après les insertions massives (0028-0029) et tests de
  cohérence DHI ≤ GHI réécrits sans auto-jointure. La cause mesurée était un
  plan de requête dégénéré faute de statistiques, pas la comparaison intégrale.
- **Fraction diffuse annuelle reproductible au bit près** (0024, 0029) : sommes
  en `numeric`, indépendantes de l'ordre d'agrégation (écart antérieur de
  3·10⁻¹⁶ selon l'exécution).
- Jalon 2 — **couverture nationale, lot départements** (ADR-0015, migration
  0027) : les 108 départements non pilotes aux 4 sources, 1080 séries,
  235 872 mesures ; avec les 3 pilotes, les 111 départements sont couverts
  (310 128 mesures mensuelles en base). NASA POWER n'y distingue que 35 valeurs
  (maille d'environ 1°) ; SARAH-3 et CAMS varient réellement d'un département à
  l'autre. Test des lots généralisé (`test_lots_nationaux_seed.py`).
- Jalon 2 — **NASA POWER journalier** (ADR-0016, migration 0026) : GHI
  1991-2020, DNI et DHI 2001-2020 aux 3 points pilotes et 31 régions, 102
  séries, 869 312 mesures dans `mesures_ressource`, insérées par `COPY`.
  Seeds CSV gzip (complétude de tous les jours civils), ingesteur
  `scripts/ingest_nasa_power_journalier.py`. Aucun jour DHI > GHI ; la moyenne
  des jours de chaque mois redonne le mensuel NASA à 0,00017 près.
- Jalon 2 — **couverture nationale, lot régions** (ADR-0015, migration 0025) :
  les 31 régions aux 4 sources (NASA POWER GHI/DNI/DHI, SARAH-3 et ERA5
  GHI/DNI, CAMS GHI/DNI/DHI), aux contrats des séries pilotes : 310 séries,
  67 704 mesures, confiance B. Nouveaux seeds **CSV gzip** (écriture
  déterministe, relecture validée) et option `--lot` des 4 ingesteurs. Constat :
  NASA POWER ne donne que 22 séries distinctes sur 31 régions (maille solaire
  d'environ 1°) ; gradient sud → nord du GHI et du DNI dans toutes les sources.
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
