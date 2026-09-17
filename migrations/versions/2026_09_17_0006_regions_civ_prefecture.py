"""regions_civ_prefecture

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-17

Seed des 31 régions de Côte d'Ivoire au niveau générique ``prefecture``
(cf. ADR-0005 : le niveau ``prefecture`` porte la région ivoirienne ;
``type_localite`` est un axe technique, l'identité est dans ``nom`` /
``notes``).

Chaque région est rattachée à son **district parent** (relation Wikidata
``P131``) ; le ``parent_id`` est résolu depuis les districts déjà posés par
la migration 0003 (``region_administrative``). Coordonnées Wikidata
(``P625``), population RGPH 2021 (INS) dont la somme par district reproduit
exactement le total du district densifié (migration 0004).

Pattern identique aux seeds de localités : ``op.bulk_insert`` unique (les 31
régions partagent le même niveau), résolution Python ``parent_code ->
parent_id`` via bulk fetch, garde-fou ``RuntimeError`` si un district parent
est introuvable. Le trigger de validation hiérarchique (matrice parent-enfant
des 7 types : ``region_administrative`` -> ``prefecture`` autorisé) et le
trigger d'audit se déclenchent à l'INSERT ; ``cree_par`` reste NULL.

``downgrade`` supprime les 31 régions par leur ``code``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.localites_civ_seed_data import LOCALITES_SEED

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_REGIONS: tuple[dict[str, Any], ...] = tuple(
    e for e in LOCALITES_SEED if e["type_localite"] == "prefecture"
)
_CODES_REGIONS: tuple[str, ...] = tuple(e["code"] for e in _REGIONS)


def upgrade() -> None:
    bind = op.get_bind()

    localites_table = sa.table(
        "localites",
        sa.column("code", sa.String),
        sa.column("nom", sa.Text),
        sa.column("type_localite", sa.String),
        sa.column("parent_id", sa.BigInteger),
        sa.column("pays_iso3", sa.String),
        sa.column("latitude", sa.Numeric(11, 8)),
        sa.column("longitude", sa.Numeric(12, 8)),
        sa.column("altitude_metres", sa.Integer),
        sa.column("population_estimee", sa.Integer),
        sa.column("annee_population", sa.Integer),
        sa.column("fuseau_horaire", sa.String),
        sa.column("notes", sa.Text),
    )

    # Résolution parent_code (district) -> parent_id depuis les districts déjà posés.
    parent_codes = sorted({e["parent_code"] for e in _REGIONS})
    lignes = bind.execute(
        sa.text("SELECT code, id FROM localites WHERE code = ANY(:codes)"),
        {"codes": parent_codes},
    ).all()
    code_to_id: dict[str, int] = {row.code: row.id for row in lignes}

    manquants = [c for c in parent_codes if c not in code_to_id]
    if manquants:
        raise RuntimeError(
            f"Migration 0006 : district(s) parent(s) introuvable(s) pour le seed "
            f"des régions : {manquants!r}. La migration 0003 doit avoir posé les "
            f"14 districts au préalable."
        )

    payload: list[dict[str, Any]] = []
    for entry in _REGIONS:
        row = {k: v for k, v in entry.items() if k != "parent_code"}
        row["parent_id"] = code_to_id[entry["parent_code"]]
        payload.append(row)

    op.bulk_insert(localites_table, payload)


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM localites WHERE code = ANY(:codes)").bindparams(
            sa.bindparam("codes", value=list(_CODES_REGIONS))
        )
    )
