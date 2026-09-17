"""Modèle SQLAlchemy de la table ``mesures_ressource_mensuelles``.

Table dédiée aux mesures ressource **mensuelles** ingérées depuis sources
externes. Pendant symétrique de ``mesures_ressource``
(strictement journalier) pour la granularité mensuelle -
préservation stricte de « journalier comme produit éditorial fini ».

Identité métier : 3-uplet ``(serie_id, annee, mois)`` avec versioning
temporel ``tstzrange(valide_du, valide_au)`` + EXCLUDE BTree-GiST.
Séparation explicite ``annee SMALLINT`` + ``mois SMALLINT`` (cohérent
avec ``grandeurs_metier`` qui sépare ``annee_debut/annee_fin/mois``)
plutôt que ``periode_debut DATE`` au 1er du mois (qui introduirait une
ambiguïté sémantique pour le consommateur SQL/API).

Superpose les 4 mécaniques structurantes :

- Statut éditorial 5 valeurs.
- Versioning temporel ``valide_du``/``valide_au`` TIMESTAMPTZ +
  EXCLUDE BTree-GiST.
- Niveau de confiance A/B/C dérivé par règles R1-R4 + override éditorial
  avec justification obligatoire.
- Identité métier 3-uplet via ``serie_id`` (FK vers
  ``series_metadonnees`` qui porte le triplet ``localite_id,
  grandeur_code, source_id`` + ``methode_collecte``).

Helper SQLAlchemy :

- ``@hybrid_property niveau_effectif`` : renvoie l'override si non NULL,
  sinon le dérive (cohérent avec ``mesures_ressource`` et
  ``grandeurs_metier``).
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
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kuma_data_core.db.base import Base
from kuma_data_core.db.models.series_metadonnees import SerieMetadonnees


class MesureRessourceMensuelle(Base):
    """Mesure mensuelle d'une grandeur brute ingérée depuis une source externe."""

    __tablename__ = "mesures_ressource_mensuelles"

    # === Identifiant ===
    id: Mapped[int] = mapped_column(BigInteger, Identity(start=1, increment=1), primary_key=True)

    # === Identité métier (3-uplet serie_id + annee + mois) ===
    serie_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "series_metadonnees.id",
            name="fk_mesures_ressource_mensuelles_serie_id__series_metadonnees",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    annee: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    mois: Mapped[int] = mapped_column(SmallInteger, nullable=False)

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
            name="fk_mesures_ressource_mensuelles_cree_par__contributeurs",
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
            name="fk_mesures_ressource_mensuelles_modifie_par__contributeurs",
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
    __table_args__ = (
        CheckConstraint(
            "annee BETWEEN 1981 AND 2099",
            name="ck_mesures_ressource_mensuelles_annee_valide",
        ),
        CheckConstraint(
            "mois BETWEEN 1 AND 12",
            name="ck_mesures_ressource_mensuelles_mois_valide",
        ),
        CheckConstraint(
            "statut IN ('brut', 'valide_auto', 'valide_humain', 'publie', 'deprecie')",
            name="ck_mesures_ressource_mensuelles_statut_valide",
        ),
        CheckConstraint(
            "niveau_confiance_derive IN ('A', 'B', 'C')",
            name="ck_mesures_ressource_mensuelles_niveau_confiance_derive_valide",
        ),
        CheckConstraint(
            "niveau_confiance_override IS NULL OR niveau_confiance_override IN ('A', 'B', 'C')",
            name="ck_mesures_ressource_mensuelles_niveau_confiance_override_valide",
        ),
        CheckConstraint(
            "valide_au IS NULL OR valide_au > valide_du",
            name="ck_mesures_ressource_mensuelles_periode_coherente",
        ),
        # Index partiel sur lignes courantes (usage dominant en lecture)
        Index(
            "idx_mesures_ressource_mensuelles_courantes",
            "serie_id",
            "annee",
            "mois",
            postgresql_where=text("valide_au IS NULL"),
        ),
        {
            "comment": (
                "Mesures mensuelles ingerees depuis sources externes "
                "(SARAH-3 ICDR + NASA POWER 1991-2020, etape 1-7a). Pendant "
                "mensuel de mesures_ressource (journalier strict, cadrage "
                "Q2 phase 1). Versioning temporel par (valide_du, "
                "valide_au) + EXCLUDE BTree-GiST sur identite metier "
                "(serie_id, annee, mois). Statut editorial et niveau de "
                "confiance derive/override par couche service editoriale."
            ),
        },
    )

    def __repr__(self) -> str:
        return (
            f"<MesureRessourceMensuelle(id={self.id}, serie_id={self.serie_id}, "
            f"annee={self.annee}, mois={self.mois}, valeur={self.valeur})>"
        )
