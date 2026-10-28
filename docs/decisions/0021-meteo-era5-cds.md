# ADR-0021 : Météo ERA5 directe (CDS Copernicus) — deuxième source météo

Date : 2026-10-15. Statut : accepté — **gravé** (migration 0036).

## Contexte

Les grandeurs météo (température, vent, précipitations, humidité, albédo) n'ont
qu'une source préparée, NASA POWER (`meteo_civ`), dont la météo vient de la
réanalyse **MERRA-2**. Comme pour le rayonnement (ADR-0010), une seule source ne
dit rien de sa propre justesse : il en faut une seconde, indépendante dans sa
fabrication.

ERA5 (ECMWF, Copernicus C3S) est la réanalyse de référence. Son accès direct, le
Climate Data Store (CDS), était bloqué tant que les conditions d'utilisation
d'ERA5 n'avaient pas été acceptées sur le compte Copernicus ; c'est chose faite
(2026-10-15), avec la même clé que l'ADS (ADR-0011). Une piste de repli par PVGIS
avait été explorée avant cette ouverture ; elle est abandonnée (voir plus bas).

## Décision

### Source, méthode, contrat

- Source **`ecmwf_era5` (id 2)**, déjà au référentiel (0002, « source de
  cross-check principal »), méthode `reanalyse`, confiance **B** (R4, comme
  ERA5 via PVGIS, ADR-0010). Aucune nouvelle source, grandeur ni valeur
  d'énumération.
- Jeu `reanalysis-era5-single-levels-monthly-means`, produit
  `monthly_averaged_reanalysis`, netCDF sur la grille régulière **0,25°**, boîte
  11° N / 9° O / 4° N / 2° O.
- **Période 1991-2025**, comme NASA POWER (normale 1991-2020 prolongée,
  ADR-0018). 2025 est complète et en **ERA5 définitif** : les 420 mois portent
  `expver = 0001`. L'ingesteur refuse tout mois provisoire (ERA5T, `0005`).

