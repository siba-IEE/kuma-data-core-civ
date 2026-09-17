"""Endpoints de santé.

Deux endpoints :

* ``GET /v1/health``    - public, indique que l'API répond.
* ``GET /v1/health/db`` - authentifié, vérifie la connectivité PostgreSQL.

La vérification Redis est volontairement absente : aucun endpoint de
l'API n'utilise encore Redis. Elle sera ajoutée le jour où le cache
devient critique pour un endpoint métier.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.api.codes_erreur import CodeErreur
from kuma_data_core.api.dependencies import CleApiValidee
from kuma_data_core.api.erreurs import ExceptionKuma
from kuma_data_core.core.config import get_settings
from kuma_data_core.db.session import obtenir_session

routeur = APIRouter(prefix="/health", tags=["sante"])


class ReponseSantePublique(BaseModel):
    """Réponse de l'endpoint public ``/v1/health``.

    Ne divulgue ni la version logicielle ni l'environnement : sur un
    endpoint non authentifié, ces informations aident un attaquant à
    cibler des vulnérabilités connues sans bénéfice pour un client
    légitime (finding F-05 pentest). Elles restent disponibles sur
    ``/v1/health/db`` (authentifié).
    """

    statut: Literal["operationnel"]
    # Identifiant de l'édition publiée servie par ce déploiement
    # (ADR-0003, D7). ``None`` hors régime édition (base de dev) ou si
    # la lecture échoue : le health ne dépend de rien, jamais de 5xx.
    edition: str | None = None


class StatutComposant(BaseModel):
    """État d'un composant d'infrastructure (base, cache...)."""

    nom: str
    statut: Literal["operationnel", "degrade", "indisponible"]


class ReponseSanteDetailee(BaseModel):
    """Réponse de l'endpoint authentifié ``/v1/health/db``."""

    statut: Literal["operationnel", "degrade", "indisponible"]
    version: str
    environnement: str
    composants: list[StatutComposant]


def _edition_courante_silencieuse() -> str | None:
    """Identifiant de l'édition servie, ou ``None`` - jamais d'exception.

    Lecture best-effort pour préserver la propriété du health public :
    il répond toujours, même base injoignable. Le détail de l'édition
    (date, révision, couverture) vit sur ``GET /v1/edition``.
    """
    try:
        from kuma_data_core.db.session import get_engine

        with get_engine().connect() as connexion:
            presente = connexion.execute(
                text("SELECT to_regclass('public.edition_metadonnees')")
            ).scalar()
            if presente is None:
                return None
            edition_id = connexion.execute(
                text("SELECT edition_id FROM edition_metadonnees LIMIT 1")
            ).scalar()
            return str(edition_id) if edition_id is not None else None
    except Exception:
        return None


@routeur.get(
    "",
    response_model=ReponseSantePublique,
    status_code=status.HTTP_200_OK,
    summary="Santé publique de l'API",
    description="Endpoint non authentifié indiquant que l'API répond.",
)
def sante() -> ReponseSantePublique:
    """Réponse minimale ; l'édition est lue en best-effort (jamais de 5xx)."""
    return ReponseSantePublique(
        statut="operationnel",
        edition=_edition_courante_silencieuse(),
    )


@routeur.get(
    "/db",
    response_model=ReponseSanteDetailee,
    status_code=status.HTTP_200_OK,
    summary="Santé détaillée (base de données)",
    description=(
        "Endpoint authentifié vérifiant la connectivité à la base "
        "PostgreSQL. La vérification Redis sera ajoutée quand un "
        "endpoint en aura besoin."
    ),
)
def sante_detailee(
    _cle: CleApiValidee,
    session: Annotated[Session, Depends(obtenir_session)],
) -> ReponseSanteDetailee:
    """Vérifie l'état de PostgreSQL via un ``SELECT 1``.

    Si la requête échoue, l'endpoint retourne un statut HTTP 503 avec
    le code ``INFRASTRUCTURE_BASE_INDISPONIBLE``. Le détail des
    composants est inclus dans la charge utile de l'erreur pour
    faciliter le diagnostic côté client.
    """
    settings = get_settings()
    composants: list[StatutComposant] = []

    try:
        session.execute(text("SELECT 1"))
        composants.append(StatutComposant(nom="postgresql", statut="operationnel"))
    except Exception as exc:
        composants.append(StatutComposant(nom="postgresql", statut="indisponible"))
        raise ExceptionKuma(
            code=CodeErreur.INFRASTRUCTURE_BASE_INDISPONIBLE,
            message="Base de données injoignable.",
            statut_http=status.HTTP_503_SERVICE_UNAVAILABLE,
            details={"composants": [c.model_dump() for c in composants]},
        ) from exc

    return ReponseSanteDetailee(
        statut="operationnel",
        version=settings.api_version,
        environnement=settings.api_environnement,
        composants=composants,
    )
