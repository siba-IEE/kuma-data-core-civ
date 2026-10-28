"""meteo_era5_journaliere

Revision ID: 0053
Revises: 0052
Create Date: 2026-10-28

**Température et vent journaliers ERA5 (CDS Copernicus) aux 142 localités** :
deuxième source journalière de ``t2m`` et ``vent_10m``, à côté de NASA POWER
(réanalyse MERRA-2, 0035 et 0047). Les moyennes mensuelles ERA5 sont gravées
depuis 0036 (ADR-0021), la pluie journalière ERA5 depuis 0050.

| Grandeur | Variables CDS horaires | Valeur du jour | Conversion | Période | Jours par série | Mesures |
|---|---|---|---|---|---:|---:|
| ``t2m`` | ``2m_temperature`` | moyenne des heures 00 h → 23 h | K − 273,15 → °C | 1991-2025 | 12 784 | 1 815 328 |
| ``vent_10m`` | ``10m_u_component_of_wind``, ``10m_v_component_of_wind`` | moyenne des vitesses √(u² + v²) des heures 00 h → 23 h | aucune (m/s) | 1991-2025 | 12 784 | 1 815 328 |

Soit **284 séries** ``ecmwf_era5_<grandeur>_journalier_<localité>``
(``granularite='journalier'``, table ``mesures_ressource``) et **3 630 656
mesures**, source ``ecmwf_era5`` (id 2), méthode ``reanalyse``, confiance
**B**. Contrats : ``meteo_era5_journaliere_civ.CONTRATS_METEO_ERA5_JOURNALIERS``.
Valeurs horaires instantanées ERA5 lues nœud par nœud dans le jeu
``reanalysis-era5-single-levels-timeseries`` (mêmes valeurs que le jeu sur
grille), jour civil UTC = jour civil local (UTC+0). Valeur au point de grille
0,25° le plus proche, **même maille que 0036 et 0050** (110 mailles pour 142
localités). Aucune nouvelle source, grandeur, unité ni valeur d'énumération.

Cohérence avec le mensuel 0036 (moyenne des jours du mois − mensuel, 59 640
mois-localités) : ``t2m`` à 0,002 °C près ; ``vent_10m`` toujours inférieur, de
0,001 à 0,110 m/s (0,021 en moyenne) : le jeu ponctuel ne sert pas la variable
``10m_wind_speed`` du mensuel, la vitesse horaire est recalculée depuis les
composantes. Écart publié dans la note publique, non corrigé.

Face à NASA POWER journalier (MERRA-2, 0035 et 0047) aux mêmes 142 localités et
12 784 jours : ERA5 est plus chaude de 0,27 °C en moyenne (0,95 °C d'écart absolu
moyen au jour le jour) et son vent plus faible de 19 % (2,04 contre 2,52 m/s).

Valeurs lues hors-ligne dans les CSV gzip committés
(``seeds/donnees/ecmwf_era5_<grandeur>_journalier_civ142.csv.gz``, générés par
``scripts/ingest_era5_cds_meteo_journalier.py``) et validées par
``series_csv.lire_series_journalieres``. Insertion par ``COPY`` avec l'**audit
par série** (``gravure_journaliere``, ADR-0031).

Garde-fous : identité de la source, unités du référentiel, 142 localités,
**aucune série journalière ERA5 préexistante** pour ces grandeurs, couverture
exacte des CSV, 284 séries et 3 630 656 mesures. ``ANALYZE`` en fin de
migration. ``downgrade`` écrit l'audit par série de la suppression, puis
supprime les mesures (audit ligne à ligne suspendu) et les séries.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.gravure_journaliere import graver_lot, supprimer_lot
from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.meteo_era5_journaliere_civ import (
    CONTRATS_METEO_ERA5_JOURNALIERS,
    LOT_METEO_ERA5_JOURNALIERE,
)
from kuma_data_core.db.seeds.series_csv import ContratSerie

# revision identifiers, used by Alembic.
revision: str = "0053"
down_revision: str | Sequence[str] | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVISION: str = "0053"
SOURCE_ID: int = 2
SOURCE_CODE: str = "ecmwf_era5"
NB_POINTS: int = 142
NB_MESURES_ATTENDU: int = 3_630_656  # 2 × 142 × 12 784
UNITES: dict[str, str] = {"t2m": "degree_celsius", "vent_10m": "metre_par_seconde"}

ATTRIBUTION: str = (
    "Attribution : contient des informations modifiées du Copernicus Climate Change Service (2026)."
)
NOTES: dict[str, str] = {
    "t2m": (
        "Température à 2 m journalière ERA5 (réanalyse ECMWF, Copernicus C3S ; valeurs "
        "horaires du CDS, jeu reanalysis-era5-single-levels) : moyenne des 24 valeurs "
        "horaires instantanées datées de 00 h à 23 h du jour civil UTC (jour civil local, "
        "UTC+0), en °C (convertie des kelvins). Point de grille 0,25° le plus proche, "
        "1991-2025, même maille que la série mensuelle ERA5 (0036) : la moyenne des jours "
        "du mois la redonne à 0,002 °C près. Face à la température journalière NASA POWER "
        "(MERRA-2) aux mêmes localités, ERA5 est plus chaude de 0,27 °C en moyenne sur "
        "1991-2025 (de −0,49 °C à Touba à +1,59 °C à Kouibly selon la localité), avec "
        "0,95 °C d'écart absolu moyen au jour le jour. Confiance B "
        "(réanalyse) ; jamais une mesure au sol (ADR-0021, ADR-0034). "
    ),
    "vent_10m": (
        "Vent à 10 m journalier ERA5 (réanalyse ECMWF, Copernicus C3S ; composantes "
        "horaires u et v du CDS, jeu reanalysis-era5-single-levels) : moyenne des 24 "
        "vitesses horaires √(u² + v²) datées de 00 h à 23 h du jour civil UTC (jour civil "
        "local, UTC+0), en m/s, et non norme des composantes moyennes. Point de grille "
        "0,25° le plus proche, 1991-2025, même maille que la série mensuelle ERA5 (0036). "
        "Le CDS ne sert pas la vitesse horaire du vent : elle est recalculée depuis les "
        "composantes, et la moyenne des jours du mois reste sous le mensuel ERA5 "
        "(10m_wind_speed) de 0,001 à 0,110 m/s selon le mois (0,021 m/s en moyenne), non "
        "corrigé. "
        "Face au vent journalier NASA POWER (MERRA-2) aux mêmes localités, ERA5 est plus "
        "faible de 19 % en moyenne sur 1991-2025 (2,04 contre 2,52 m/s ; de −1,68 m/s à "
        "Tiapoum à +0,96 m/s à Issia selon la localité). Confiance B (réanalyse) ; jamais "
        "une mesure au sol "
        "(ADR-0021, ADR-0034). "
    ),
}


def _codes_localites() -> list[str]:
    return sorted(code for code, _, _, _ in points_nationaux())


def _contrats() -> list[ContratSerie]:
    return list(CONTRATS_METEO_ERA5_JOURNALIERS.values())


def _note(contrat: ContratSerie, _serie: dict[str, Any]) -> str:
    return NOTES[contrat.grandeur_code] + ATTRIBUTION


def upgrade() -> None:
    bind = op.get_bind()
    contrats = _contrats()

    # 0. Garde-fous : source, unités du référentiel, localités, séries préexistantes.
    code_source = bind.execute(
        sa.text("SELECT code FROM sources WHERE id = :i"), {"i": SOURCE_ID}
    ).scalar_one_or_none()
    if code_source != SOURCE_CODE:
        raise RuntimeError(
            f"Migration {REVISION} : source id {SOURCE_ID} = {code_source!r}, "
            f"{SOURCE_CODE!r} attendue."
        )
    unites = {
        row.grandeur: row.unite
        for row in bind.execute(
            sa.text(
                "SELECT g.code AS grandeur, u.code AS unite FROM grandeurs_referentiel g "
                "JOIN unites u ON u.id = g.unite_id WHERE g.code = ANY(:g) AND g.actif"
            ),
            {"g": list(UNITES)},
        ).all()
    }
    if unites != UNITES:
        raise RuntimeError(f"Migration {REVISION} : unités {unites!r}, {UNITES!r} attendues.")
    codes_loc = _codes_localites()
    loc = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:c)"), {"c": codes_loc}
        ).all()
    }
    if len(codes_loc) != NB_POINTS or sorted(loc) != codes_loc:
        raise RuntimeError(
            f"Migration {REVISION} : {len(loc)} localités trouvées sur {len(codes_loc)}, "
            f"{NB_POINTS} attendues."
        )
    preexistantes = bind.execute(
        sa.text(
            """
            SELECT code FROM series_metadonnees
            WHERE code = ANY(:codes)
               OR (source_id = :src AND granularite = 'journalier' AND grandeur_code = ANY(:g))
            """
        ),
        {
            "codes": [c.code_serie(code) for c in contrats for code in codes_loc],
            "src": SOURCE_ID,
            "g": list(UNITES),
        },
    ).all()
    if preexistantes:
        raise RuntimeError(
            f"Migration {REVISION} : séries déjà présentes : {[r.code for r in preexistantes]!r}."
        )

    # 1. Séries, mesures par COPY et audit par série.
    total = graver_lot(bind, REVISION, contrats, LOT_METEO_ERA5_JOURNALIERE, loc, _note)
    if total != NB_MESURES_ATTENDU:
        raise RuntimeError(
            f"Migration {REVISION} : {total} mesures, {NB_MESURES_ATTENDU} attendues."
        )
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource"))


def downgrade() -> None:
    bind = op.get_bind()
    supprimer_lot(bind, REVISION, _contrats(), LOT_METEO_ERA5_JOURNALIERE, _codes_localites())
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource"))
