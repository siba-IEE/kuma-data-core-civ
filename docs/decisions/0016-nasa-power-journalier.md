# ADR-0016 : NASA POWER journalier — lot « pilotes + régions »

Date : 2026-09-29. Statut : accepté — **gravé** (migration 0026).

## Contexte

La couverture nationale (ADR-0015) prévoit, après le mensuel, le **journalier
NASA POWER** (décision du 2026-09-29), grain des grandeurs journalières du
moteur (HEP, variabilité journalière, contrôle qualité). La table
`mesures_ressource` (grain journalier, `instant_mesure` date) porte un
**trigger d'audit par ligne**, et chaque exécution de la CI rejoue toutes les
migrations.

Chiffrage sur un point réel (Abidjan) : une requête pour les 3 paramètres en
1,5 s, 25 568 jours retenus, ~140 Ko en CSV gzip. Sur 142 points (tous les lots),
cela ferait 3,6 M lignes et ~20 Mo dans git, avec beaucoup de doublons (NASA n'a
qu'une maille d'environ 1°).

## Décision

- **Périmètre : 34 localités** — les 3 points pilotes et les 31 régions (choix
  du 2026-09-29). Tout le territoire à la maille régionale, pour ~5 Mo.
- **Contrats** : mêmes périodes que le mensuel NASA — GHI 1991-2020, DNI et DHI
  2001-2020 (DNI non servi, DHI en rupture avant 2001, ADR-0013). kWh/m²/jour
  sans conversion, `modele_satellitaire`, confiance B, source `nasa_power`
  (id 1), `granularite='journalier'`.
- **Seeds** : CSV gzip (ADR-0015), colonnes `localite_code, latitude,
  longitude, date, valeur`, écriture déterministe et relecture validée
  (complétude de **tous les jours civils** par localité). Ingesteur
  `scripts/ingest_nasa_power_journalier.py`, une requête par point.
- **Migration 0026** : 102 séries, **869 312 mesures**, insérées par `COPY`
  (volume) ; garde-fous de source, de couverture et de comptes. Durée mesurée :
  environ 1 min 30, trigger d'audit compris.

## Vérifications

| Contrôle | Résultat |
|---|---|
| Valeurs de remplissage (-999) dans les périodes gravées | aucune |
| Jours avec DHI > GHI (2001-2020, 34 points) | 0 |
| Moyenne des jours du mois vs mensuel NASA gravé (28 560 mois) | écart max 0,00017 kWh/m²/jour (arrondi) |
| Fidélité base ↔ CSV | intégrale (test) |

## Conséquences

- Les grandeurs journalières du moteur deviennent calculables aux 34 points.
- Le journalier des 108 départements reste possible plus tard, au même format,
  si le besoin justifie le volume.
