"""Modèle SQLAlchemy de la table ``localites``.

Référentiel des localités géographiques utilisées dans Kuma Data Core.
Couvre 7 niveaux hiérarchiques : ``continent``, ``region_supranationale``,
``pays``, ``region_administrative``, ``prefecture``, ``commune``, ``site``.

Validation hiérarchique en deux étages
--------------------------------------
* Migration 003 : CHECK simple - un ``continent`` ne peut pas avoir de
  ``parent_id`` (c'est une racine de la hiérarchie).
* Migration 084 (densification préfectorale) : trigger PL/pgSQL
  ``valider_hierarchie_localites()`` (``BEFORE INSERT OR UPDATE``,
  ``SECURITY DEFINER``) qui valide la matrice parent-enfant des 7 types.
  **Clôture la dette du trigger 007** (resté « à venir » de la 003 à la 083).
  Détection de boucles ``WITH RECURSIVE`` non incluse (différée : le seed
  n'a pas de cycle). Exception Conakry : ``commune.parent`` peut être une
  ``region_administrative`` (région spéciale sans préfecture).

Convention pour le ``code``
---------------------------
* ``continent`` / ``region_supranationale`` : slug ASCII
  (``afrique``, ``uemoa``).
* ``pays`` : code ISO 3166-1 alpha-3 en minuscule
  (``gin``, ``sen``, ``mar``).
* ``region_administrative`` / ``commune`` / ``site`` :
  ``<code_pays>_<slug>`` (``gin_conakry``, ``gin_souapiti``,
  ``mar_noor_ouarzazate``).

La cohérence stricte ``code='gin'`` ⇒ ``pays_iso3='GIN'`` n'est pas
contrainte en base (regex CHECK insuffisamment expressive). Validation
applicative.

Internationalisation différée
------------------------------
Le champ ``nom_local`` du brief v1 a été supprimé : Kuma publie
exclusivement en français. Si une i18n devient nécessaire, une table
``localites_traductions`` sera créée.

Précision géographique
----------------------
``Numeric(11, 8)`` pour la latitude, ``Numeric(12, 8)`` pour la
longitude. 8 décimales = 1 mm de précision à l'équateur (niveau
levés professionnels). Bornes vérifiées par CHECK
(``[-90, 90]`` / ``[-180, 180]``).

Format ``fuseau_horaire``
-------------------------
IANA Time Zone Database (par exemple ``Africa/Conakry``,
``Africa/Casablanca``, ``Europe/Paris``). Pas de CHECK : la liste
IANA évolue.

FK ``localite_id`` sur ``contributeurs``
----------------------------------------
Reportée en migration 005 dédiée. Une migration = un changement
logique : la 003 crée la table ``localites``, la 005 ajoutera la FK
inverse.
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
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from kuma_data_core.db.base import Base


class Localite(Base):
    """Référentiel des localités géographiques de Kuma Data Core."""

    __tablename__ = "localites"

    # === Identifiants ===
    id: Mapped[int] = mapped_column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    # === Métier ===
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    type_localite: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment=(
            "7 valeurs : continent, region_supranationale, pays, region_administrative, "
            "prefecture, commune, site. prefecture ajoutee en densification prefectorale "
            "Etape 1 (niveau pays > region > prefecture > commune)."
        ),
    )
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("localites.id", name="fk_localites_parent_id__localites"),
        nullable=True,
    )
    # Code administratif officiel externe (decret guineen 2025, 3 lettres, ex. CKY).
    code_administratif_national: Mapped[str | None] = mapped_column(
        String(8),
        nullable=True,
        comment=(
            "Code administratif officiel externe (decret guineen de codification 2025, "
            "3 lettres majuscules, ex. CKY). Nullable. Convention identifiant externe "
            "comme sources.doi / sources.isbn. Candidat cle de jointure INS / gouvernemental."
        ),
    )

    # === Géographie ===
    pays_iso3: Mapped[str | None] = mapped_column(String(3), nullable=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(11, 8), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    altitude_metres: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # === Démographie ===
    population_estimee: Mapped[int | None] = mapped_column(Integer, nullable=True)
    annee_population: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # === Métadonnées ===
    fuseau_horaire: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # === Soft delete ===
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    desactive_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # === Audit applicatif ===
    cree_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    cree_par: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("contributeurs.id", name="fk_localites_cree_par__contributeurs"),
        nullable=True,
    )
    modifie_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    modifie_par: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("contributeurs.id", name="fk_localites_modifie_par__contributeurs"),
        nullable=True,
    )

    # === Contraintes et index ===
    __table_args__ = (
        CheckConstraint(
            "type_localite IN ("
            "'continent', 'region_supranationale', 'pays', "
            "'region_administrative', 'prefecture', 'commune', 'site')",
            name="ck_localites_type_valide",
        ),
        CheckConstraint(
            "(type_localite = 'continent' AND parent_id IS NULL) OR (type_localite != 'continent')",
            name="ck_localites_continent_racine",
        ),
        CheckConstraint(
            "latitude IS NULL OR (latitude BETWEEN -90 AND 90)",
            name="ck_localites_latitude_bornes",
        ),
        CheckConstraint(
            "longitude IS NULL OR (longitude BETWEEN -180 AND 180)",
            name="ck_localites_longitude_bornes",
        ),
        CheckConstraint(
            "pays_iso3 IS NULL OR pays_iso3 ~ '^[A-Z]{3}$'",
            name="ck_localites_pays_iso3_format",
        ),
        CheckConstraint(
            "population_estimee IS NULL OR population_estimee >= 0",
            name="ck_localites_population_positive",
        ),
        CheckConstraint(
            "annee_population IS NULL OR (annee_population BETWEEN 1900 AND 2100)",
            name="ck_localites_annee_population_bornes",
        ),
        CheckConstraint(
            "(population_estimee IS NULL AND annee_population IS NULL) "
            "OR (population_estimee IS NOT NULL "
            "AND annee_population IS NOT NULL)",
            name="ck_localites_demographie_coherente",
        ),
        CheckConstraint(
            "code ~ '^[a-z][a-z0-9_]*$'",
            name="ck_localites_code_format",
        ),
        CheckConstraint(
            "code_administratif_national IS NULL OR code_administratif_national ~ '^[A-Z]{3}$'",
            name="ck_localites_code_administratif_format",
        ),
        CheckConstraint(
            "(actif = TRUE AND desactive_le IS NULL) "
            "OR (actif = FALSE AND desactive_le IS NOT NULL)",
            name="ck_localites_actif_desactive_le",
        ),
        Index("idx_localites_actif", "actif"),
        Index("idx_localites_type_localite", "type_localite"),
        Index("idx_localites_pays_iso3", "pays_iso3"),
        Index("idx_localites_parent_id", "parent_id"),
    )

    def __repr__(self) -> str:
        return f"<Localite(code={self.code!r}, type={self.type_localite!r}, nom={self.nom!r})>"
