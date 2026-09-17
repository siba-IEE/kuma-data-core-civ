"""Orchestration de l'émetteur de capsule, du point au fichier Kuma.

Deux étages, séparés pour rester prouvables :

- ``construire_capsule`` — **pur**. Prend les entrées déjà acquises et le calage
  éventuel, appelle l'assembleur, sérialise. Aucune I/O, testable sur valeurs.
- ``assembler_capsule`` — l'orchestrateur. Résout le point via une **source
  d'acquisition injectée** (les données du Core), et en ligne seulement appelle
  kuma-calage. La source réelle (accès base) se branche à l'endpoint ; les tests
  injectent une source factice.

La frontière tient : hors-ligne, aucune touche à kuma-calage, la capsule est
brute. En ligne, le calage entre, et seulement ses facteurs par saison.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from kuma_data_core.services.capsule import client_calage, fichier_kuma
from kuma_data_core.services.capsule.assembleur import assembler_ressource


@dataclass(frozen=True)
class EntreesRessource:
    """Tout ce que l'acquisition rassemble pour une ressource, hors calage.

    Le calage n'est pas ici : il n'existe qu'en ligne et vient de kuma-calage,
    jamais de la même source que le brut.
    """

    metadonnees: dict[str, Any]
    periode: dict[str, Any]
    domaine_validite: dict[str, Any]
    climatologie_hep: list[float]
    sequence: dict[str, Any]
    sequence_contraignant: dict[str, Any] | None = None
    corrections: dict[str, Any] | None = None
    # Extremes de temperature au point (records froid/chaud, bruts NASA), ou
    # None tant que le Core ne les sert pas : la capsule omet alors le bloc.
    temperatures_conception: dict[str, Any] | None = None


class SourceCapsule(Protocol):
    """L'accès aux données brutes du Core pour un point (résolution incluse)."""

    def acquerir(self, latitude_deg: float, longitude_deg: float) -> EntreesRessource: ...


class CalageRequisError(ValueError):
    """Une capsule en ligne a été demandée sans de quoi joindre kuma-calage."""


def construire_capsule(entrees: EntreesRessource, *, calage: dict[str, Any] | None = None) -> str:
    """Assemble puis sérialise. Pur : mêmes entrées, même fichier.

    ``calage=None`` produit la capsule brute (hors-ligne) ; un calage présent
    produit la ressource calibrée (en ligne).
    """
    contenu = assembler_ressource(
        metadonnees=entrees.metadonnees,
        periode=entrees.periode,
        sequence_type=entrees.sequence,
        climatologie_hep=entrees.climatologie_hep,
        domaine_validite=entrees.domaine_validite,
        sequence_contraignant=entrees.sequence_contraignant,
        calage=calage,
        corrections=entrees.corrections,
        temperatures_conception=entrees.temperatures_conception,
    )
    return fichier_kuma.serialiser(contenu)


def assembler_capsule(
    latitude_deg: float,
    longitude_deg: float,
    *,
    source: SourceCapsule,
    avec_calage: bool,
    base_calage: str | None = None,
    jeton_calage: str | None = None,
) -> str:
    """Du point au fichier : acquisition Core, calage en ligne, puis construction.

    Hors-ligne (``avec_calage=False``) : la source du Core suffit, kuma-calage
    n'est jamais touché. En ligne : on appelle kuma-calage serveur à serveur et
    on cuit ses facteurs par saison dans la ressource.
    """
    entrees = source.acquerir(latitude_deg, longitude_deg)

    calage: dict[str, Any] | None = None
    if avec_calage:
        if not base_calage or not jeton_calage:
            raise CalageRequisError("capsule en ligne demandée sans base ni jeton kuma-calage")
        reponse = client_calage.couverture(base_calage, jeton_calage, latitude_deg, longitude_deg)
        calage = client_calage.referentiel_calage(reponse)

    return construire_capsule(entrees, calage=calage)
