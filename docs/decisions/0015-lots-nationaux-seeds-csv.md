# ADR-0015 : Couverture nationale par lots — seeds CSV gzip

Date : 2026-09-29. Statut : accepté — lot « régions » **gravé** (migration 0025).

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

## Suite prévue

- **Lot 2** : les 108 départements non pilotes (niveau `commune`).
- **Lot 3** : NASA POWER journalier (table `mesures_ressource`), même format CSV.
