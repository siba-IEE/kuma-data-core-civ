"""localites_civ_pays_districts

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-17

Seed des localités de Côte d'Ivoire (pays et districts) :

- 1 continent (Afrique, racine partagée)
- 1 pays (Côte d'Ivoire, ISO 3166-1 alpha-3 : CIV)
- 14 districts (12 districts + 2 districts autonomes : Abidjan et
  Yamoussoukro), niveau ``region_administrative``, nomenclature
  ISO 3166-2:CI.

Coordonnées, population et sourçage fin différés à une passe sourcée
(accès réseau requis) ; voir ``localites_civ_seed_data`` et
``docs/contribution/genericite-pays.md``.

Pattern identique à l'instance Guinée : ``op.bulk_insert`` par profondeur,
résolution Python ``parent_code -> parent_id`` via bulk fetch après chaque
batch, garde-fou ``RuntimeError`` si un ``parent_code`` est introuvable.
Le trigger d'audit et le trigger de validation hiérarchique se déclenchent
à l'INSERT ; ``auteur_applicatif`` reste NULL (pas de ``set_config``).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.localites_civ_seed_data import LOCALITES_SEED

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CODES_LOCALITES: tuple[str, ...] = tuple(entry["code"] for entry in LOCALITES_SEED)


def upgrade() -> None:
    bind = op.get_bind()
    code_to_id: dict[str, int] = {}

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

    def insert_batch(entries: list[dict[str, Any]]) -> None:
        payload: list[dict[str, Any]] = []
        for entry in entries:
            row = {k: v for k, v in entry.items() if k != "parent_code"}
            parent_code = entry.get("parent_code")
            if parent_code is None:
                row["parent_id"] = None
            else:
                if parent_code not in code_to_id:
                    raise RuntimeError(
                        f"Migration 0003 : parent_code introuvable lors du seed "
                        f"localites : {parent_code!r} (entite {entry['code']!r}). "
                        f"Verifier l'ordre topologique dans LOCALITES_SEED."
                    )
                row["parent_id"] = code_to_id[parent_code]
            payload.append(row)

        op.bulk_insert(localites_table, payload)

        codes_inseres = [entry["code"] for entry in entries]
        lignes = bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:codes)"),
            {"codes": codes_inseres},
        ).all()
        code_to_id.update({row.code: row.id for row in lignes})

    # Batch 1 - continent (parent_code None)
    insert_batch([e for e in LOCALITES_SEED if e["type_localite"] == "continent"])
    # Batch 2 - pays (parent_code 'afrique')
    insert_batch([e for e in LOCALITES_SEED if e["type_localite"] == "pays"])
    # Batch 3 - districts (region_administrative, parent_code 'civ')
    insert_batch([e for e in LOCALITES_SEED if e["type_localite"] == "region_administrative"])


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM localites WHERE code = ANY(:codes)").bindparams(
            sa.bindparam("codes", value=list(_CODES_LOCALITES))
        )
    )
