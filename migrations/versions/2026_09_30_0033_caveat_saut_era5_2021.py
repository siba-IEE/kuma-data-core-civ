"""caveat_saut_era5_2021

Revision ID: 0033
Revises: 0032
Create Date: 2026-09-30

**Mise en garde ERA5 portée par les données** (ADR-0018). Le contrôle de
continuité 2020/2021 a montré un saut propre à ERA5 servi par PVGIS (moyenne
nationale GHI +3,6 %, DNI +7,7 % par rapport à 2016-2020, environ trois fois sa
variabilité interannuelle), absent des autres sources. Jusqu'ici consigné
seulement dans l'ADR : un lecteur de la base ou de l'API ne le voyait pas.

Ajoute une phrase de mise en garde à la note publique de :

- 284 séries **ERA5 brutes** (GHI et DNI mensuels × 142 localités) ;
- 284 séries d'**écart ERA5 − NASA** (GHI et DNI × 142 localités).

**Métadonnées seulement** : aucune valeur n'est modifiée (on grave la source
telle quelle). Garde-fous : exactement 568 séries, aucune ne porte déjà la
phrase. ``downgrade`` retire la phrase.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.lots_civ import CONTRATS_ERA5, ECARTS_INTER_SOURCES, points_nationaux

# revision identifiers, used by Alembic.
revision: str = "0033"
down_revision: str | Sequence[str] | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NB_SERIES_ATTENDU: int = 568  # (2 brutes + 2 écarts) × 142 localités

CAVEAT: str = (
    " Mise en garde : saut probable du produit PVGIS-ERA5 en 2021 (moyenne nationale "
    "GHI +3,6 %, DNI +7,7 % par rapport à 2016-2020, environ trois fois la variabilité "
    "interannuelle), absent des autres sources ; valeurs 2021-2023 à interpréter avec "
    "prudence (ADR-0018)."
)


def codes_series_era5() -> list[str]:
    """Codes des séries ERA5 brutes et des écarts ERA5 − NASA, aux 142 localités."""
    localites = [code for code, _, _, _ in points_nationaux()]
    brutes = [c.code_serie(loc) for c in CONTRATS_ERA5.values() for loc in localites]
    ecarts = [
        e.code_serie(loc)
        for e in ECARTS_INTER_SOURCES
        if e.source_comparee == "era5_pvgis"
        for loc in localites
    ]
    return brutes + ecarts


def upgrade() -> None:
    bind = op.get_bind()
    codes = codes_series_era5()
    if len(codes) != NB_SERIES_ATTENDU:
        raise RuntimeError(f"Migration 0033 : {len(codes)} séries, {NB_SERIES_ATTENDU} attendues.")
    n = bind.execute(
        sa.text(
            """
            UPDATE series_metadonnees SET note_publique = note_publique || :caveat
            WHERE code = ANY(:c) AND strpos(note_publique, :caveat) = 0
            """
        ),
        {"caveat": CAVEAT, "c": codes},
    ).rowcount
    if n != NB_SERIES_ATTENDU:
        raise RuntimeError(f"Migration 0033 : {n} séries annotées, {NB_SERIES_ATTENDU} attendues.")


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE series_metadonnees
            SET note_publique = left(note_publique, length(note_publique) - length(:caveat))
            WHERE code = ANY(:c) AND right(note_publique, length(:caveat)) = :caveat
            """
        ),
        {"caveat": CAVEAT, "c": codes_series_era5()},
    )
