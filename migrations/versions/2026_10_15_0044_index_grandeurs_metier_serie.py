"""index_grandeurs_metier_serie

Revision ID: 0044
Revises: 0043
Create Date: 2026-10-15

**Index de lecture des séries dérivées** (ADR-0029). L'API lit une série de
``grandeurs_metier`` par son identifiant de série (``/v1/series/{code}``), puis
compte ses lignes pour la pagination. Aucun index ne couvrait
``series_metadonnees_id`` : chaque lecture parcourait toute la table, qui dépasse
désormais le million de lignes (écarts, fraction diffuse, HEP, productible,
indice de clarté, variabilité, dégénérescence de pixel).

Index partiel sur les lignes courantes, dans l'ordre de lecture de l'API
(``annee_debut``, ``mois``), symétrique de ``idx_grandeurs_metier_courantes``.
Schéma seulement, aucune donnée modifiée.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0044"
down_revision: str | Sequence[str] | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "idx_grandeurs_metier_serie_courantes",
        "grandeurs_metier",
        ["series_metadonnees_id", "annee_debut", "mois"],
        unique=False,
        postgresql_where=sa.text("valide_au IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_grandeurs_metier_serie_courantes",
        table_name="grandeurs_metier",
        postgresql_where=sa.text("valide_au IS NULL"),
    )
