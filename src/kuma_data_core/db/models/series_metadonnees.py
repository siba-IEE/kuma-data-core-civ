"""Modèle SQLAlchemy de la table ``series_metadonnees``.

Référentiel éditorial des séries de mesures Kuma : pour un triplet
(localité, grandeur, source), stocke les métadonnées éditoriales
communes à toutes les mesures de cette série. Citée en aval par
``mesures_ressource`` via une FK ``serie_id``.

Pas de versioning temporel (cas d'usage vérifié), pas de statut
éditorial workflow (soft delete via ``actif``/``desactive_le``
suffit), pas de ``niveau_confiance`` à l'échelle série (la dérivation
R1-R4 vit à l'échelle mesure).

FK ``grandeur_code`` cite ``grandeurs_referentiel.code`` (colonne
UNIQUE non-PK). Premier usage du pattern dans le projet.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
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


class SerieMetadonnees(Base):
    """Métadonnées éditoriales d'une série de mesures Kuma."""

    __tablename__ = "series_metadonnees"

    # === Identifiants ===
    id: Mapped[int] = mapped_column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    code: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        unique=True,
        comment=(
            "Cle naturelle metier (ASCII pur, snake_case). "
            "Convention : <localite>_<grandeur>_<source>[_<periode>] "
            "ex. gin_conakry_hep_nasa_power_2010_2024."
        ),
    )
    libelle: Mapped[str] = mapped_column(Text, nullable=False)

    # === Identité métier (triplet localité x grandeur x source) ===
    localite_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "localites.id",
            name="fk_series_metadonnees_localite_id__localites",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    grandeur_code: Mapped[str] = mapped_column(
        String(80),
        ForeignKey(
            "grandeurs_referentiel.code",
            name="fk_series_metadonnees_grandeur_code__grandeurs_referentiel",
            ondelete="RESTRICT",
        ),
        nullable=False,
        comment=(
            "FK vers grandeurs_referentiel.code (colonne UNIQUE non-PK). "
            "Lisibilite metier prioritaire sur convention SQL classique."
        ),
    )
    source_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "sources.id",
            name="fk_series_metadonnees_source_id__sources",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    # === Période ===
    periode_debut: Mapped[date] = mapped_column(Date, nullable=False)
    periode_fin: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        comment=(
            "NULL si la serie est en cours (pas de fin annoncee). "
            "Sinon date de la derniere mesure attendue, >= periode_debut."
        ),
    )

    # === Granularité (discriminant de routage table-cible) ===
    granularite: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        comment=(
            "Discriminant de granularite temporelle pour le routage "
            "table-cible (journalier/mensuel/horaire). NULL pour les series "
            "kuma_calculs (routees par source vers grandeurs_metier ; "
            "temporalite portee par grandeurs_metier.periode_type). "
            "Resout D-36 (Vague 3 lot 1)."
        ),
    )

    # === Métadonnées éditoriales ===
    methode_collecte: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        comment=(
            "Methode dominante de collecte de la serie. "
            "Liste indicative des 6 valeurs en spec mecaniques-transverses sec. 6.4. "
            "CHECK formel pose en 1-2b."
        ),
    )
    methode_collecte_doc: Mapped[str | None] = mapped_column(Text, nullable=True)
    commentaire_editorial: Mapped[str | None] = mapped_column(Text, nullable=True)
    note_publique: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment=(
            "Passeport public de la série (servi par l'API sous l'alias "
            "notes_fr, affiché sur les fiches du site). Auto-portant : "
            "aucune référence de chantier interne. Toute nouvelle série "
            "doit le renseigner à l'insertion ; commentaire_editorial "
            "reste le journal interne, assaini à l'export d'édition."
        ),
    )
    url_documentation: Mapped[str | None] = mapped_column(Text, nullable=True)

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
            name="fk_series_metadonnees_cree_par__contributeurs",
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
            name="fk_series_metadonnees_modifie_par__contributeurs",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    # === Contraintes et index ===
    __table_args__ = (
        CheckConstraint(
            "periode_fin IS NULL OR periode_fin >= periode_debut",
            name="ck_series_metadonnees_periode_coherente",
        ),
        CheckConstraint(
            "granularite IS NULL OR granularite IN ('journalier', 'mensuel', 'horaire')",
            name="ck_series_metadonnees_granularite_valide",
        ),
        CheckConstraint(
            "(actif = TRUE AND desactive_le IS NULL) "
            "OR (actif = FALSE AND desactive_le IS NOT NULL)",
            name="ck_series_metadonnees_actif_desactive_coherent",
        ),
        # CHECK methode_collecte (migration 016) :
        # 6 valeurs anticipees par les mecaniques transverses.
        CheckConstraint(
            "methode_collecte IS NULL OR methode_collecte IN ("
            "'mesure_directe', 'modele_satellitaire', 'interpolation_geographique', "
            "'extrapolation_temporelle', 'calcul_derive', 'expertise_humaine')",
            name="ck_series_metadonnees_methode_collecte_valide",
        ),
        Index("idx_series_metadonnees_actif", "actif"),
        Index("idx_series_metadonnees_localite_id", "localite_id"),
        Index("idx_series_metadonnees_grandeur_code", "grandeur_code"),
        Index("idx_series_metadonnees_source_id", "source_id"),
        # Nommé explicitement : la naming_convention Kuma (cf. db/base.py)
        # utilise column_0_name, donc sans `name=` ne reprend que la
        # première colonne - ne reflèterait pas l'identité métier complète.
        UniqueConstraint(
            "localite_id",
            "grandeur_code",
            "source_id",
            "periode_debut",
            "periode_fin",
            "granularite",
            name="uq_series_metadonnees_identite_metier_plage_granularite",
        ),
        # Commentaire de table porté sur l'ORM pour cohérence avec la
        # migration 008 (alembic check). Le dict doit être le dernier
        # élément du tuple __table_args__ selon la convention SQLAlchemy.
        {
            "comment": (
                "Referentiel editorial des series de mesures Kuma. "
                "Une serie = un triplet (localite, grandeur, source) "
                "avec ses metadonnees editoriales communes."
            ),
        },
    )

    def __repr__(self) -> str:
        return f"<SerieMetadonnees(code={self.code!r}, grandeur={self.grandeur_code!r})>"
