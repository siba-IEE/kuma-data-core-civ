"""densification_pays_civ

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-17

Densification sourcée du pays ``civ`` (Côte d'Ivoire).

La migration 0003 a posé le pays avec coordonnées et population différées à
``NULL``. Cette migration renseigne, par ``UPDATE`` ciblé sur le ``code`` :

- ``latitude`` / ``longitude`` : centroïde (point représentatif) de l'entité
  pays sur Wikidata (Q1008, propriété ``P625``, rang normal) ;
- ``population_estimee`` / ``annee_population`` (= 2021) : population nationale
  du **RGPH 2021** (INS Côte d'Ivoire), 29 389 150 hab. Ce chiffre officiel
  n'est pas présent dans Wikidata (``P1082`` s'arrête à 2017 puis saute à
  2023) ; il est recoupé par la somme des 14 districts densifiés (migration
  0004 : 29 389 152, écart d'arrondi +2).

La valeur provient de ``LOCALITES_SEED`` (même source que le seed 0003 lit
pour les installations neuves) : sur base neuve l'``UPDATE`` est idempotent,
sur base ayant appliqué 0003 avant densification il applique le delta.
``altitude_metres`` reste ``NULL`` (un pays n'a pas d'altitude ponctuelle).

``downgrade`` restaure l'état antérieur : coordonnées et population à ``NULL``
et la note « à densifier » d'origine.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.localites_civ_seed_data import LOCALITES_SEED

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Entrée pays (source unique de vérité : le seed).
_CIV: dict[str, Any] = next(e for e in LOCALITES_SEED if e["code"] == "civ")

# Note « à densifier » d'origine (migration 0003), pour restaurer l'état exact.
_NOTE_CIV_ORIGINE: str = (
    "Code ISO 3166-1 alpha-3 : CIV. Capitale politique : Yamoussoukro ; "
    "capitale économique : Abidjan. Fuseau UTC+00:00 (Africa/Abidjan). "
    "Centroïde et population nationale (RGPH 2021 : 29 389 150 hab.) à "
    "densifier en passe ultérieure. Aucune coordonnée n'est inventée hors-ligne."
)


def upgrade() -> None:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            """
            UPDATE localites
            SET latitude = :latitude,
                longitude = :longitude,
                population_estimee = :population_estimee,
                annee_population = :annee_population,
                notes = :notes
            WHERE code = 'civ'
            """
        ),
        {
            "latitude": _CIV["latitude"],
            "longitude": _CIV["longitude"],
            "population_estimee": _CIV["population_estimee"],
            "annee_population": _CIV["annee_population"],
            "notes": _CIV["notes"],
        },
    )
    if result.rowcount != 1:
        raise RuntimeError(
            f"Migration 0005 : pays 'civ' introuvable lors de la densification "
            f"(rowcount={result.rowcount}). La migration 0003 doit l'avoir posé."
        )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            UPDATE localites
            SET latitude = NULL,
                longitude = NULL,
                population_estimee = NULL,
                annee_population = NULL,
                notes = :notes
            WHERE code = 'civ'
            """
        ),
        {"notes": _NOTE_CIV_ORIGINE},
    )
