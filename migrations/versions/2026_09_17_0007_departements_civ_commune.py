"""departements_civ_commune

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-17

Seed des 111 départements de Côte d'Ivoire au niveau générique ``commune``
(cf. ADR-0005). 108 sont rattachés à une région (``prefecture``) et 3 aux
districts autonomes d'Abidjan et de Yamoussoukro (``commune`` ->
``region_administrative``, autorisé par la matrice hiérarchique, cas
« Conakry »). Le ``parent_id`` est résolu depuis les régions posées par la
migration 0006 et les districts posés par la migration 0003.

Coordonnées Wikidata ``P625`` (règle de rang ADR-0006 ; Attiégouakro, sans
``P625`` propre, porte la coordonnée de son chef-lieu). **Population RGPH 2021**
(INS Côte d'Ivoire, via ``data.gouv.ci`` / ``citypopulation.de``) : chaque
département porte sa population de recensement 2021 ; la somme par région
reproduit le total régional déjà gravé (écart ≤ 1 hab) et le total national
vaut 29 389 150 (chiffre officiel exact). Les valeurs proviennent de
``LOCALITES_SEED`` (source unique) ; ``op.bulk_insert`` les insère telles
quelles.

Pattern identique aux seeds de localités : ``op.bulk_insert`` unique,
résolution Python ``parent_code -> parent_id`` via bulk fetch, garde-fou
``RuntimeError`` si un parent est introuvable. Trigger de validation
hiérarchique et trigger d'audit se déclenchent à l'INSERT.

``downgrade`` supprime les 111 départements par leur ``code``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.localites_civ_seed_data import LOCALITES_SEED

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DEPARTEMENTS: tuple[dict[str, Any], ...] = tuple(
    e for e in LOCALITES_SEED if e["type_localite"] == "commune"
)
_CODES_DEPARTEMENTS: tuple[str, ...] = tuple(e["code"] for e in _DEPARTEMENTS)


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

    parent_codes = sorted({e["parent_code"] for e in _DEPARTEMENTS})
    lignes = bind.execute(
        sa.text("SELECT code, id FROM localites WHERE code = ANY(:codes)"),
        {"codes": parent_codes},
    ).all()
    code_to_id: dict[str, int] = {row.code: row.id for row in lignes}

    manquants = [c for c in parent_codes if c not in code_to_id]
    if manquants:
        raise RuntimeError(
            f"Migration 0007 : parent(s) introuvable(s) pour le seed des départements : "
            f"{manquants!r}. Les migrations 0003 (districts) et 0006 (régions) doivent "
            f"avoir été appliquées au préalable."
        )

    payload: list[dict[str, Any]] = []
    for entry in _DEPARTEMENTS:
        row = {k: v for k, v in entry.items() if k != "parent_code"}
        row["parent_id"] = code_to_id[entry["parent_code"]]
        payload.append(row)

    op.bulk_insert(localites_table, payload)


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM localites WHERE code = ANY(:codes)").bindparams(
            sa.bindparam("codes", value=list(_CODES_DEPARTEMENTS))
        )
    )
