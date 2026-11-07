"""Contrats du ciel clair, de l'irradiation hors atmosphère et de la fiabilité CAMS Radiation.

Colonnes que CAMS Radiation sert à côté du tous ciels (mensuel gravé de 0014 à
0030 et révisé en 0056, journalier en 0054), dans les **mêmes réponses** que lui : mêmes
requêtes, mêmes caches (``ingest_cams_radiation_mensuel.py`` et
``ingest_cams_radiation_journalier.py``, mode ``--ciel-clair``), 142 localités,
2005-2025 (ADR-0039).

| Grandeur | Colonne CAMS | Ce qu'elle mesure |
|---|---|---|
| ``ghi_ciel_clair`` | ``Clear sky GHI`` | global horizontal sans nuage (McClear) |
| ``dni_ciel_clair`` | ``Clear sky BNI`` | direct normal sans nuage (McClear) |
| ``dhi_ciel_clair`` | ``Clear sky DHI`` | diffus horizontal sans nuage (McClear) |
| ``irradiation_extraterrestre`` | ``TOA`` | horizontal au sommet de l'atmosphère |
| ``fiabilite_satellite`` | ``Reliability`` | part des pas de 15 min fiables (0 à 1) |

Le ciel clair vient du modèle **McClear** (aérosols, vapeur d'eau et ozone des
analyses CAMS, altitude du point) : il ne dépend pas des images Meteosat et
CAMS le sert aussi les jours sans images, où le tous ciels manque. Aucune
lacune, donc.

**Conversion** : Wh/m² intégrés sur le pas → kWh/m²/jour (÷ 1000, et ÷ nombre
de jours du mois en mensuel), comme le tous ciels. La fiabilité est sans
dimension, sans conversion. Arrondi à 4 décimales à l'écriture du CSV.

Source ``cams_radiation`` (id 13), méthode ``modele_satellitaire``, confiance
B. Bornes de sanité : celles du tous ciels de même nature (GHI, DNI, DHI de
NASA POWER en journalier, de CAMS en mensuel), 12 kWh/m²/jour pour
l'irradiation hors atmosphère (au plus 10,53 servi), 1 pour la fiabilité.
"""

from __future__ import annotations

import calendar

from kuma_data_core.db.seeds.lots_civ import CONTRATS_CAMS, CONTRATS_NASA_JOURNALIERS
from kuma_data_core.db.seeds.rayonnement_cams_journalier_civ import (
    ANNEE_DEBUT_CAMS_JOURNALIER,
    ANNEE_FIN_CAMS_JOURNALIER,
    LOT_CAMS_JOURNALIER,
    WH_PAR_KWH,
)
from kuma_data_core.db.seeds.series_csv import ContratSerie

LOT_CIEL_CLAIR_CAMS: str = LOT_CAMS_JOURNALIER
"""Suffixe des CSV : les 142 localités en un seul fichier par grandeur (``civ142``)."""

COLONNES_CIEL_CLAIR: dict[str, str] = {
    "ghi_ciel_clair": "Clear sky GHI",
    "dni_ciel_clair": "Clear sky BNI",
    "dhi_ciel_clair": "Clear sky DHI",
    "irradiation_extraterrestre": "TOA",
    "fiabilite_satellite": "Reliability",
}
"""Grandeur → nom de la colonne du CSV CAMS (repérée par nom)."""
GRANDEURS_CIEL_CLAIR: tuple[str, ...] = tuple(COLONNES_CIEL_CLAIR)
SANS_CONVERSION: frozenset[str] = frozenset({"fiabilite_satellite"})

LIBELLES: dict[str, str] = {
    "ghi_ciel_clair": "Irradiation globale horizontale par ciel clair",
    "dni_ciel_clair": "Irradiation normale directe par ciel clair",
    "dhi_ciel_clair": "Irradiation diffuse horizontale par ciel clair",
    "irradiation_extraterrestre": "Irradiation extraterrestre horizontale",
    "fiabilite_satellite": "Fiabilité des observations satellitaires",
}
BORNE_EXTRATERRESTRE: float = 12.0
"""kWh/m²/jour : au plus 10,53 servi (journalier, 142 localités, 2005-2025)."""


def _borne(grandeur: str, granularite: str) -> float:
    if grandeur == "fiabilite_satellite":
        return 1.0
    if grandeur == "irradiation_extraterrestre":
        return BORNE_EXTRATERRESTRE
    tous_ciels = grandeur.removesuffix("_ciel_clair")
    contrats = CONTRATS_NASA_JOURNALIERS if granularite == "journalier" else CONTRATS_CAMS
    return contrats[tous_ciels].borne_max


def _contrat(grandeur: str, granularite: str) -> ContratSerie:
    return ContratSerie(
        source_code="cams_radiation",
        source_id=13,
        source_libelle="CAMS Radiation",
        prefixe_code=f"cams_{grandeur}_{granularite}",
        grandeur_code=grandeur,
        methode_collecte="modele_satellitaire",
        annee_debut=ANNEE_DEBUT_CAMS_JOURNALIER,
        annee_fin=ANNEE_FIN_CAMS_JOURNALIER,
        borne_max=_borne(grandeur, granularite),
        granularite=granularite,
        libelle_grandeur=LIBELLES[grandeur],
    )


CONTRATS_CIEL_CLAIR_JOURNALIERS: dict[str, ContratSerie] = {
    g: _contrat(g, "journalier") for g in GRANDEURS_CIEL_CLAIR
}
CONTRATS_CIEL_CLAIR_MENSUELS: dict[str, ContratSerie] = {
    g: _contrat(g, "mensuel") for g in GRANDEURS_CIEL_CLAIR
}


def valeur_journaliere(grandeur: str, servie: float) -> float:
    """Valeur du jour : Wh/m² → kWh/m²/jour, fiabilité telle que servie."""
    return servie if grandeur in SANS_CONVERSION else servie / WH_PAR_KWH


def valeur_mensuelle(grandeur: str, servie: float, annee: int, mois: int) -> float:
    """Valeur du mois : Wh/m² du mois → kWh/m²/jour moyen, fiabilité telle que servie."""
    if grandeur in SANS_CONVERSION:
        return servie
    return servie / WH_PAR_KWH / calendar.monthrange(annee, mois)[1]
