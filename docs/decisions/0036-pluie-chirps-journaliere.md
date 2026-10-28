# ADR-0036 — Pluie journalière CHIRPS v3.0

Date : 2026-10-28. Statut : accepté — **gravé** (migration 0055).

## Contexte

La pluie journalière était gravée depuis trois sources :
- NASA POWER (0035, 0047), à ne pas utiliser pour les épisodes (ADR-0032) ;
- ERA5 (0050) ;
- GPM IMERG (0052), source de la salissure (ADR-0033).

CHIRPS n'avait été consulté que ponctuellement, lors du recoupement de
l'ADR-0032. L'utilisateur a demandé de le graver comme donnée brute en
confiance B, la confiance A venant à la fin.

## Décision

1. **Version** : CHIRPS v3.0, version finale, publiée le 2025-01-01. La v2.0
   s'arrête en décembre 2026.
2. **Désagrégation journalière** : `rnl`, qui répartit le cumul pentadaire selon
   les proportions journalières d'ERA5. Elle couvre de 1981 à nos jours, donc
   toute la période 1991-2025. La variante `sat` (IMERG Late) ne commence qu'en
   1998, et le CHC ne recommande ni l'une ni l'autre.
3. **Lecture** : les COG journaliers quasi globaux du CHC, lus par plages
   d'octets (GDAL `/vsicurl/`), sans télécharger les fichiers complets.
   - Le serveur refuse les rafales de requêtes et les requêtes à plusieurs
     plages (HTTP 403). La lecture se fait donc une requête à la fois, une
     plage par requête, avec une pause entre deux jours.
   - Il a fallu environ 4 heures sur trois relances, reprises depuis le cache
     annuel.
4. **Maille** : celle de 0,05° qui contient la localité (`maille_chirps`),
   calculée en arithmétique exacte.
   - 76 des 142 localités ont des coordonnées multiples de 0,05° et tombent sur
     une limite de maille. Elles sont rattachées à la maille au sud et à l'est
     de la limite, selon la convention de GDAL.
   - Cela donne 121 mailles distinctes.
5. **Gravure** :
   - source `chirps` (id 18, à id figé, identité des sources recalée) ;
   - 142 séries `chirps_precipitation_journalier_<localité>`, 1 815 328
     mesures ;
   - méthode `modele_satellitaire`, confiance B, audit par série.
6. **Licence et citation** :
   - Les données sont dans le domaine public, enregistrées auprès de Creative
     Commons, et sous licence CC BY 4.0 (page CHIRPS3 du CHC).
   - Citation : dépôt DOI 10.15780/G2JQ0P et article Funk et al. (2026),
     *Scientific Data* 13, 718.

## Ce que vaut le journalier CHIRPS

Le CHC le dit lui-même : CHIRPS est un produit pentadaire et mensuel, et son
journalier **n'est pas indépendant**. Le cumul de chaque pentade est
l'information propre de CHIRPS, qui fond satellite et pluviomètres. En
revanche, sa répartition entre les jours suit ERA5, interpolé de 0,25° à 0,05°.

Quand ERA5 est sec sur une pentade pluvieuse pour CHIRPS, le cumul est réparti
également entre les jours, ce qui peut créer de faux épisodes. La note publique
le dit : à utiliser en cumuls de pentade ou de mois, pas pour les extrêmes
journaliers.

## Résultats

**Cohérence interne** : la somme des jours redonne le CHIRPS v3.0 mensuel à
0,0001 mm près sur 50 699 mois-mailles. Seule exception, février 2000 : 5
mailles sur 121 diffèrent, jusqu'à 4,1 mm.
- Les jours 21 à 29 portent de la pluie là où le mensuel est nul, ou l'inverse.
- C'est une incohérence de la source, non corrigée et citée par la note.
- L'ingesteur la déclare (`MOIS_INCOHERENTS`) et reste strict ailleurs.

**Contrôles de lecture** :
- un jour par an, le COG est identique au GeoTIFF du même jour ;
- aucune maille océan ni valeur négative aux mailles retenues.

**Recoupement aux 142 localités** :
- **Jours extrêmes de NASA** : aux 25 jours-localités où NASA POWER dépasse
  200 mm, CHIRPS donne au plus 21,2 mm le jour même et 54,8 mm sur trois jours.
  À San-Pédro le 2022-09-16, il donne 1,65 mm, contre 726,74 mm pour NASA. Cela
  confirme l'ADR-0032.
- **Rupture des fortes pluies** : les jours-localités > 50 mm passent de 89,8
  par an (1991-2015) à 111,0 (2017-2025), soit ×1,24, contre ×1,67 pour ERA5 et
  ×12 pour NASA. La rupture de NASA lui reste propre.
- **Cumul annuel moyen 1998-2025** :

  | Source | Cumul annuel moyen |
  |---|---:|
  | CHIRPS | 1 387 mm |
  | NASA POWER | 1 393 mm |
  | ERA5 | 1 256 mm |
  | IMERG | 1 287 mm |

- **Maximum journalier de CHIRPS** : 259,8 mm à Dabou, le 2015-06-10.

**Reproductibilité** :
- régénérer le CSV depuis le cache redonne les mêmes octets ;
- l'aller-retour `downgrade`/`upgrade` redonne la même empreinte, supprime la
  source puis la recrée, et recale l'identité.

## Conséquences

- Quatre sources de pluie journalière aux 142 localités.
- La salissure et le PR réaliste restent sur IMERG (ADR-0033). CHIRPS sert au
  recoupement des cumuls de pentade et de mois, au plus près des pluviomètres.
- Une éventuelle gravure pentadaire de CHIRPS demanderait une granularité que
  le schéma n'a pas.
