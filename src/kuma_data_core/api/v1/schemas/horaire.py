"""Schémas Pydantic des endpoints `/api/v1/horaire/<localite>/<grandeur>`.

Cinq schémas pour le passe-plat horaire :

- :class:`ParametresHoraire` : paramètres communs (localité, grandeur,
  plage temporelle, format de sortie).
- :class:`ResultatHoraire` : un point horaire passe-plat (instant ISO,
  valeur ou null, unité, statut éditorial).
- :class:`PlageTemporelle` : helper structurel pour les plages
  temporelles inclusives.
- :class:`ReponseHoraire` : réponse complète d'un endpoint data.
- :class:`ReponseDisponibilite` : réponse de l'endpoint
  ``/disponibilite``.

Principe « Kuma assume » : aucun champ ne mentionne la source amont
(NASA POWER, SARAH-3, etc.). Le statut éditorial uniforme
``passe_plat_non_valide`` signale au consommateur que les données
horaires ne sont pas validées éditorialement par Kuma.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# === Constantes module ====================================================


GRANDEURS_AUTORISEES: tuple[str, ...] = (
    "ghi",
    "dni",
    "dhi",
    "t2m",
    "rh2m",
    "kt",
    "vent_2m",
    "vent_10m",
    "precipitation",
)
"""9 grandeurs horaires ingérables (vents et précipitation ajoutés avec la
densification horaire aux 28 communes)."""

PLAGE_MAX_JOURS: int = 366
"""Plage temporelle maximale par requête (année bissextile incluse)."""

DATE_DEBUT_DISPONIBILITE: date = date(2001, 1, 1)
"""Borne historique de début de la disponibilité passe-plat horaire."""


# === Schémas paramètres ===================================================


class ParametresHoraire(BaseModel):
    """Paramètres communs aux endpoints du passe-plat horaire.

    Le champ ``format_sortie`` est exposé en query string sous le nom
    URL ``format`` via ``Query(alias="format")`` côté handler - alias
    nécessaire pour éviter le shadow du built-in Python ``format``.
    """

    # Toute localite du referentiel (code complet, ex. gin_kankan) ;
    # les codes courts historiques des 6 villes pilotes restent des
    # alias de compatibilite, resolus par le handler contre la table
    # (genericite pays : plus de liste codee).
    localite: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9_]+$")
    grandeur: Literal[
        "ghi", "dni", "dhi", "t2m", "rh2m", "kt", "vent_2m", "vent_10m", "precipitation"
    ]
    periode_debut: date = Field(..., ge=DATE_DEBUT_DISPONIBILITE)
    periode_fin: date
    format_sortie: Literal["json", "csv"] = Field(
        default="json",
        alias="format",
        description="Format de reponse : 'json' (defaut) ou 'csv'.",
    )

    @model_validator(mode="after")
    def _valider_plage_temporelle(self) -> ParametresHoraire:
        if self.periode_fin < self.periode_debut:
            raise ValueError("periode_fin doit etre superieure ou egale a periode_debut")
        if (self.periode_fin - self.periode_debut).days > PLAGE_MAX_JOURS:
            raise ValueError(f"plage maximale {PLAGE_MAX_JOURS} jours par requete")
        return self


# === Schémas résultats ====================================================


class PlageTemporelle(BaseModel):
    """Plage temporelle inclusive [début, fin]."""

    debut: date
    fin: date


class ResultatHoraire(BaseModel):
    """Un point horaire (24 par jour, fuseau UTC).

    ``statut_editorial`` distingue les deux régimes de service :

    - ``valide_auto`` : donnée horaire **stockée et validée** par le
      contrôle qualité algorithmique Kuma (confiance B).
    - ``passe_plat_non_valide`` : donnée relayée à la volée (passe-plat),
      non validée éditorialement - servie en repli là où aucune donnée
      validée ne couvre la plage demandée.
    """

    instant: datetime
    valeur: float | None = Field(
        default=None,
        description=(
            "Valeur numerique ou null si donnee manquante (sentinelle "
            "amont ou indice physique non defini selon la grandeur)."
        ),
    )
    unite: str
    statut_editorial: Literal["valide_auto", "passe_plat_non_valide"] = "passe_plat_non_valide"


# === Schémas réponses =====================================================


class ReponseHoraire(BaseModel):
    """Réponse complète d'un endpoint passe-plat horaire data."""

    localite: str
    grandeur: str
    periode_demandee: PlageTemporelle
    resultats: list[ResultatHoraire]


class ReponseDisponibilite(BaseModel):
    """Réponse de l'endpoint `/disponibilite`."""

    localite: str
    grandeur: str
    plage_disponible: PlageTemporelle
    statut_editorial: Literal["passe_plat_non_valide"] = "passe_plat_non_valide"
