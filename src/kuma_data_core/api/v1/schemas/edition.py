"""Schémas Pydantic de l'endpoint ``/v1/edition`` (ADR-0003, D7).

La fraîcheur est une propriété affichée : chaque déploiement public sert
une édition datée, et l'API dit laquelle. Les métadonnées sont produites
au moment de la publication (``exporter-edition.ps1``) et injectées dans
l'édition (table ``edition_metadonnees``), jamais devinées côté serveur.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class CouvertureResumee(BaseModel):
    """Volumétrie sommaire de l'édition servie (calculée à la lecture)."""

    localites: int = Field(description="Localités actives couvertes par l'édition.")
    series: int = Field(description="Séries actives au catalogue de l'édition.")


class ReponseEdition(BaseModel):
    """Réponse de ``GET /v1/edition``."""

    edition_id: str = Field(description="Identifiant daté de l'édition (edition_AAAAMMJJ).")
    date_publication: date = Field(description="Date de publication de l'édition.")
    revision_source: str = Field(description="Révision git du dépôt public au moment de l'export.")
    couverture_resumee: CouvertureResumee
