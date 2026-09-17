"""Schémas Pydantic des endpoints ``/v1/cles`` (ADR-0003, D3 / WP6)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DemandeCle(BaseModel):
    """Corps de ``POST /v1/cles`` - inscription self-service légère."""

    email: str = Field(
        min_length=3,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="Adresse de contact du titulaire (identification, pas de compte).",
    )
    usage_prevu: str | None = Field(
        default=None,
        max_length=500,
        description="Description libre de l'usage envisagé (facultatif).",
    )


class ReponseCleCreee(BaseModel):
    """Réponse de ``POST /v1/cles`` - la clé n'est montrée qu'une fois."""

    cle: str = Field(
        description=(
            "Clé API complète. Elle n'est jamais stockée en clair côté "
            "serveur et ne sera plus jamais affichée : la conserver "
            "immédiatement."
        )
    )
    prefixe: str = Field(description="Identifiant public de la clé (support, révocation).")
    quota_journalier: int = Field(description="Requêtes autorisées par jour.")


class ReponseRevocation(BaseModel):
    """Réponse de ``DELETE /v1/cles/{prefixe}``."""

    prefixe: str
    cles_revoquees: int
