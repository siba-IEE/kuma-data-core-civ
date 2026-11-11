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

RESULTATS

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
