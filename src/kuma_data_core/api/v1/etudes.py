"""Endpoint d'étude au point : l'émetteur de capsule Kuma.

``GET /v1/etudes/capsule`` assemble la ressource complète du moteur pour un point
(lat, lon) et la rend au format ``kuma-ressource-1``, prête à lire par
``@kuma/moteur-minireseau``.

Deux fonctionnements, un seul endpoint, la seule différence est le calage :

- ``calage=0`` (défaut) — capsule **brute**, hors-ligne. Ne touche que la base du
  Core (résolution, climatologie mensuelle profonde, séquence horaire satellite).
- ``calage=1`` — ressource **calibrée**, en ligne. Appelle kuma-calage serveur à
  serveur et cuit ses facteurs par saison dans la ressource. La loi ne descend
  jamais, seuls ses facteurs au point.

La séquence horaire est plafonnée à la profondeur de l'horaire NASA (2001-2025) ;
la fenêtre ``annee_min`` / ``annee_max`` permet d'alléger la capsule.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from kuma_data_core.api.codes_erreur import CodeErreur
from kuma_data_core.api.dependencies import CleApiValidee
from kuma_data_core.api.erreurs import ExceptionKuma
from kuma_data_core.core.config import get_settings
from kuma_data_core.db.session import obtenir_session
from kuma_data_core.services.capsule.acquisition import (
    PointHorsReferentielError,
    SourceCore,
)
from kuma_data_core.services.capsule.client_calage import CalageIndisponibleError
from kuma_data_core.services.capsule.construire import assembler_capsule

routeur = APIRouter(prefix="/etudes", tags=["etudes"])


@routeur.get(
    "/capsule",
    status_code=status.HTTP_200_OK,
    summary="Assemble la ressource complete du moteur pour un point",
    description=(
        "Pour un point (lat, lon), assemble la ressource au format "
        "`kuma-ressource-1`. `calage=0` : capsule brute hors-ligne "
        "(base du Core seule). `calage=1` : ressource calibree en ligne "
        "(appel serveur a serveur a kuma-calage). La sequence horaire "
        "satellite est plafonnee a 2001-2025 ; `annee_min`/`annee_max` "
        "fenetrent la profondeur servie."
    ),
    responses={
        404: {"description": "Le point ne se resout sur aucune localite du referentiel."},
        503: {"description": "Mode en ligne demande mais kuma-calage indisponible."},
    },
)
def assembler_etude_capsule(
    _cle: CleApiValidee,
    session: Annotated[Session, Depends(obtenir_session)],
    lat: Annotated[float, Query(ge=-90, le=90, description="Latitude WGS84 du point.")],
    lon: Annotated[float, Query(ge=-180, le=180, description="Longitude WGS84 du point.")],
    calage: Annotated[
        bool, Query(description="1 : ressource calibree en ligne. 0 : capsule brute.")
    ] = False,
    annee_min: Annotated[
        int | None, Query(ge=2001, le=2025, description="Borne basse de la fenetre horaire.")
    ] = None,
    annee_max: Annotated[
        int | None, Query(ge=2001, le=2025, description="Borne haute de la fenetre horaire.")
    ] = None,
) -> Response:
    """Assemble et rend la ressource au format fichier Kuma."""
    if annee_min is not None and annee_max is not None and annee_min > annee_max:
        raise ExceptionKuma(
            code=CodeErreur.VALIDATION_VALEUR_INVALIDE,
            message="annee_min ne peut pas depasser annee_max.",
            statut_http=status.HTTP_400_BAD_REQUEST,
        )

    source = SourceCore(session=session, annee_min=annee_min, annee_max=annee_max)

    base_calage: str | None = None
    jeton_calage: str | None = None
    if calage:
        settings = get_settings()
        base_calage = settings.kuma_calage_base
        jeton = settings.kuma_calage_jeton
        jeton_calage = jeton.get_secret_value() if jeton is not None else None
        if not base_calage or not jeton_calage:
            raise ExceptionKuma(
                code=CodeErreur.CALAGE_INDISPONIBLE,
                message="Le calage en ligne n'est pas configure sur ce serveur.",
                statut_http=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

    try:
        texte = assembler_capsule(
            lat,
            lon,
            source=source,
            avec_calage=calage,
            base_calage=base_calage,
            jeton_calage=jeton_calage,
        )
    except PointHorsReferentielError as e:
        raise ExceptionKuma(
            code=CodeErreur.RESSOURCE_INTROUVABLE,
            message=str(e),
            statut_http=status.HTTP_404_NOT_FOUND,
        ) from e
    except CalageIndisponibleError as e:
        raise ExceptionKuma(
            code=CodeErreur.CALAGE_INDISPONIBLE,
            message="kuma-calage indisponible pour le calage en ligne.",
            statut_http=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from e

    return Response(content=texte, media_type="text/plain; charset=utf-8")
