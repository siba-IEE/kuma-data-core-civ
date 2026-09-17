"""Modèle SQLAlchemy de la table ``mesures_ressource``.

Table métier opérationnelle. Stocke les mesures journalières des
données brutes ingérées depuis sources externes (NASA POWER ; ECMWF
ERA5, ANM Guinée, etc. en phases ultérieures).

Identité métier (Option D) : 2-uplet ``(serie_id, instant_mesure)`` via
FK vers ``series_metadonnees`` qui porte le triplet
``(localite_id, grandeur_code, source_id)``. ``instant_mesure DATE``
cohérent avec « journalier comme produit éditorial fini ».

Superpose 4 mécaniques structurantes :

- Statut éditorial 5 valeurs : ``brut``, ``valide_auto``,
  ``valide_humain``, ``publie``, ``deprecie``.
- Versioning temporel ``valide_du``/``valide_au`` TIMESTAMPTZ +
  EXCLUDE BTree-GiST.
- Niveau de confiance A/B/C dérivé par règles R1-R4 + override éditorial
  avec justification obligatoire.
- Identité métier 2-uplet via ``serie_id``.

Helper SQLAlchemy :

- ``@hybrid_property niveau_effectif`` : renvoie l'override si non NULL,
  sinon le dérive. Équivalent Python de la vue SQL
  ``v_mesures_avec_niveau_effectif`` créée en migration 018.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
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


class MesureRessource(Base):
    """Mesure journalière d'une grandeur brute ingérée depuis une source externe."""

    __tablename__ = "mesures_ressource"

    # === Identifiant ===
    id: Mapped[int] = mapped_column(BigInteger, Identity(start=1, increment=1), primary_key=True)

    # === Identité métier (Option D : 2-uplet serie_id + instant_mesure) ===
    serie_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "series_metadonnees.id",
            name="fk_mesures_ressource_serie_id__series_metadonnees",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    instant_mesure: Mapped[date] = mapped_column(Date, nullable=False)

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
        comment=(
            "Statut editorial Kuma : brut (importe non valide), valide_auto "
            "(controle qualite automatique passe), valide_humain (validation "
            "editoriale humaine), publie (publie publiquement), deprecie "
            "(retire du circuit editorial). Transitions encadrees par la "
            "couche service Python (cf. kuma_data_core.editorial.statuts)."
        ),
    )

    # === Niveau de confiance ===
    niveau_confiance_derive: Mapped[str] = mapped_column(
        String(1),
        nullable=False,
        comment=(
            "Niveau de confiance derive automatiquement par la couche service "
            "a partir des regles R1-R4 (cf. spec mecaniques-transverses-phase-1 "
            "sec. 6.4). A = haute, B = moyenne, C = basse. Recalcule a chaque "
            "modification de methode_collecte ou source_id de la serie."
        ),
    )
    niveau_confiance_override: Mapped[str | None] = mapped_column(
        String(1),
        nullable=True,
        comment=(
            "Override editorial du niveau derive. NULL = pas override (valeur "
            "effective = derive). Sinon valeur effective = override. Pose par "
            "la fonction service overrider_niveau_confiance avec justification "
            "obligatoire dans commentaire_editorial."
        ),
    )

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
            name="fk_mesures_ressource_cree_par__contributeurs",
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
            name="fk_mesures_ressource_modifie_par__contributeurs",
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

    # === Hybrid properties (helpers Python) ===
    @hybrid_property
    def niveau_effectif(self) -> str:
        """Renvoie ``niveau_confiance_override`` si non NULL, sinon ``niveau_confiance_derive``.

        Équivalent Python de la vue SQL ``v_mesures_avec_niveau_effectif``
        (à créer en migration 018). Permet aux callers d'obtenir le niveau
        consommable sans logique conditionnelle dispersée.
        """
        return (
            self.niveau_confiance_override
            if self.niveau_confiance_override is not None
            else self.niveau_confiance_derive
        )

    # === Contraintes et index ===
    __table_args__ = (
        CheckConstraint(
            "statut IN ('brut', 'valide_auto', 'valide_humain', 'publie', 'deprecie')",
            name="ck_mesures_ressource_statut_valide",
        ),
        CheckConstraint(
            "niveau_confiance_derive IN ('A', 'B', 'C')",
            name="ck_mesures_ressource_niveau_confiance_derive_valide",
        ),
        CheckConstraint(
            "niveau_confiance_override IS NULL OR niveau_confiance_override IN ('A', 'B', 'C')",
            name="ck_mesures_ressource_niveau_confiance_override_valide",
        ),
        CheckConstraint(
            "valide_au IS NULL OR valide_au > valide_du",
            name="ck_mesures_ressource_periode_coherente",
        ),
        # Index partiel sur lignes courantes (usage dominant en lecture)
        Index(
            "idx_mesures_ressource_courantes",
            "serie_id",
            "instant_mesure",
            postgresql_where=text("valide_au IS NULL"),
        ),
        # Commentaire de table porté sur l'ORM pour cohérence avec la
        # migration 014 (alembic check).
        {
            "comment": (
                "Mesures journalieres ingerees depuis sources externes. Premiere "
                "table metier operationnelle phase 1. Versioning temporel par "
                "(valide_du, valide_au) + EXCLUDE BTree-GiST sur identite metier "
                "(serie_id, instant_mesure). Statut editorial et niveau de "
                "confiance derive/override par couche service editoriale."
            ),
        },
    )

    def __repr__(self) -> str:
        return (
            f"<MesureRessource(id={self.id}, serie_id={self.serie_id}, "
            f"instant_mesure={self.instant_mesure!r}, valeur={self.valeur})>"
        )
