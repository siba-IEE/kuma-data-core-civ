"""Journalier aux 108 départements hors pilotes (ADR-0031).

Le journalier ne couvrait que 34 localités (3 pilotes + 31 régions, ADR-0016,
ADR-0020, ADR-0022). Ce lot l'étend aux **108 départements** restants
(``points_lot("departements")``) : avec les pilotes, les 111 départements ont
alors un journalier, et les calculs de l'API qui l'exigent (POA, correction
thermique, humidex, salissure, PR réaliste) deviennent possibles partout.

Mêmes contrats que le lot « pilotes + régions », période d'un seul tenant :

- rayonnement NASA POWER : GHI 1991-2025, DNI et DHI 2001-2025 (le lot 34 est
  gravé en deux temps, 1991-2020 puis l'extension 2021-2025 ; ici un seul CSV) ;
- météo NASA POWER : ``meteo_civ.CONTRATS_METEO_NASA_JOURNALIERS`` ;
- particules CAMS EAC4 : ``aerosols_civ.CONTRATS_EAC4_JOURNALIERS`` (2003-2025).

Les mesures sont gravées avec l'**audit par série** (``audit_par_serie``).
"""

from __future__ import annotations

from dataclasses import replace

from kuma_data_core.db.seeds.aerosols_civ import CONTRATS_EAC4_JOURNALIERS
from kuma_data_core.db.seeds.lots_civ import (
    CONTRATS_NASA_JOURNALIERS,
    FIN_EXTENSION,
    points_lot,
)
from kuma_data_core.db.seeds.meteo_civ import CONTRATS_METEO_NASA_JOURNALIERS
from kuma_data_core.db.seeds.series_csv import ContratSerie

LOT_JOURNALIER_DEPARTEMENTS: str = "departements"
"""Suffixe des CSV journaliers des 108 départements hors pilotes."""

NB_DEPARTEMENTS: int = 108


def points_journalier_departements() -> list[tuple[str, str, float, float]]:
    """Les 108 départements hors pilotes : ``(code, nom, latitude, longitude)``."""
    points = points_lot("departements")
    if len(points) != NB_DEPARTEMENTS:
        raise ValueError(f"{len(points)} départements, {NB_DEPARTEMENTS} attendus.")
    return points


CONTRATS_RAYONNEMENT_DEPARTEMENTS: dict[str, ContratSerie] = {
    g: replace(c, annee_fin=FIN_EXTENSION["nasa_power"])
    for g, c in CONTRATS_NASA_JOURNALIERS.items()
}
CONTRATS_METEO_DEPARTEMENTS: dict[str, ContratSerie] = dict(CONTRATS_METEO_NASA_JOURNALIERS)
CONTRATS_PARTICULES_DEPARTEMENTS: dict[str, ContratSerie] = dict(CONTRATS_EAC4_JOURNALIERS)
