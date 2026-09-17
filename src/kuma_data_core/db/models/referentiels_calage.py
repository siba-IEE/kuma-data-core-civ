"""Modèle SQLAlchemy de la table ``referentiels_calage``.

Référentiel de calage satellite/sol : les biais saisonniers mesurés
aux stations de référence, publiés comme donnée éditoriale de
l'édition (ADR-0004). Une ligne par (station, grandeur, saison).

Pourquoi une table et non une grandeur calculée à la volée : les
biais sont des RÉSULTATS de recherche, produits par des analyses
documentées (notes ``docs/methodologie/calage-*-terrain-lite.md``,
scripts reproductibles) sur des appariements horaires sol/satellite
dont les lignes satellite ne sont plus stockées en base. L'édition
publie le résultat avec sa provenance ; le recalcul appartient à la
chaîne de recherche, pas au serveur public (doctrine D6 : le VPS ne
détient et ne calcule que du reconstructible).

Consommateur type : Solar Bridge applique ``k = 1 / (1 + biais)`` à
la climatologie du site étudié (méthode d'étude mini-réseau v1),
avec statut « transporté » affiché dans le tableau des hypothèses.
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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from kuma_data_core.db.base import Base


class ReferentielCalage(Base):
    """Biais saisonnier satellite/sol d'une station de référence."""

    __tablename__ = "referentiels_calage"

    # === Identifiants ===
    id: Mapped[int] = mapped_column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    code: Mapped[str] = mapped_column(String(120), nullable=False)

    # === Métier ===
    localite_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("localites.id", name="fk_referentiels_calage_localite__localites"),
        nullable=False,
    )
    grandeur_code: Mapped[str] = mapped_column(String(50), nullable=False)
    saison: Mapped[str] = mapped_column(String(40), nullable=False)
    mois: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False)
    # Biais relatif moyen satellite moins sol (0.044 pour +4,4 %).
    # Le facteur de calage k = 1/(1+biais) est derive, jamais stocke.
    biais: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)

    # Serie sol de fondation du referentiel (machine-lisible) : la
    # sequence horaire de reference que les consommateurs d'etude
    # doivent utiliser avec ce calage. Decouverte par l'API, jamais
    # une constante cote consommateur (genericite pays, residu 3).
    serie_sol: Mapped[str] = mapped_column(String(120), nullable=False)

    # === Provenance et portée (traçabilité, jamais un nombre nu) ===
    provenance: Mapped[str] = mapped_column(Text, nullable=False)
    portee: Mapped[str] = mapped_column(Text, nullable=False)
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
            "localite_id",
            "grandeur_code",
            "saison",
            "version",
            name="uq_referentiels_calage_station_grandeur_saison_version",
        ),
        CheckConstraint("biais > -1", name="ck_referentiels_calage_biais_definissable"),
        Index("idx_referentiels_calage_localite_grandeur", "localite_id", "grandeur_code"),
        Index("idx_referentiels_calage_actif", "actif"),
        {
            "comment": (
                "Referentiel de calage satellite/sol : biais saisonniers "
                "mesures aux stations de reference, publies avec provenance "
                "et portee de transport (ADR-0004)."
            ),
        },
    )

    def __repr__(self) -> str:
        return f"<ReferentielCalage(code={self.code!r}, saison={self.saison!r})>"
