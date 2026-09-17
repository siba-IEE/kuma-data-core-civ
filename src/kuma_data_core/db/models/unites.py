"""Modèle SQLAlchemy de la table ``unites``.

Référentiel des unités de mesure utilisées dans Kuma Data Core. Couvre
30 grandeurs physiques, économiques et environnementales, avec 153
unités validées contre plus de 20 organismes normatifs internationaux
(BIPM, AIE, ONU, NIST, IUPAC, IEC, DIN, ISO, IPCC, IRENA, UNECE, etc.).

Choix de précision (``Numeric(60, 30)`` pour les facteurs/décalages) :
-----------------------------------------------------------------------
La grandeur ``energie`` inclut les électronvolts dont les facteurs de
conversion vers le joule sont extrêmement petits :
``electronvolt = 1.602176634e-19``,
``kilo_electronvolt = 1.602176634e-16``,
``mega_electronvolt = 1.602176634e-13``.

Avec ``Numeric(30, 15)`` (15 décimales), ces valeurs seraient tronquées
à 0 (eV, keV) ou perdraient 10 chiffres significatifs (MeV). À l'autre
extrême, ``quad = 1.05505585262e18`` exige au moins 19 chiffres avant
la virgule.

``Numeric(60, 30)`` (30 chiffres avant la virgule + 30 après) couvre
sans perte les deux extrêmes, tout en préservant la précision décimale
exacte (par opposition à ``DOUBLE PRECISION`` qui introduirait des
erreurs binaires IEEE 754 incompatibles avec l'exigence métrologique
de Kuma : 1 atm = 101 325 Pa exactement, 1 cal_IT = 4,1868 J
exactement, année grégorienne moyenne = 365,2425 j exactement).

Conventions pragmatiques adoptées (voir migration 002 pour détails) :
- intensite_carbone : référence interne en gCO2/kWh (pas kg/J)
- irradiation_solaire : référence interne en MJ/m²/jour
- pouvoir_calorifique : convention PCI par défaut
- devises économiques : Stratégie B (pas de conversion automatique)
- GNF prioritaire dans l'ordre du seed (signal éditorial Kuma)
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from kuma_data_core.db.base import Base


class Unite(Base):
    """Référentiel des unités de mesure de Kuma Data Core."""

    __tablename__ = "unites"

    # === Identifiants ===
    id: Mapped[int] = mapped_column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)

    # === Métier ===
    libelle: Mapped[str] = mapped_column(Text, nullable=False)
    symbole: Mapped[str] = mapped_column(String(50), nullable=False)
    grandeur: Mapped[str] = mapped_column(String(100), nullable=False)
    systeme: Mapped[str] = mapped_column(String(20), nullable=False)
    est_unite_de_base: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )

    # === Conversion vers l'unité de référence interne (souvent SI) ===
    # Formule : valeur_ref = valeur × facteur + decalage
    # Numeric(60, 30) - voir docstring du module pour la justification.
    facteur_conversion_si: Mapped[Decimal] = mapped_column(
        Numeric(60, 30), nullable=False, server_default=text("1")
    )
    decalage_conversion_si: Mapped[Decimal] = mapped_column(
        Numeric(60, 30), nullable=False, server_default=text("0")
    )
    code_unite_si: Mapped[str] = mapped_column(String(80), nullable=False)

    # === Notes éditoriales ===
    note_methodologique: Mapped[str | None] = mapped_column(Text, nullable=True)
    contexte_usage: Mapped[str | None] = mapped_column(Text, nullable=True)
    references_normatives: Mapped[list[str] | None] = mapped_column(ARRAY(Text()), nullable=True)

    # === Soft delete ===
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    desactive_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # === Audit applicatif ===
    cree_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    cree_par: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("contributeurs.id", name="fk_unites_cree_par__contributeurs"),
        nullable=True,
    )
    modifie_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    modifie_par: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("contributeurs.id", name="fk_unites_modifie_par__contributeurs"),
        nullable=True,
    )

    # === Contraintes et index ===
    __table_args__ = (
        CheckConstraint(
            "systeme IN ('SI', 'non_SI_acceptee', 'composee_mixte', 'imperial', 'autre')",
            name="ck_unites_systeme_valide",
        ),
        CheckConstraint(
            "(est_unite_de_base = TRUE AND systeme = 'SI') OR (est_unite_de_base = FALSE)",
            name="ck_unites_base_coherence_systeme",
        ),
        CheckConstraint(
            "(actif = TRUE AND desactive_le IS NULL) "
            "OR (actif = FALSE AND desactive_le IS NOT NULL)",
            name="ck_unites_actif_desactive_le",
        ),
        Index("idx_unites_actif", "actif"),
        Index("idx_unites_grandeur", "grandeur"),
        Index("idx_unites_systeme", "systeme"),
        Index(
            "idx_unites_est_unite_de_base",
            "est_unite_de_base",
            postgresql_where=text("est_unite_de_base = TRUE"),
        ),
        Index("idx_unites_code_unite_si", "code_unite_si"),
        # Commentaire de table porté sur l'ORM pour cohérence avec la
        # migration 002 (alembic check). Le dict doit être le dernier
        # élément du tuple __table_args__ selon la convention SQLAlchemy.
        {
            "comment": (
                "Référentiel des unités de mesure de Kuma Data Core. "
                "153 unités sur 30 grandeurs, validées contre 20+ organismes "
                "normatifs internationaux (BIPM, AIE, ONU, NIST, IUPAC, IEC, "
                "DIN, ISO, IPCC, IRENA, UNECE, etc.)."
            ),
        },
    )

    def __repr__(self) -> str:
        return f"<Unite(code={self.code!r}, symbole={self.symbole!r})>"
