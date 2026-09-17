"""Schémas Pydantic de l'endpoint ``/api/v1/calage``.

Le référentiel de calage satellite/sol (ADR-0004) : biais saisonniers
mesurés aux stations de référence, publiés avec provenance et portée.
Le facteur ``k = 1 / (1 + biais)`` est dérivé côté serveur pour
éviter toute divergence d'arrondi chez les consommateurs.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SaisonCalage(BaseModel):
    """Une saison du référentiel : biais mesuré et facteur dérivé."""

    nom: str
    mois: list[int] = Field(description="Mois couverts (1-12).")
    biais: float = Field(description="Biais relatif moyen satellite moins sol (0.044 pour +4,4 %).")
    k: float = Field(description="Facteur de calage derive : k = 1 / (1 + biais).")


class ReponseCalage(BaseModel):
    """Référentiel de calage d'un couple (station, grandeur).

    ``localites_couvertes`` porte le domaine de couverture du
    transport (ADR-0004, couverture progressive) : les codes des
    localités qualifiées, triés. C'est la donnée qui pilote la
    couverture géographique des consommateurs - une étude calée
    n'est permise que si la localité résolue du site en fait partie.
    ``justification_couverture`` en donne la provenance.
    """

    localite: str
    grandeur: str
    code: str
    version: str
    saisons: list[SaisonCalage]
    provenance: str
    portee: str
    localites_couvertes: list[str] = Field(default_factory=list)
    justification_couverture: str | None = None
    serie_sol: str = Field(
        description=(
            "Code de la serie sol de fondation du referentiel : la "
            "sequence horaire de reference a utiliser avec ce calage. "
            "Decouverte par l'API, jamais une constante consommateur."
        )
    )


class ReferentielListe(BaseModel):
    """Un referentiel de calage au listing (une entree par code)."""

    code: str
    localite: str
    grandeur: str
    version: str
    serie_sol: str
    localites_couvertes: list[str] = Field(default_factory=list)


class ReponseCalageListe(BaseModel):
    """Reponse de ``GET /v1/calage`` : les referentiels publies."""

    items: list[ReferentielListe]
    total: int