| Grandeur | Variable CDS | Définition (documentation ERA5) | Conversion | Borne |
|---|---|---|---|---:|
| `t2m` | `2m_temperature` | moyenne des heures 00-23 UTC des jours du mois | K − 273,15 → °C | 45 |
| `vent_10m` | `10m_wind_speed` (paramètre 207) | moyenne des **vitesses** horaires | m/s | 20 |
| `precipitation` | `total_precipitation` | cumul du mois entier, ramené à un jour (m d'eau/jour) | × 1000 → mm/jour | 50 |

Les bornes sont celles de NASA POWER mensuel ; la borne basse est 0. La
Côte d'Ivoire est en UTC+0 : le mois UTC est le mois civil local.

### Extraction au point de grille le plus proche

Pas d'interpolation : chaque localité prend la valeur du **nœud 0,25° le plus
proche** (au plus 0,122° de distance sur chaque axe). Un point à égale distance
de deux nœuds serait refusé ; aucun des 142 ne l'est. Les 142 localités tombent
dans **110 mailles** : 82 mailles n'ont qu'une localité, 24 en ont deux, 4 en
ont trois. Deux localités de la même maille portent donc la même série (vérifié
par test). NASA POWER, sur la grille MERRA-2 (½° × ⅝°), n'en distingue que 77.

### Seeds, ingesteur, migration

- CSV gzip `ecmwf_era5_<grandeur>_mensuel_civ142.csv.gz` (ADR-0015), écriture
  déterministe : une régénération depuis le cache redonne les mêmes octets.
- Ingesteur `scripts/ingest_era5_cds_mensuel.py` : une requête par variable
  (1991-2025, boîte CIV), netCDF bruts dans le cache (`--cache`, hors dépôt).
  Garde-fous : unité servie, 420 mois dans l'ordre, `expver`, pas de 0,25°,
  aucune valeur manquante à la maille retenue, relecture par `lire_series`.
- Le CDS limite le nombre de requêtes en file par jeu de données (« Number
  queued requests for this dataset is temporarily limited ») : 2 requêtes
  simultanées au plus et reprise après 60 s. Chaque requête mensuelle prend
  1 à 2 min et pèse 0,2 à 0,6 Mo.
- **Migration 0036** : 426 séries (3 grandeurs × 142 localités) et **178 920
  mesures**, en environ 35 s. Garde-fous : identité de la source, unité de
  chaque grandeur au référentiel cohérente avec la conversion, aucune série
  préexistante sous ces codes, 142 localités exactement, comptes par famille et
  total ; `ANALYZE` en fin de migration. L'aller-retour `downgrade 0033` →
  `upgrade` redonne la même empreinte md5 des séries et des mesures.
- La note publique de chaque série porte l'attribution exigée par la licence :
  « contient des informations modifiées du Copernicus Climate Change Service ».

### Sémantique vérifiée sur l'horaire

Séries horaires ERA5 (jeu `reanalysis-era5-single-levels-timeseries`) aux nœuds
des 3 pilotes, 2016-2025, soit 360 mois comparés aux moyennes mensuelles du CDS
à la même maille :

| Contrôle | Résultat |
|---|---|
| T et Td : moyenne des heures − moyenne mensuelle | ≤ 0,0016 K |
| `10m_wind_speed` − moyenne des vitesses horaires √(u² + v²) | 0,009 à 0,035 m/s en moyenne (max 0,065) |
| `10m_wind_speed` − norme des composantes moyennes | +0,26 à +0,67 m/s en moyenne (max +2,1) |
| `total_precipitation` × 1000 − Σ cumuls horaires / jours | 0,0006 à 0,0015 mm/jour en moyenne |

Le vent mensuel est bien la moyenne des vitesses (le petit écart résiduel vient
du calcul sur la grille native avant interpolation, documenté par l'ECMWF), et
non la vitesse du vent moyen, plus faible.

### Abstentions

**Humidité relative (`rh2m`) — non gravée.** ERA5 ne sert pas d'humidité
relative au sol. La recalculer depuis les moyennes mensuelles de T et de Td
(Magnus, coefficients de `humidex.py`) est biaisée, car la formule n'est pas
linéaire. Mesure du biais par rapport à la moyenne des humidités horaires, aux 3
pilotes sur 2016-2025 (points d'humidité relative) :

| Méthode | Biais moyen | DJF | JJA | Pire mois |
|---|---:|---:|---:|---:|
| M1 : moyennes mensuelles de T et Td | **−1,77** | −3,01 | −0,85 | −6,58 |
| M2 : moyennes par heure du jour, puis moyenne des 24 h | −0,45 | −0,87 | −0,19 | −4,34 |

M1 dépasse le seuil retenu (1 point), surtout en saison sèche et au nord
(Korhogo −2,45 en moyenne, Yamoussoukro −4,18 en DJF) : `rh2m` n'est pas gravée.
M2 (produit « monthly averaged by hour of day ») réduit le biais sans
l'annuler (Korhogo DJF −1,48). Seule la moyenne des humidités horaires est sans
biais par construction ; elle demande les séries horaires de T et Td aux 110
mailles (110 requêtes ponctuelles d'environ 1,5 min). Décision ouverte, tranchée
par l'ADR-0038 : l'humidité ERA5 est gravée par la voie horaire (migration 0057).

**Albédo de surface (`albedo_surface`) — non gravé.** D'après la documentation
ERA5, `forecast_albedo` ne vaut que pour le rayonnement **diffus** à spectre
fixe ; l'albédo réel, toutes conditions de ciel, se calcule par
(SSRD − SSR) / SSRD. Sur la Côte d'Ivoire, `forecast_albedo` est de plus une
climatologie prescrite : son écart-type interannuel pour un même mois est de
l'ordre de 10⁻⁵, contre 0,04 d'amplitude saisonnière. Il ne dit rien de
l'albédo d'une année donnée.

ERA5 ne sert pas de vent à 2 m (seulement à 10 m et 100 m) : `vent_2m` reste
propre à NASA POWER.

### Piste PVGIS abandonnée : la T2m de `MRcalc`

Avant l'ouverture du CDS, la température ERA5 servie par PVGIS (`MRcalc` v5_3,
`avtemp=1`) a été étudiée. Elle n'est **pas gravée** : c'est la même réanalyse
que le CDS, mais en moins fidèle.

- Définition : « monthly average values of daily (24h) temperature », en °C,
  servie au dixième de degré. Elle vient d'ERA5 quelle que soit la base de
  rayonnement (`meteo_db = ERA5`, valeurs identiques avec `PVGIS-SARAH3`).
  Couverture 2005-2023 ; une fin en 2024 est refusée (HTTP 400, « enter an
  integer between 2005 and 2023 »).
- **Le premier et le dernier mois de toute période demandée sont faux.** À
  Abidjan, pour 5 périodes différentes, le premier mois dépasse de 0,9 °C la
  moyenne des heures servies par `seriescalc`, et le dernier mois est inférieur
  de 0,8 à 0,9 °C ; les autres mois concordent au dixième près. Le rayonnement
  `H(h)_m` n'est pas touché (écart ≤ 0,005 % à la somme horaire, mois de bord
  compris) : les séries GHI et DNI déjà gravées (ADR-0010, ADR-0012) sont saines.
- Par rapport au CDS (142 localités, hors mois de bord), la T2m PVGIS est
  inférieure de 0,34 °C en moyenne (de −1,01 à +0,63 °C selon la localité, sans
  lien net avec l'altitude PVGIS, r = +0,19). L'écart dérive de +0,015 °C par an :
  sur 2005-2022, PVGIS montre +0,29 °C par décennie, le CDS +0,14. Pas de marche
  en 2021 (+0,07 °C sur 2021-2023 par rapport à 2016-2020).

## Diagnostic du saut ERA5 de 2021

L'ADR-0018 a relevé un saut du GHI ERA5 servi par PVGIS en 2021 (+3,6 %) et
supposé un changement du produit PVGIS. Le rayonnement descendant ERA5 du CDS
(`surface_solar_radiation_downwards`, J/m² par jour ÷ 3,6·10⁶ → kWh/m²/jour),
téléchargé aux 142 localités **pour ce diagnostic seulement** (non gravé),
tranche :

| GHI, moyenne nationale (kWh/m²/jour) | 2016-2020 | 2021-2023 | Variation | Variabilité interannuelle | Rapport |
|---|---:|---:|---:|---:|---:|
| ERA5 du CDS (`ssrd`) | 4,901 | 5,078 | **+3,6 %** | 1,2 % | 3,0 |
| ERA5 via PVGIS (en base) | 4,889 | 5,065 | **+3,6 %** | 1,2 % | 2,9 |
| CAMS | 5,385 | 5,458 | +1,4 % | 1,3 % | 1,0 |
| SARAH-3 | 5,512 | 5,551 | +0,7 % | 1,3 % | 0,5 |
| NASA POWER | 4,868 | 4,882 | +0,3 % | 1,2 % | 0,2 |

*(Variabilité : coefficient de variation des moyennes annuelles 2005-2020.)*

- **Le saut est dans ERA5 lui-même**, pas dans le traitement PVGIS : le rapport
  PVGIS / CDS reste entre 0,996 et 0,999 chaque année de 2005 à 2023.
- Anomalie ERA5 du CDS par rapport à 2005-2020 : +0,08 (2020), +0,19 (2021),
  +0,17 (2022), +0,19 (2023), +0,19 (2024), +0,08 kWh/m²/jour (2025). Un tel
  niveau n'apparaît avant qu'en 2000, isolément. L'origine (changement des
  observations assimilées ou signal réel que les satellites voient moins) n'est
  pas établie.
- La mise en garde de la migration 0033 reste juste sur le fond ; sa formule
  « saut probable du produit PVGIS-ERA5 » est réécrite en « saut probable de la
  réanalyse ERA5 » par la migration 0043, sur les 994 séries qui la portent
  (précision reportée dans l'ADR-0018).

**Variables gravées : pas de saut analogue.** Même contrôle (variation de la
moyenne nationale rapportée à l'écart-type des moyennes annuelles 2005-2020),
et écart ERA5 − NASA, qui s'écarte si une seule source saute :

| Grandeur | ERA5 2021-2023 | ERA5 2021-2025 | NASA 2021-2023 | NASA 2021-2025 | Écart ERA5 − NASA, 2021-2023 |
|---|---:|---:|---:|---:|---:|
| T2M | +0,06 °C (0,3 σ) | +0,13 °C (0,8 σ) | −0,16 °C (−0,5 σ) | +0,22 °C (0,8 σ) | +0,7 σ |
| Vent à 10 m | +0,8 % (0,4 σ) | +2,1 % (1,1 σ) | −3,3 % (−0,8 σ) | −0,9 % (−0,2 σ) | +0,9 σ |
| Précipitations | −5,7 % (−0,7 σ) | −11,7 % (−1,4 σ) | +13,2 % (1,0 σ) | +2,2 % (0,2 σ) | −1,5 σ |

Aucune variable n'approche les 3 σ du GHI : **les notes publiques ne portent pas
de mise en garde**. Point de vigilance : la pluie ERA5 baisse de 11,7 % sur
2021-2025 quand NASA la voit stable. C'est cohérent en signe avec l'ERA5 plus
ensoleillé de 2021-2024, mais sous le seuil retenu.

## Triangulation ERA5 − NASA POWER (1991-2025, 142 localités)

Calcul hors base, NASA POWER mensuel interrogé aux 142 localités (`T2M`,
`WS10M`, `PRECTOTCORR`, communauté RE, aucune valeur de remplissage). Écarts en
rapport des moyennes de période : en °C pour la température, en % de NASA pour
le vent et la pluie.

| | T2M (°C) | Vent à 10 m | Précipitations |
|---|---:|---:|---:|
| Moyenne nationale ERA5 / NASA | 26,39 / 26,13 | 2,07 / 2,52 m/s | 3,48 / 3,74 mm/jour |
| Écart moyen (médiane) | +0,27 (+0,22) | −14 % (−24 %) | −6,6 % (−10 %) |
| Minimum | −0,49 (Touba) | −45 % (Tiapoum) | −31 % (M'Bahiakro) |
| Maximum | +1,60 (Kouibly) | +101 % (Issia) | +52 % (Grand-Lahou) |
| DJF / MAM / JJA / SON | +0,32 / +0,20 / +0,21 / +0,33 | −15 / −11 / −15 / −15 % | +10 / −12 / −9 / −3 % |
| Sud (< 6,5° N, 43) | +0,03 | −11 % | −1 % |
| Centre (6,5-8,5° N, 68) | +0,45 | −9 % | −16 % |
| Nord (≥ 8,5° N, 31) | +0,19 | −29 % | +6 % |
| Corrélation avec la latitude | +0,18 | −0,32 | +0,10 |
| Corrélation des anomalies mensuelles (médiane) | 0,38 | 0,36 | 0,35 |

**Lecture (constats, pas validation) :**

- **Température** : les deux réanalyses s'accordent en moyenne (+0,27 °C) mais
  pas sur l'évolution. Sur 2005-2022, ERA5 se réchauffe de +0,14 °C par décennie
  et NASA se refroidit de −0,29 ; l'écart passe de −0,09 °C (2005) à +0,92 °C
  (2020). Puis NASA monte de +0,85 °C en 2024-2025 par rapport à 2016-2023
  (3,0 σ), contre +0,21 °C pour ERA5 (1,3 σ) : l'écart retombe à −0,11 °C en
  2025.
  La documentation NASA POWER prévient que sa météo combine MERRA-2 et GEOS-IT
  et déconseille les tendances qui chevauchent un changement de source. Origine
  non établie ; **vigilance pour les séries NASA météo 2024-2025** (lot
  parallèle).
- **Vent** : ERA5 est plus faible que NASA presque partout (médiane −24 %),
  surtout au nord. Les extrêmes tiennent à des mailles particulières : à Issia,
  NASA ne donne que 0,96 m/s ; à Tiapoum, sur le littoral, 3,71 m/s.
- **Pluie** : ERA5 est plus sec au centre (−16 %) et plus humide en saison sèche
  (DJF +10 %) ; les plus grands désaccords sont sur le littoral (Grand-Lahou
  +52 %).
- Mois par mois, les deux réanalyses s'accordent peu à l'échelle d'une localité
  (corrélation médiane des anomalies 0,35 à 0,38). Ni l'une ni l'autre n'est une
  mesure : seules des stations au sol (SODEXAM) diront laquelle est juste.

Le test `test_triangulation_era5_nasa` refait ce contrôle en base dès que les
séries NASA météo y sont : appariement complet sur 1991-2025 et écarts par
localité dans des plages larges autour de ces constats. Il est ignoré tant
qu'elles n'y sont pas.

## Conséquences

- Température, vent à 10 m et précipitations ont une deuxième source aux 142
  localités, sur la même période que NASA POWER.
- ERA5 n'est pas plus une vérité que MERRA-2 : deux réanalyses de modèles et
  d'assimilations différents (ECMWF, NASA GMAO), sans mesure au sol commune.
  Leurs désaccords de tendance interdisent d'en tirer une tendance climatique
  sans précaution.
- Pistes ouvertes, toutes accessibles maintenant que le CDS l'est : humidité
  relative par la voie horaire (gravée depuis, ADR-0038), albédo réel (SSRD − SSR) / SSRD, ERA5-Land
  (`ecmwf_era5_land`, id 12, maille 0,1°) pour réduire le partage de mailles, et
  le rayonnement ERA5 du CDS, qui doublerait le GHI ERA5 via PVGIS (rapport
  0,996 à 0,999).
