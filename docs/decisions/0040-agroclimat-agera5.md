# ADR-0040 — Agroclimat AgERA5 : ET0, Tmin, Tmax, déficit de pression de vapeur

Date : 2026-11-11. Statut : accepté — **gravé** (migration 0059).

## Contexte

L'inventaire des données agricoles sur la Côte d'Ivoire (novembre 2026) a
montré que l'offre la plus riche se trouve au point, en agroclimat. Le moteur
sert déjà le rayonnement, la température moyenne, l'humidité, le vent et la
pluie aux 142 localités. Il lui manque les grandeurs qu'un agronome demande en
premier :
- l'**évapotranspiration de référence** (ET0), base du calcul des besoins en
  eau des cultures ;
- les **températures minimale et maximale** du jour (degrés-jours, stress
  thermique, nuits fraîches) ;
- le **déficit de pression de vapeur** aux heures chaudes, qui mesure le
  pouvoir desséchant de l'air.

AgERA5 (Copernicus C3S, Wageningen Environmental Research) les sert toutes
quatre. Il tire des valeurs horaires d'ERA5 des indicateurs journaliers,
agrégés sur le jour local et ramenés sur une grille de 0,1° avec une
correction d'altitude. La version 2.0 corrige les Tmin aberrantes et les
Tmoy supérieures à Tmax de la version 1. Licence CC BY 4.0, accès par le
Climate Data Store, avec la clé Copernicus déjà utilisée pour ERA5.

## Décision

1. **Source** `agera5` (id 19), jeu CDS `sis-agrometeorological-indicators`,
   version 2_0, méthode `reanalyse`, confiance B.
2. **Quatre grandeurs nouvelles** au référentiel (F1, `stockee`) :

   | Code (id) | Variable AgERA5 | Unité servie → référentiel |
   |---|---|---|
   | `et0` (47) | `reference_evapotranspiration` (Penman-Monteith FAO-56) | mm/jour |
   | `t2m_min` (48) | `2m_temperature`, `24_hour_minimum` | K → °C |
   | `t2m_max` (49) | `2m_temperature`, `24_hour_maximum` | K → °C |
   | `vpd_tmax` (50) | `vapour_pressure_deficit_at_maximum_temperature` | hPa → kPa |

   Les autres variables d'AgERA5 (température moyenne, pluie, rayonnement,
   vent, humidité) doublent des séries déjà gravées : elles ne sont pas prises.
3. **Requêtes** : une par grandeur et par année, sur la zone de la Côte
   d'Ivoire. Le CDS plafonne le coût d'une requête à 400 ; une année d'une
   grandeur en coûte 372, et plusieurs variables ou statistiques se
   multiplient.
4. **Maille** : la maille de 0,1° qui contient la localité, sans
   interpolation. Les nœuds d'AgERA5 sont aux multiples de 0,1°. 38 localités
   ont une coordonnée multiple impaire de 0,05° et tombent sur une limite de
   maille : elles sont rattachées à la maille au sud et à l'est, comme pour
   CHIRPS (ADR-0036). 119 mailles pour 142 localités, toutes terrestres
   (AgERA5 masque la mer).
5. **Jour** : le jour local 00 h-00 h d'AgERA5, soit le jour civil en Côte
   d'Ivoire (UTC+0).
6. **Mensuel** : moyenne des jours du mois, dans l'unité du journalier.
   AgERA5 ne sert que du journalier.
7. **Gravure** (migration 0059), 1991-2025 :
   - 568 séries journalières, 7 261 312 mesures, par `COPY` avec l'audit par
     série (ADR-0031) ;
   - 568 séries mensuelles, 238 560 mesures, audit ligne à ligne ;
   - 568 lignes de dégénérescence de pixel, selon la règle de 0042
     (ADR-0027).

## Résultats

Sur les jours de 1991-2025, aux 142 localités :

| Grandeur | Moyenne | Plus bas | Plus haut | Mois extrêmes |
|---|---|---|---|---|
| ET0 | 4,02 mm/jour | 3,38 (San-Pédro) | 5,29 (Doropo) | 4,85 en février, 3,26 en août |
| Tmin | 22,36 °C | 19,93 (Biankouma) | 25,39 (Jacqueville) | 23,63 en avril, 21,28 en décembre |
| Tmax | 30,67 °C | 26,71 (Sassandra) | 33,17 (M’Bengué) | 33,53 en février, 27,67 en août |
| Déficit à Tmax | 1,99 kPa | 0,64 (Jacqueville) | 3,15 (Tengréla) | 3,01 en février, 1,25 en août |

Contrôles et recoupements (`scripts/ingest_agera5.py`) :
- Tmin ≤ Tmax chaque jour-localité ; le déficit atteint au plus 97,9 % de la
  pression de vapeur saturante à Tmax.
- **Jour** : face aux extrêmes des 24 heures UTC d'ERA5 au nœud de 0,25° (cache
  horaire de 0057, 110 nœuds), Tmin et Tmax sont corrélées à 0,955 et 0,964 le
  même jour, à 0,78-0,82 avec un jour de décalage. Le jour d'AgERA5 est bien le
  jour civil.
- AgERA5 est plus frais que ces extrêmes horaires : −0,23 °C sur Tmin,
  −0,63 °C sur Tmax en moyenne. La maille et la correction d'altitude
  diffèrent ; l'écart n'est pas corrigé.
- La température moyenne journalière ERA5 (0053) tombe entre Tmin et Tmax
  99,82 % des jours-localités ; la demi-somme de Tmin et Tmax la dépasse de
  0,13 °C en moyenne (0,41 en valeur absolue).
- La formule de Hargreaves (FAO-56, équation 52), sur Tmin, Tmax et
  l'irradiation extraterrestre, donne 4,19 mm/jour pour une ET0 de 4,02,
  corrélée à 0,75 au jour le jour. Elle ignore l'humidité et le vent.

Les notes publiques citent les chiffres recalculables depuis la base ; les
tests d'intégration les vérifient.

## Conséquences

- Les besoins en eau d'une culture se calculent désormais au point, aux 142
  localités : ET0 multipliée par le coefficient cultural de la FAO, comparée à
  la pluie des quatre sources.
- Tmin et Tmax ouvrent les degrés-jours de croissance et le décompte des jours
  de stress thermique, au jour près depuis 1991.
- Le déficit de pression de vapeur à Tmax complète l'humidité moyenne : il dit
  la sécheresse de l'air aux heures où les plantes transpirent le plus.
- AgERA5 reste une réanalyse : une seule maille de 0,1° par localité, aucune
  mesure au sol. Le calage sur des stations attendra la confiance A.
