"""Modèle SQLAlchemy de la table ``audit_log``.

Reflet ORM de la table créée par la migration 005
(``migrations/versions/2026_05_04_1700_creer_table_audit_log.py``).

Cette table est conçue pour être consultée en lecture seule depuis
l'applicatif. Les écritures sont effectuées exclusivement par la
fonction PL/pgSQL ``kuma_log_audit()``, déclenchée par les triggers
``trg_audit_*`` posés sur les tables auditées (voir
``docs/architecture/03-audit.md``). Aucun code applicatif Python ne
doit faire d'``INSERT`` / ``UPDATE`` / ``DELETE`` sur cette table.

Le modèle est néanmoins déclaré pour deux raisons :

1. Permettre à ``alembic check`` de valider que la définition ORM
   reste alignée avec la migration de référence.
2. Préparer les futurs endpoints administratifs de consultation de
   l'historique, qui utiliseront ce modèle en lecture seule.

Conventions de stockage (``id_ligne_auditee TEXT`` plutôt que
``BIGINT``, ``type_operation CHAR(1)``, ``horodatage`` via
``clock_timestamp()`` plutôt que ``now()``…) sont justifiées dans la
docstring de la migration 005.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    DateTime,
    Identity,
    Index,
    Text,
    desc,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from kuma_data_core.db.base import Base


class AuditLog(Base):
    """Journal d'audit centralisé de Kuma Data Core (lecture seule)."""

    __tablename__ = "audit_log"

    # === Identifiants ===
    id: Mapped[int] = mapped_column(BigInteger, Identity(start=1, increment=1), primary_key=True)

    # === Identification de la modification ===
    table_auditee: Mapped[str] = mapped_column(Text, nullable=False)
    schema_audite: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'public'")
    )
    type_operation: Mapped[str] = mapped_column(CHAR(length=1), nullable=False)
    id_ligne_auditee: Mapped[str] = mapped_column(Text, nullable=False)

    # === Contenu de la modification (granularité hybride) ===
    champs_modifies: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    valeurs_avant: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    valeurs_apres: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # === Identification de l'auteur (combinaison) ===
    utilisateur_pg: Mapped[str] = mapped_column(Text, nullable=False)
    auteur_applicatif: Mapped[str | None] = mapped_column(Text, nullable=True)
    adresse_client: Mapped[str | None] = mapped_column(INET, nullable=True)

    # === Horodatage ===
    # clock_timestamp() (instant réel) et non now() (début de
    # transaction). Cf. migration 005 et docs/architecture/03-audit.md.
    horodatage: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    )

    # === Contraintes et index ===
    # Les noms exacts (CheckConstraint, Index) sont strictement alignés
    # sur ceux de la migration 005 pour qu'``alembic check`` reste vert.
    # Le tri DESC sur ``horodatage`` reflète l'usage dominant des
    # requêtes : « événements les plus récents en premier ».
    __table_args__ = (
        CheckConstraint(
            "type_operation IN ('I', 'U', 'D')",
            name="ck_audit_log_type_operation",
        ),
        Index(
            "idx_audit_log_table_horodatage",
            "schema_audite",
            "table_auditee",
            desc("horodatage"),
        ),
        Index("idx_audit_log_horodatage", desc("horodatage")),
        Index(
            "idx_audit_log_utilisateur_pg",
            "utilisateur_pg",
            desc("horodatage"),
        ),
        Index(
            "idx_audit_log_auteur_applicatif",
            "auteur_applicatif",
            desc("horodatage"),
            postgresql_where=text("auteur_applicatif IS NOT NULL"),
        ),
        Index(
            "idx_audit_log_ligne",
            "schema_audite",
            "table_auditee",
            "id_ligne_auditee",
            desc("horodatage"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog(id={self.id}, table={self.table_auditee!r}, "
            f"op={self.type_operation!r}, ligne={self.id_ligne_auditee!r})>"
        )
