# ADR-0022 : Particules fines PM2.5 et PM10 — CAMS EAC4

Date : 2026-10-15. Statut : accepté — **gravé** (migration 0037).

## Contexte

Le proxy de salissure (`taux_salissure_proxy`, modèle HSU de `pvlib`) et le PR
réaliste de l'API consomment des **PM2.5 et PM10 journalières** de la source
`cams_eac4`, avec la pluie journalière NASA POWER. La source (id 15) et les
grandeurs `pm2_5` / `pm10` (unité `microgramme_par_metre_cube`, µg/m³) existent
au référentiel depuis 0002, mais **aucune série** n'était gravée : aucun calcul
de salissure ne pouvait aboutir en Côte d'Ivoire.

EAC4 (ECMWF Atmospheric Composition Reanalysis 4, Inness et al. 2019) est servie
par l'ADS Copernicus, avec la clé `ADS_API_KEY` déjà utilisée pour CAMS
Radiation (ADR-0011). Sondage du 2026-10-15 :

| Jeu ADS | Pas | Servi | Grille |
|---|---|---|---|
| `cams-global-reanalysis-eac4-monthly` (`monthly_mean`) | mois | 2003-01 → 2025-12 | 0,75° |
| `cams-global-reanalysis-eac4` | 3 h (00, 03, …, 21 UTC) | 2003-01-01 → 2025-12-31 | 0,75° |

**Dernière année complète servie : 2025** (les deux jeux, vérifié sur le
catalogue et par téléchargement du 31/12/2025).

## Décision

### Contrats (`seeds/aerosols_civ.py`)

| Famille | Préfixe | Localités | Lot (CSV) | Table |
|---|---|---:|---|---|
| PM2.5 / PM10 mensuels | `cams_eac4_<g>_mensuel` | 142 (`points_nationaux`) | `civ142` | `mesures_ressource_mensuelles` |
| PM2.5 / PM10 journaliers | `cams_eac4_<g>_journalier` | 34 (`points_journalier`) | `pilotes_regions` | `mesures_ressource` |

Source `cams_eac4` (id 15), méthode **`reanalyse`**, confiance **B**, période
**2003-2025** (tout EAC4). Le journalier est limité aux 34 localités (3 pilotes +
31 régions) où le rayonnement et la météo NASA journaliers existent : c'est là
que le HSU trouve sa pluie. Bornes de sanité (rejet à la lecture du CSV) :
PM2.5 ≤ 1000 µg/m³ au mois et ≤ 3000 au jour, PM10 ≤ 2000 et ≤ 6000 — larges
exprès, les épisodes de saison sèche (Harmattan) pouvant porter les PM10 au-delà
de 1000 µg/m³. Borne basse 0 (voir « Valeurs nulles »).

### Extraction (`scripts/ingest_cams_eac4_pm.py`)

- **Requêtes** sur la boîte englobante des 142 localités calée sur la grille
  (`[N 10,5 ; O −9,0 ; S 3,75 ; E −2,25]`, 10 × 10 points) : une requête pour le
  mensuel, **une par année** pour le 3-horaire (23 requêtes, `netcdf_zip`).
  Chaque archive est téléchargée dans son propre sous-dossier du cache
  (`--cache`) et réutilisée si elle est valide. L'ADS rejette une requête quand
  trop sont en file pour un même jeu (« Number queued requests for this dataset
  is temporarily limited ») : le script retente avec une attente croissante.
- **Conversion** kg/m³ → µg/m³ (× 1e9), sans autre transformation.
- **Point de grille le plus proche**, axe par axe (grille régulière) ; une
  égalité exacte arrêterait l'ingestion (aucune rencontrée). La boîte contient,
  pour chaque localité, les deux lignes de grille qui l'encadrent.
