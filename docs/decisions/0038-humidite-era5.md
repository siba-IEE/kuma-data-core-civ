# ADR-0038 — Humidité relative ERA5 par la voie horaire

Date : 2026-10-28. Statut : accepté — **gravé** (migration 0057).

## Contexte

L'humidité relative à 2 m (`rh2m`) n'avait qu'une source : NASA POWER
(réanalyse MERRA-2), en mensuel aux 142 localités (0034) et en journalier aux
142 localités (0035 et 0047). Toutes les autres grandeurs météo ont une deuxième
source, ERA5.

ERA5 ne sert pas d'humidité relative au sol. Elle se calcule depuis la
température (`2m_temperature`) et le point de rosée
(`2m_dewpoint_temperature`). L'ADR-0021 s'était abstenu de la graver :
- la recalculer depuis les moyennes mensuelles de T et de Td la sous-estime de
  1,77 point en moyenne aux 3 pilotes (jusqu'à 6,58), car la formule n'est pas
  linéaire ;
- seule la moyenne des humidités horaires est sans biais par construction.
  Elle demande les séries horaires aux 110 mailles, et la décision était restée
  ouverte.

Depuis, la température et le vent journaliers ERA5 (0053, ADR-0034) ont été
gravés depuis ces mêmes séries horaires ponctuelles. L'utilisateur a choisi de
graver l'humidité ERA5 comme deuxième source, toujours en données brutes de
confiance B.

## Décision

1. **Données** : séries horaires ERA5 `2m_temperature` et
   `2m_dewpoint_temperature` (K), jeu `reanalysis-era5-single-levels-timeseries`
   du CDS, une requête par nœud 0,25° (`scripts/ingest_era5_cds_humidite.py`).
   Même maille que 0036, 0050 et 0053 : 110 nœuds pour 142 localités,
   1991-2025.
2. **Humidité horaire**, formule d'ECMWF (fonctions Metview
   `relative_humidity_from_dewpoint` et `saturation_vapour_pressure`, phase
   eau) :
   - `HR = 100 · e_sat(Td) / e_sat(T)` ;
   - `e_sat(T) = 611,21 · exp(17,502 · (T − 273,16) / (T − 32,19))` Pa
     (Tetens sur l'eau) ;
   - la Côte d'Ivoire ne gèle pas : la phase eau suffit. Aucune valeur n'est
     écrêtée.
3. **Agrégation** :
   - jour J : moyenne des 24 humidités horaires datées de 00 h à 23 h UTC, comme
     la température 0053 ;
   - mois : moyenne de toutes les humidités horaires du mois, égale à la moyenne
     de ses jours.
4. **Gravure** (migration 0057) :
   - 142 séries `ecmwf_era5_rh2m_journalier_<localité>`, 1 815 328 mesures,
     par `COPY` avec l'audit par série (ADR-0031) ;
   - 142 séries `ecmwf_era5_rh2m_mensuel_<localité>`, 59 640 mesures, comme
     0036 ;
   - source `ecmwf_era5` (id 2), méthode `reanalyse`, confiance B, unité
     `pourcent`.
5. **Dégénérescence de pixel** (ADR-0027) : toute série mensuelle brute porte
   une ligne `degenerescence_pixel`. La famille étant gravée après 0042, 0057
   grave ses 142 lignes selon la règle de 0042 (égalité exacte des séries, même
   commentaire, maille ERA5 du CDS). La maille est celle de la température
   ERA5 mensuelle : la migration exige les mêmes comptes de jumeaux (82
   localités sans jumeau, 48 avec un, 12 avec deux, soit 110 nœuds).

## Résultats

**Contrôles de l'ingesteur** :
- la température moyenne de chaque jour, recalculée depuis les mêmes fichiers,
  redonne exactement le journalier ERA5 gravé en 0053 : mêmes heures, même
  nœud ;
- chaque mois redonne la moyenne de ses jours gravés, à 0,00007 point près
  (arrondi) ;
- régénérer les CSV depuis le cache redonne les mêmes octets.

**Valeurs** :
- humidité horaire de 2,0 % à 100,02 %. Dans 67 913 heures-nœuds sur
  33 749 760, le point de rosée servi dépasse la température d'au plus
  0,003 K : c'est le bruit du float32, et rien n'est écrêté ;
- journalier de 8,5 % (Bouna, en Harmattan, le 6 février 1999) à 99,6 %
  (Sikensi), 76,4 % en moyenne ;
- mensuel de 17,8 % (Doropo, février 1997) à 93,1 % (Adiaké).

**Biais évité** : l'humidité calculée depuis les moyennes mensuelles de T et de
Td, comparée à la moyenne des humidités horaires, à Abidjan, Yamoussoukro et
Korhogo sur 2016-2025.

| Pilote | Biais moyen | Décembre-février | Pire mois |
|---|---:|---:|---:|
| Abidjan | −0,84 | −1,36 | −4,11 |
| Yamoussoukro | −2,03 | −4,17 | −6,28 |
| Korhogo | −2,45 | −3,48 | −6,57 |

Soit −1,77 point en moyenne. L'ADR-0021 avait mesuré la même chose (−1,77 ;
Korhogo −2,45 ; Yamoussoukro −4,18 en décembre-février ; pire mois −6,58),
avec les coefficients de Magnus au lieu de ceux de Tetens.

**Face à NASA POWER** (MERRA-2), aux mêmes 142 localités, 1991-2025 :

| | ERA5 | NASA | Écart moyen | Par localité |
|---|---:|---:|---:|---|
| Journalier (12 784 jours) | 76,42 % | 74,90 % | +1,52 point | de −2,85 (Duékoué) à +5,66 (Touba) |
| Mensuel (420 mois) | 76,37 % | 74,83 % | +1,54 point | de −2,87 (Duékoué) à +5,71 (Touba) |

- ERA5 est surtout plus humide en saison sèche : +5,03 points de décembre à
  février, contre −0,29 de juin à août.
- L'écart absolu moyen au jour le jour est de 6,04 points. La corrélation
  journalière par localité est de 0,81 en médiane, et de 0,35 au plus bas.
- Deux réanalyses ne sont pas une vérité sol : aucune n'est retenue comme
  référence (ADR-0021).

## Conséquences

- Chaque grandeur météo gravée a désormais deux sources (NASA POWER, ERA5), en
  mensuel et en journalier, aux 142 localités.
- Les calculs qui cherchent l'humidité compagne d'une série ERA5 (même
  localité, même source) la trouvent désormais.
- La décision ouverte de l'ADR-0021 sur l'humidité est tranchée.
