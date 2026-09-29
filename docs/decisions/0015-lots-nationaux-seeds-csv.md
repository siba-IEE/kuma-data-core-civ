# ADR-0015 : Couverture nationale par lots — seeds CSV gzip

Date : 2026-09-29. Statut : accepté — lots « régions » (0025) et « départements »
(0027) **gravés** ; le journalier suit l'ADR-0016 (0026).

## Contexte

Les séries solaires (ADR-0007 à ADR-0014) ne couvrent que 3 points pilotes
(départements d'Abidjan, Yamoussoukro, Korhogo). Objectif : couvrir **tout le
pays** en données brutes, d'abord aux **31 régions**, puis aux **108 autres
départements**, puis au **journalier NASA POWER** (décision du 2026-09-29).

Aux 3 points, chaque (source, grandeur) est un module Python généré
(`series_*_civ.py`, un tuple par mois). Au lot régions, cela ferait ~68 000
tuples ; aux départements ~240 000 ; au journalier, des millions. Les modules
Python deviennent inadaptés (taille, temps d'import, lint et typage).

## Décision

### Seeds des lots : CSV gzip committés

- Un fichier par (source, grandeur, lot) : `src/kuma_data_core/db/seeds/donnees/
  <prefixe>_<lot>.csv.gz`, colonnes `localite_code, latitude, longitude, annee,
  mois, valeur` (kWh/m²/jour, 4 décimales).
- **Écriture déterministe** (`series_csv.ecrire_series`) : lignes triées,
  horodatage gzip nul. Régénérer depuis les mêmes données donne les mêmes
  octets (vérifié) : la continuité reste contrôlable par `git diff`.
- **Lecture validée** (`series_csv.lire_series`) : en-tête, période, bornes,
  doublons, complétude (12 mois × années du contrat, par localité), localités
  connues du référentiel. L'écriture n'est acceptée que si la relecture passe.
- L'invariant du dépôt est inchangé : **les migrations n'accèdent jamais au
  réseau** et chaque valeur gravée est versionnée dans git.

Les 3 points pilotes gardent leurs modules Python (déjà gravés, inchangés : le
mode par défaut des ingesteurs les régénère à l'octet près).

### Contrats identiques aux séries pilotes

`seeds/lots_civ.py` déclare, par source et grandeur, un `ContratSerie` identique
au contrat pilote :

| Source (id) | Grandeurs | Période | Méthode |
|---|---|---|---|
| NASA POWER (1) | GHI / DNI / DHI | 1991 / 2001 / 2001 → 2020 | `modele_satellitaire` |
| SARAH-3 PVGIS (11) | GHI / DNI | 2005-2020 | `modele_satellitaire` |
| ERA5 PVGIS (16) | GHI / DNI | 2005-2020 | `reanalyse` |
| CAMS Radiation (13) | GHI / DNI / DHI | 2005-2020 | `modele_satellitaire` |

Aucune nouvelle source, grandeur ni valeur d'énumération. Les codes de série
suivent la convention pilote (`<prefixe>_<code localité>`).

### Ingesteurs : option `--lot`

Les 4 ingesteurs (NASA, SARAH-3, ERA5, CAMS) acceptent `--lot <nom>` : mêmes
requêtes et garde-fous, points lus dans `lots_civ.points_lot`, sortie CSV gzip.
L'ingesteur CAMS parallélise les requêtes ADS (4 par défaut) et garde les CSV
bruts en cache (`--cache`) pour reprendre après une interruption.

### Une migration par lot

La migration d'un lot parcourt les contrats, relit chaque CSV, insère séries et
mesures, et vérifie : identité de chaque source, couverture exacte des
localités du lot, nombre de mesures par famille et total.

## Lot 1 — régions (migration 0025)

31 régions (niveau `prefecture`, coordonnées Wikidata `P625` gravées en 0006) ×
10 familles = **310 séries**, **67 704 mesures**.

**Limite de résolution NASA POWER** (constat sur les CSV du lot) : les 31
régions ne donnent que **22 séries NASA distinctes** (GHI comme DHI) ; 8 groupes
de régions voisines partagent exactement les mêmes valeurs, par exemple Poro et
Tchologo, ou Agnéby-Tiassa, Indénié-Djuablin et La Mé. C'est cohérent avec la
maille solaire d'environ 1° de NASA POWER (CERES). Ces séries sont gravées
telles quelles, par localité : la duplication est un fait de la source, pas une
erreur. SARAH-3 (31 séries distinctes sur 31) et CAMS sont propres à chaque
point.

**Aperçu national** (moyennes 2005-2020 par région, kWh/m²/jour) :

| Grandeur | Source | Min (région) | Max (région) | Corrélation avec la latitude |
|---|---|---|---|---:|
| GHI | NASA POWER | 4,49 (Lôh-Djiboua) | 5,64 (Folon) | 0,86 |
| GHI | SARAH-3 | 5,07 (Sud-Comoé) | 5,98 (Folon) | 0,80 |
| GHI | CAMS | 4,80 (Sud-Comoé) | 5,89 (Folon) | 0,83 |
| GHI | ERA5 | 4,38 (Nawa) | 5,58 (Tchologo) | 0,76 |
| DNI | NASA POWER | 1,93 (La Mé) | 3,74 (Folon) | 0,82 |
| DNI | CAMS | 2,92 (Sud-Comoé) | 4,90 (Folon) | 0,78 |
| DHI | NASA POWER | 2,41 (San-Pédro) | 2,59 (Bagoué) | 0,71 |
| DHI | CAMS | 2,38 (San-Pédro) | 2,74 (Agnéby-Tiassa) | −0,45 |

Toutes les sources montrent le **gradient sud → nord** du GHI et du DNI (plus de
ressource vers le nord, Folon en tête). Le DHI varie peu d'une région à l'autre
et les deux sources ne s'accordent pas sur son sens de variation : constat, pas
interprétation.

Les écarts inter-sources et la fraction diffuse restent, à ce stade, limités
aux 3 points pilotes : leur extension aux lots est une étape distincte.

## Lot 2 — départements (migration 0027)

108 départements (niveau `commune`, coordonnées gravées en 0007) **hors les 3
points pilotes**, déjà gravés en seeds Python : **1080 séries**, **235 872
mesures**. Avec les pilotes, les **111 départements** du pays sont couverts.
L'ingestion CAMS (108 requêtes ADS, 4 en parallèle) a pris environ 2 h, avec
une coupure réseau reprise automatiquement par le client.

**Aperçu départemental** (moyennes 2005-2020 sur les 111 départements,
kWh/m²/jour) :

| Grandeur | Source | Séries distinctes | Min | Max | Corrélation avec la latitude |
|---|---|---:|---|---|---:|
| GHI | NASA POWER | 35 | 4,49 (Grand-Lahou) | 5,64 (Minignan) | 0,88 |
| GHI | SARAH-3 | 111 | 4,94 (Alépé) | 6,03 (Tengréla) | 0,80 |
| GHI | CAMS | 111 | 4,62 (Abidjan) | 5,93 (Tengréla) | 0,84 |
| GHI | ERA5 | 111 | 4,34 (Guéyo) | 5,72 (Tengréla) | 0,83 |
| DNI | NASA POWER | 35 | 1,93 (Akoupé) | 3,74 (Minignan) | 0,88 |
| DNI | CAMS | 111 | 2,74 (Abidjan) | 4,98 (Tengréla) | 0,82 |
| DHI | NASA POWER | 35 | 2,39 (Tabou) | 2,59 (Kouto) | 0,60 |
| DHI | CAMS | 111 | 2,39 (Kaniasso) | 2,76 (Adzopé) | −0,60 |

NASA POWER ne distingue que **35 valeurs** sur les 111 départements (maille
d'environ 1°) ; pour une étude à l'échelle d'un département, SARAH-3 et CAMS
sont les seules sources qui varient réellement d'un point à l'autre. Le
gradient sud → nord du GHI et du DNI se confirme dans toutes les sources ; le
DHI reste peu variable et les sources divergent sur son sens.

## Coût opérationnel

La reconstruction complète 0001 → 0027 prend environ 2 min 30. La suite de
tests prenait environ 4 min 30 ; la cause n'était pas la fidélité intégrale
mais des statistiques Postgres absentes après les insertions massives, corrigé
par l'ADR-0017 (suite ramenée à ~26 s, couverture intégrale conservée).

## Suite

- Journalier NASA : gravé aux 3 pilotes et 31 régions (migration 0026,
  [ADR-0016](0016-nasa-power-journalier.md)).
- Écarts inter-sources et fraction diffuse étendus aux lots (migrations
  0028-0029, [ADR-0017](0017-grandeurs-derivees-lots-nationaux.md)).
