"""Modèle SQLAlchemy de la table ``calage_couverture``.

Domaine de couverture d'un référentiel de calage (ADR-0004,
complément couverture progressive) : la liste des localités du
référentiel qualifiées pour le transport du calage, une ligne par
localité couverte.

C'est la donnée qui pilote la couverture géographique des logiciels
consommateurs (Solar Bridge en tête) : une étude calée n'est permise
que si la localité résolue pour le site appartient au domaine.
Étendre la couverture = ajouter des lignes (qualification par la
recherche : cohérence inter-source, campagnes de mesure,
leave-one-out quand une deuxième station sol existera) et publier
une édition - zéro code côté consommateurs.

Le lien vers ``referentiels_calage`` est logique, par ``referentiel_code``
(le code y est partagé par les lignes de saisons, il n'est pas une
clé unique) ; l'intégrité est tenue par les seeds de migration.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from kuma_data_core.db.base import Base


class CalageCouverture(Base):
    """Une localité qualifiée pour le transport d'un référentiel de calage."""

    __tablename__ = "calage_couverture"

    # === Identifiants ===
    id: Mapped[int] = mapped_column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    referentiel_code: Mapped[str] = mapped_column(String(120), nullable=False)
    localite_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("localites.id", name="fk_calage_couverture_localite__localites"),
        nullable=False,
    )

    # === Provenance de la qualification (jamais un perimetre nu) ===
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'v1'"))

    # === Soft delete ===
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))

    # === Audit applicatif ===
    cree_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    modifie_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "referentiel_code",
            "localite_id",
            "version",
            name="uq_calage_couverture_referentiel_localite_version",
        ),
        Index("idx_calage_couverture_referentiel", "referentiel_code"),
        Index("idx_calage_couverture_actif", "actif"),
        {
            "comment": (
                "Domaine de couverture des referentiels de calage : "
                "localites qualifiees pour le transport, avec justification. "
                "Pilote la couverture geographique des consommateurs "
                "(ADR-0004, couverture progressive)."
            ),
        },
    )

    def __repr__(self) -> str:
        return (
            f"<CalageCouverture(referentiel={self.referentiel_code!r}, "
            f"localite_id={self.localite_id!r})>"
        )
