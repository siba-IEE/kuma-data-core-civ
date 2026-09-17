# ADR-0007 : contrat de série — climatologie GHI mensuel NASA POWER (1991-2020)

Date : 2026-09-17. Statut : accepté.

## Contexte

Le Jalon 2 (donnée solaire brute) commence par une première **série** de
climatologie satellitaire, en confiance B, aux points ivoiriens. La
reconnaissance NASA POWER (lecture seule) a confirmé sur donnée brute : valeurs
cohérentes (gradient nord-sud, creux mousson juillet-août), unité renvoyée
``kW-hr/m^2/day``, clé ``AAAA13`` = moyenne annuelle. Trois choix de convention
touchant la correction de l'écriture devaient être tranchés avant de graver.

## Décision

**Contrat de la série** (une par point d'ingestion) :

| Élément | Valeur | Résolution / justification |
|---|---|---|
| Source | ``nasa_power`` (``sources``, id 1) | seedée en 0002 |
| Grandeur | ``ghi`` (id 16) | description cite ``ALLSKY_SFC_SW_DWN`` |
| Unité | ``kwh_par_m2_jour`` (id 63) | **fixée par la grandeur** (``grandeurs_referentiel.unite_id``), héritée par les mesures |
| Granularité | ``mensuel`` | choix opérateur |
| Méthode collecte | ``modele_satellitaire`` | NASA POWER = modèle satellite/réanalyse |
| Table des mesures | ``mesures_ressource_mensuelles`` | **Point 1** ci-dessous |
| Millésime | **1991-2020** (360 mois) | **Point 2** ci-dessous |
| Confiance dérivée | **B** | **Point 3** ci-dessous |
| Statut | ``brut`` | ingestion brute, non encore validée éditorialement |

**Point 1 — table cible.** La description de ``ghi`` désigne
``mesures_ressource`` (journalier) comme stockage par défaut (cadrage Q7). Pour
une ingestion de **granularité mensuelle**, la table dédiée est
``mesures_ressource_mensuelles`` — son propre commentaire la cadre explicitement
autour de « SARAH-3 ICDR + **NASA POWER** », comme pendant mensuel du journalier.
Le mensuel va donc dans la table mensuelle ; le journalier (Q7) reste un lot
ultérieur distinct.

**Point 2 — millésime.** La valeur mensuelle NASA POWER est la **moyenne
journalière du mois** (kWh/m²/**jour**), pas un cumul. On grave la période
**1991-2020** (normale climatologique standard), alignée sur le commentaire de
la table et sur ADR-0004 (résolution climatologie-au-point « moyenne 1991-2020 »).
La clé ``AAAA13`` (moyenne annuelle NASA POWER) n'est **pas** stockée : elle est
dérivable, et la table impose ``mois BETWEEN 1 AND 12`` (garde-fou structurel).

**Point 3 — confiance B.** Donnée satellite/réanalyse : ``niveau_confiance_derive
= 'B'``. Le niveau A reste réservé à la mesure sol (ancre ESMAP, Jalon 4). C'est
un acte éditorial assumé, cohérent avec le modèle A/B/C du schéma.

**Reproductibilité.** Les valeurs sont figées dans le seed
``series_nasa_power_ghi_mensuel_civ`` (module Python), **régénérable** par
``scripts/ingest_nasa_power_ghi_mensuel.py`` (accès réseau). La migration 0008
lit ce seed et n'accède jamais au réseau (invariant README :
``alembic upgrade head`` hors-ligne).

**Périmètre initial.** 3 points au niveau département (Abidjan, Yamoussoukro,
Korhogo), grandeur ``ghi`` seule. DNI, DHI et davantage de points suivront (une
série = un ajout, sans nouvelle décision de contrat).

## Conséquences

- La table mensuelle reçoit sa première donnée réelle ; la chaîne
  lecture NASA POWER → seed → migration → base est prouvée de bout en bout.
- Les valeurs sont **recoupables** : chaque mesure = sortie NASA POWER au point,
  reproductible par le script ; bornes physiques 0–7 kWh/m²/jour, 12 mois/an.
- Étendre à DNI (``ALLSKY_SFC_SW_DNI``, même unité) ou à d'autres points ne
  requiert que de rejouer le script et d'ajouter une migration ; le contrat ne
  change pas.
- La comparaison inter-sources (SARAH-3, CAMS, ERA5-Land) au même point
  s'appuiera sur ce contrat ; l'écart inter-source relève d'une couche
  éditoriale ultérieure, pas de l'ingestion brute.
