"""Modèle SQLAlchemy de la table ``grandeurs_referentiel``.

Référentiel statique des grandeurs solaires/climatiques traduites par
Kuma (15 entrées prévues). Cité en aval par
``series_metadonnees.grandeur_code``,
``mesures_ressource.grandeur_code`` et
``grandeurs_metier.grandeur_code`` via la clé naturelle
``code`` (``UNIQUE NOT NULL``).

PK ``id BIGINT IDENTITY`` + clé naturelle ``code`` : la fonction
d'audit ``kuma_log_audit()`` (migration 005) suppose une colonne
``id`` sur les tables auditées (cf. ``docs/conventions/01-naming.md``
§*Audit et convention de PK pour les tables auditées*).

Constantes ``FAMILLES_AUTORISEES`` et ``STRATEGIES_CALCUL_AUTORISEES``
non encore consommées. Préparées pour la validation applicative
(cf. ``docs/conventions/01-naming.md`` §*Catégoriels et listes
fermées*).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from kuma_data_core.db.base import Base

FAMILLES_AUTORISEES: frozenset[str] = frozenset({"F1", "F2"})
STRATEGIES_CALCUL_AUTORISEES: frozenset[str] = frozenset({"stockee", "calculee_volee"})


class GrandeurReferentiel(Base):
    """Référentiel statique des grandeurs traduites Kuma."""

    __tablename__ = "grandeurs_referentiel"

    # === Identifiants ===
    id: Mapped[int] = mapped_column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    code: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        unique=True,
        comment=(
            "Cle naturelle metier (ASCII pur, snake_case, citee par les FK aval). "
            "Cf. 01-naming.md section Codes metier des referentiels."
        ),
    )

    # === Métier ===
    libelle: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Titre humain de la grandeur (accents et casse normale autorises).",
    )
    unite_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "unites.id",
            name="fk_grandeurs_referentiel_unite_id__unites",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    famille: Mapped[str] = mapped_column(
        String(2),
        nullable=False,
        comment=(
            "F1 : grandeur ontologique (mesuree ou derivee simple). "
            "F2 : grandeur parametree (calcul necessitant des parametres utilisateur)."
        ),
    )
    strategie_calcul: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment=(
            "stockee : valeur persistee dans grandeurs_metier. "
            "calculee_volee : recalculee a chaque consultation, dependante du perimetre."
        ),
    )
    methode_calcul_doc: Mapped[str | None] = mapped_column(Text, nullable=True)
    version_formule_actuelle: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
        comment=(
            "Compteur applicatif de la formule en vigueur. "
            "Incremente a chaque revision methodologique. Initial : 1."
        ),
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # === Soft delete ===
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    desactive_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # === Audit applicatif ===
    cree_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    cree_par: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "contributeurs.id",
            name="fk_grandeurs_referentiel_cree_par__contributeurs",
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
            name="fk_grandeurs_referentiel_modifie_par__contributeurs",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    # === Contraintes et index ===
    __table_args__ = (
        CheckConstraint(
            "famille IN ('F1', 'F2')",
            name="ck_grandeurs_referentiel_famille_valide",
        ),
        CheckConstraint(
            "strategie_calcul IN ('stockee', 'calculee_volee')",
            name="ck_grandeurs_referentiel_strategie_calcul_valide",
        ),
        CheckConstraint(
            "version_formule_actuelle >= 1",
            name="ck_grandeurs_referentiel_version_formule_positive",
        ),
        CheckConstraint(
            "(actif = TRUE AND desactive_le IS NULL) "
            "OR (actif = FALSE AND desactive_le IS NOT NULL)",
            name="ck_grandeurs_referentiel_actif_desactive_coherent",
        ),
        Index("idx_grandeurs_referentiel_actif", "actif"),
        # Commentaire de table porté sur l'ORM pour cohérence avec la
        # migration 007 (alembic check). Le dict doit être le dernier
        # élément du tuple __table_args__ selon la convention SQLAlchemy.
        {
            "comment": (
                "Referentiel des grandeurs Kuma. 15 grandeurs traduites (1-1C) + "
                "5 grandeurs brutes ingerees (1-2b) = 20 entrees post-1-2b. "
                "Le lieu de stockage physique d'une F1 stockee est determine par "
                "series_metadonnees.methode_collecte (cadrage Q7 v1.3)."
            ),
        },
    )

    def __repr__(self) -> str:
        return f"<GrandeurReferentiel(code={self.code!r}, famille={self.famille!r})>"