- **Moyenne journalière** = moyenne arithmétique des **8 analyses** 00-21 UTC du
  jour civil UTC (la Côte d'Ivoire est en UTC+0). Un jour incomplet ou une
  valeur manquante arrêterait l'ingestion : rien n'est comblé (aucun cas).
- CSV gzip déterministes (ADR-0015), 4 décimales.

**Maille partagée.** La grille de 0,75° (≈ 83 km) est grossière à l'échelle des
départements : les **142 localités** ne tombent que sur **49 mailles** (128
localités partagent leur maille avec au moins une autre, jusqu'à 7 par maille) ;
les **34 localités** journalières sur **26 mailles** (15 localités partagent
leur maille, 7 mailles concernées). Ces séries identiques sont gravées telles
quelles, par localité (même constat que NASA POWER, ADR-0015) ; la note publique
de chaque série le dit.

### Migration 0037

**352 séries** et **649 652 mesures** : 78 384 mensuelles (2 × 142 × 276 mois)
et 571 268 journalières (2 × 34 × 8401 jours, par `COPY`). Garde-fous : identité
de la source, unité `microgramme_par_metre_cube` des deux grandeurs, **aucune
série PM `cams_eac4` préexistante**, localités, couverture exacte de chaque CSV,
comptes par famille et total ; `ANALYZE` en fin de migration ; `downgrade`
symétrique (mesures puis séries).

### Compatibilité API (vérifiée, API non modifiée)

- **PR réaliste** : `_chercher_serie_pm_cams` retient la première série
  `cams_eac4` **journalière** active de la localité, par grandeur. Aux 34
  localités, il trouve exactement les séries gravées ; ailleurs, rien (le
  mensuel, de granularité différente, n'est jamais pris).
- **Proxy de salissure** : depuis le code de la série PM2.5 journalière,
  `_chercher_serie_compagne` trouve la PM10 compagne (même source, même début
  2003-01-01, même granularité) ; la lecture donne un index journalier contigu
  2003-01-01 → 2025-12-31, ce qu'exige le HSU.
- La pluie journalière NASA (`precipitation`, contrats de `meteo_civ.py`) est
  gravée par un lot distinct : tant qu'elle manque, les deux endpoints
  répondent 400 « compagne absente », comme prévu. Le test d'intégration
  appelle les résolveurs réels de l'API.

## Vérifications

| Contrôle | Résultat |
|---|---|
| Mensuel servi vs moyenne des analyses 3-horaires du mois (100 points de la boîte, 276 mois) | ≤ 0,0004 µg/m³ (≤ 0,004 %) sur 275 mois ; **mars 2024 : jusqu'à 3,7 µg/m³ (6,0 %)** |
| Moyenne des jours gravés vs mensuel gravé (34 localités × 276 mois, test) | ≤ 0,00033 µg/m³ hors mars 2024 ; mars 2024 : jusqu'à 1,9 (PM2.5) et 2,3 µg/m³ (PM10), < 6 %, aux 34 localités |
| Valeurs manquantes servies ; jours avec moins de 8 analyses | aucune ; aucun |
| PM2.5 > PM10 aux mailles des localités (3-horaire, jour, mois) | aucun |
| PM2.5 > PM10 sur toute la boîte (3-horaire) | 1 analyse (2004-07-23 15 UTC, 5,25° N 6,75° O : PM10 = 0, PM2.5 = 0,0002 µg/m³), hors maille de localité |
| Fidélité base ↔ CSV | intégrale (test) |
| Régénération des CSV depuis le cache | identique à l'octet |
| Aller-retour 0037 → 0033 → 0037 | empreintes de contenu identiques |

### Valeurs nulles servies par EAC4

L'EAC4 sert des concentrations **exactement nulles**, PM2.5 et PM10 ensemble,
**uniquement à 12, 15, 18 et 21 UTC** (jamais de 00 à 09 UTC), dispersées dans
l'année et sur toute la boîte. Ce ne sont pas des valeurs manquantes : le GRIB
natif (sans bitmap, 24 bits) porte bien 0 — vérifié sur Korhogo le 2005-01-16
(64,84 µg/m³ à 09 UTC, **0** à 12 UTC, 2,33 à 15 UTC). Cause non
établie ; ces zéros **ne sont ni retirés ni remplacés** : **3344 analyses nulles**
aux 26 mailles des 34 localités, soit **0,19 %** des analyses (75 % à 12 UTC, au
plus 4 par jour, de 73 par an en 2004 à 248 en 2018). Ils abaissent la moyenne
des jours concernés ; aucune moyenne journalière ni mensuelle n'est nulle (minimum
journalier 0,67 µg/m³ en PM2.5).

### Mars 2024 : mensuel et 3-horaire incohérents à la source

Sur 276 mois, le produit `monthly_mean` est la moyenne des analyses 3-horaires
servies à 0,0004 µg/m³ près, **sauf en mars 2024** : jusqu'à 3,7 µg/m³ d'écart
(6,0 %) sur la boîte, 0,6 à 0,7 µg/m³ en moyenne aux 34 localités. Aucune exclusion
simple (un jour, une heure UTC, une fin de mois tronquée) ne l'explique, et rien
ne dit lequel des deux produits est juste. **Les deux sont gravés tels que
servis** ; la note publique de chaque série le signale, et le test de cohérence
borne l'écart de ce seul mois (< 6 %) au lieu de le masquer : il échouera si la
source est corrigée.

## Résultats (2003-2025)

### Saisonnalité : un pic de saison sèche

Moyenne nationale (142 localités) des mesures mensuelles, µg/m³ :

| | Jan | Fév | Mar | Avr | Mai | Juin | Juil | Août | Sep | Oct | Nov | Déc |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| PM2.5 | 69,7 | 59,2 | 44,2 | 30,8 | 21,0 | 17,9 | 15,4 | 12,9 | 13,2 | 17,3 | 25,4 | 53,3 |
| PM10 | 89,5 | 75,1 | 56,1 | 40,0 | 28,5 | 24,8 | 21,7 | 18,4 | 18,6 | 23,7 | 33,8 | 70,1 |

- **DJF (Harmattan) ≈ 3,6 à 3,9 × JJA (mousson)** : PM2.5 60,7 contre
  15,4 µg/m³ (× 3,9), PM10 78,2 contre 21,6 (× 3,6). Le rapport DJF/JJA va de
  2,5 à 8,1 selon la localité (PM2.5). Janvier est le mois le plus chargé, août
  le moins.
- Moyenne 2003-2025 : PM2.5 **31,7**, PM10 **41,7** µg/m³.

### Gradient nord-sud : modéré en saison sèche, inversé en mousson

| Grandeur | Min (localité) | Max (localité) | Corrélation avec la latitude (moyenne / DJF / JJA) |
|---|---|---|---:|
| PM2.5 | 17,9 (San-Pédro) | 42,7 (Bafing) | 0,52 / 0,49 / −0,36 |
| PM10 | 23,5 (San-Pédro) | 56,7 (Bafing) | 0,46 / 0,48 / −0,42 |

En DJF, la charge croît vers le nord (Tabou 31,2 → Bafing 101,1 µg/m³ en
PM2.5) ; en JJA, le maximum est sur la côte (Abidjan 22,6), le minimum à Tabou
(11,4). Le maximum annuel est à **l'ouest (Bafing, 8,5° N)**, pas à l'extrême
nord : le gradient n'est pas monotone.

### Épisodes extrêmes (journalier, 34 localités)

| | PM2.5 | PM10 |
|---|---:|---:|
| Maximum journalier | **1140,1** (Bafing, 2016-02-21) | **1565,1** (Bafing, 2016-02-21) |
| Maximum 3-horaire | 2363,8 (Bafing, 2016-02-21 03 UTC) | 3252,7 (idem) |
| Jours-localités > 500 / > 1000 µg/m³ | 80 / 2 | 238 / 17 |
| 99ᵉ centile journalier | 191,2 | 239,5 |
| Journée la plus chargée (moyenne des 34 localités) | 284,2 (2005-01-14) | 339,7 (2004-02-06) |
| Jours au-dessus de la ligne directrice OMS 2021 sur 24 h (15 / 45 µg/m³) | 71,8 % | 24,8 % |

Les maxima ponctuels sont localisés (Bafing, Bounkani et Gbêkê occupent les dix
premières places) ; les journées les plus chargées à l'échelle du pays tombent
toutes de décembre à avril (jours au-delà du 99ᵉ centile national en PM10 : 41
en janvier, 24 en février, 10 en mars, 2 en avril, 7 en décembre). Les bornes de
sanité (3000 / 6000 µg/m³ au jour) gardent une marge d'un facteur 2,6 à 3,8 sur
les maxima observés.

### Tendances

Moyenne nationale annuelle (mensuel, 142 localités), pente des moindres carrés
2003-2025 :

| Grandeur | Pente annuelle | Pente DJF (hivers 2003/04 → 2024/25) | Pente JJA | Localités en baisse |
|---|---:|---:|---:|---:|
| PM2.5 | −2,2 µg/m³/décennie | −8,2 | +0,6 | 98 / 142 |
| PM10 | −3,0 µg/m³/décennie | −11,7 | +0,9 | 99 / 142 |

Une baisse de la saison sèche, mais à lire avec prudence : la variabilité
interannuelle est forte (moyennes annuelles de 26,0 à 38,5 µg/m³ en PM2.5), la
série ne compte que 23 ans, et une réanalyse peut porter des ruptures liées aux
observations assimilées. **Aucun test de significativité ni attribution** ici.

### Lecture (constats, pas validation)

- **PM2.5 / PM10 ≈ 0,73** (médiane journalière ; de 0,57 à 0,92) : la fraction
  fine domine, ce qui s'accorde mal avec une poussière minérale seule, dont la
  masse est surtout grossière. Les feux de savane de la saison sèche,
  contemporains de l'Harmattan, sont une explication plausible ; EAC4 sert la
  composition par espèce, que ce lot n'ingère pas. **Non tranché.**
- Ce sont des concentrations de **réanalyse**, sur une maille de 83 km, sans
  mesure sol dans l'instance pour les ancrer : confiance B, ordre de grandeur et
  saisonnalité plutôt que valeur locale exacte.

## Coût opérationnel

Ingestion ADS : environ 50 min pour les 24 requêtes (≈ 5 à 8 min de file par
année 3-horaire, deux à cinq en parallèle), 35 Mo d'archives en cache. CSV
committés : 4,3 Mo (0,5 Mo mensuel, 3,8 Mo journalier). Migration 0037 : environ
1 min 30, trigger d'audit compris ; tests du lot : environ 15 s.

## Conséquences

- Le proxy de salissure et la correction salissure du PR réaliste deviennent
  calculables aux 34 localités dès que la pluie NASA journalière est gravée.
- Les métadonnées de la source `cams_eac4` (0002, héritées du moteur générique)
  annoncent encore une couverture « 2021-01-01 à 2025-08-31 » ; elles ne sont pas
  modifiées par ce lot (point ouvert).
- Étendre le journalier aux 108 départements ne demanderait aucun
  téléchargement de plus (même boîte), au prix d'environ 1,8 M lignes, dont
  beaucoup en double (49 mailles pour 142 localités).

## Précisions (2026-10-15, ADR-0031)

Le lot journalier des 108 départements (migration 0048) a relu les mêmes
archives 3-horaires sur toutes les mailles des localités :

- l'unique analyse où PM2.5 > PM10 (2004-07-23, 15 UTC) tombe dans la maille de
  Méagui et San-Pédro : elle est donc hors maille des 34 localités de ce lot,
  mais pas hors maille de localité ;
- EAC4 sert aussi quelques analyses nulles avant 12 UTC (3 sur les 48 mailles
  des départements, le 2025-07-11 à 00 et 03 UTC) ; la règle « jamais de 00 à
  09 UTC » ne vaut que pour les mailles des 34 localités ;
- l'écart de mars 2024 entre journalier et mensuel atteint 6,0 % (Doropo) aux
  départements.
