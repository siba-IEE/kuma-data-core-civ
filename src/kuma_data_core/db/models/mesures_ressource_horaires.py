"""Modèle SQLAlchemy de la table ``mesures_ressource_horaires``.

Table dédiée aux mesures ressource **horaires** ingérées depuis sources
externes. Pendant horaire de ``mesures_ressource`` (journalier strict)
et ``mesures_ressource_mensuelles`` (mensuel).

Identité métier : 2-uplet ``(serie_id, instant_mesure)`` avec
``instant_mesure TIMESTAMPTZ`` (UTC), versioning temporel
``tstzrange(valide_du, valide_au)`` + EXCLUDE BTree-GiST. Le choix UTC
(plutôt qu'un instant naïf LST) est dicté par le contrôle qualité
horaire qui calcule la position solaire (angle zénithal) sans
ambiguïté de fuseau.

Superpose les 4 mécaniques structurantes :

- Statut éditorial 5 valeurs.
- Versioning temporel ``valide_du``/``valide_au`` TIMESTAMPTZ + EXCLUDE
  BTree-GiST.
- Niveau de confiance A/B/C dérivé + override éditorial.
- Identité métier 2-uplet via ``serie_id``.

Helper SQLAlchemy :

- ``@hybrid_property niveau_effectif`` : renvoie l'override si non NULL,
  sinon le dérive (cohérent avec ``mesures_ressource`` et
  ``mesures_ressource_mensuelles``).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kuma_data_core.db.base import Base
from kuma_data_core.db.models.series_metadonnees import SerieMetadonnees


class MesureRessourceHoraire(Base):
    """Mesure horaire d'une grandeur brute ingérée depuis une source externe."""

    __tablename__ = "mesures_ressource_horaires"

    # === Identifiant ===
    id: Mapped[int] = mapped_column(BigInteger, Identity(start=1, increment=1), primary_key=True)

    # === Identité métier (2-uplet serie_id + instant_mesure) ===
    serie_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "series_metadonnees.id",
            name="fk_mesures_ressource_horaires_serie_id__series_metadonnees",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    instant_mesure: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # === Valeur ===
    valeur: Mapped[float] = mapped_column(Float(precision=53), nullable=False)

    # === Versioning temporel ===
    valide_du: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    valide_au: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # === Statut éditorial ===
    statut: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'brut'"),
    )

    # === Niveau de confiance ===
    niveau_confiance_derive: Mapped[str] = mapped_column(String(1), nullable=False)
    niveau_confiance_override: Mapped[str | None] = mapped_column(String(1), nullable=True)

    # === Commentaire éditorial ===
    commentaire_editorial: Mapped[str | None] = mapped_column(Text, nullable=True)

    # === Audit applicatif ===
    cree_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    cree_par: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "contributeurs.id",
            name="fk_mesures_ressource_horaires_cree_par__contributeurs",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    modifie_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    modifie_par: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "contributeurs.id",
            name="fk_mesures_ressource_horaires_modifie_par__contributeurs",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    # === Relations ===
    serie: Mapped[SerieMetadonnees] = relationship(
        SerieMetadonnees,
        lazy="select",
        foreign_keys=[serie_id],
    )

    # === Hybrid properties ===
    @hybrid_property
    def niveau_effectif(self) -> str:
        """Renvoie ``niveau_confiance_override`` si non NULL, sinon ``niveau_confiance_derive``."""
        return (
            self.niveau_confiance_override
            if self.niveau_confiance_override is not None
            else self.niveau_confiance_derive
        )

    # === Contraintes et index ===
    # Note : la contrainte EXCLUDE BTree-GiST et le trigger d'audit sont
    # posés en migration (053) et non déclarés ici - cohérent avec
    # mesures_ressource_mensuelles (Alembic ne compare pas les EXCLUDE).
    __table_args__ = (
        CheckConstraint(
            "statut IN ('brut', 'valide_auto', 'valide_humain', 'publie', 'deprecie')",
            name="ck_mesures_ressource_horaires_statut_valide",
        ),
        CheckConstraint(
            "niveau_confiance_derive IN ('A', 'B', 'C')",
            name="ck_mesures_ressource_horaires_niveau_confiance_derive_valide",
        ),
        CheckConstraint(
            "niveau_confiance_override IS NULL OR niveau_confiance_override IN ('A', 'B', 'C')",
            name="ck_mesures_ressource_horaires_niveau_confiance_override_valide",
        ),
        CheckConstraint(
            "valide_au IS NULL OR valide_au > valide_du",
            name="ck_mesures_ressource_horaires_periode_coherente",
        ),
        # Index partiel sur lignes courantes (usage dominant en lecture).
        Index(
            "idx_mesures_ressource_horaires_courantes",
            "serie_id",
            "instant_mesure",
            postgresql_where=text("valide_au IS NULL"),
        ),
        {
            "comment": (
                "Mesures horaires ingerees depuis sources externes (NASA POWER, "
                "Vague 3). Pendant horaire de mesures_ressource (journalier) et "
                "mesures_ressource_mensuelles (mensuel). instant_mesure en "
                "TIMESTAMPTZ (UTC) pour le controle qualite horaire (position "
                "solaire sans ambiguite de fuseau). Versioning temporel par "
                "(valide_du, valide_au) + EXCLUDE BTree-GiST sur identite metier "
                "(serie_id, instant_mesure). Statut editorial et niveau de "
                "confiance derive/override par couche service editoriale."
            ),
        },
    )

    def __repr__(self) -> str:
        return (
            f"<MesureRessourceHoraire(id={self.id}, serie_id={self.serie_id}, "
            f"instant_mesure={self.instant_mesure!r}, valeur={self.valeur})>"
        )
