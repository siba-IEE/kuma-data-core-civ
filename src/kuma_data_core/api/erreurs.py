"""Format d'erreur standardisé Kuma et handlers associés.

Toute erreur retournée par l'API suit la structure ``ErreurKuma`` :

.. code-block:: json

   {
     "erreur": {
       "code": "AUTH_CLE_INVALIDE",
       "message": "Clé API invalide ou révoquée.",
       "details": null
     }
   }

Le champ ``code`` est un identifiant technique stable (voir
``codes_erreur.CodeErreur``). Le champ ``message`` est en français,
destiné à être affiché à un humain. Le champ ``details`` est optionnel
et contient des informations structurées exploitables par les outils
consommateurs.

L'``ExceptionKuma`` est l'exception interne portant le triplet
``(code, message, statut HTTP)``. Elle est capturée par
``handler_exception_kuma`` et convertie en ``JSONResponse`` normalisée.
``handler_exception_generique`` sert de filet de sécurité : toute
exception non interceptée se transforme en 500 normalisé, sans fuite
de stack trace côté client.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from kuma_data_core.api.codes_erreur import CodeErreur
from kuma_data_core.core.logging import obtenir_logger


class DetailErreur(BaseModel):
    """Détail d'une erreur Kuma."""

    code: CodeErreur = Field(description="Code stable de l'erreur")
    message: str = Field(description="Message lisible en français")
    details: dict[str, Any] | None = Field(
        default=None,
        description="Informations supplémentaires structurées",
    )


class ErreurKuma(BaseModel):
    """Réponse d'erreur standardisée."""

    erreur: DetailErreur


class ExceptionKuma(Exception):
    """Exception interne portant un code d'erreur Kuma.

    Levée par les couches applicatives (dépendances FastAPI, services,
    routeurs) puis convertie en ``JSONResponse`` par
    ``handler_exception_kuma``.
    """

    def __init__(
        self,
        code: CodeErreur,
        message: str,
        statut_http: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.statut_http = statut_http
        self.details = details
        super().__init__(message)


async def handler_exception_kuma(request: Request, exc: Exception) -> JSONResponse:
    """Convertit une ``ExceptionKuma`` en réponse JSON normalisée.

    Le typage de ``exc`` est ``Exception`` (et non ``ExceptionKuma``)
    pour respecter la signature attendue par
    ``FastAPI.add_exception_handler`` ; un ``isinstance`` interne
    rétablit la précision.
    """
    assert isinstance(exc, ExceptionKuma)
    erreur = ErreurKuma(
        erreur=DetailErreur(
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )
    )
    return JSONResponse(
        status_code=exc.statut_http,
        content=erreur.model_dump(exclude_none=True),
    )


async def handler_validation_requete(request: Request, exc: Exception) -> JSONResponse:
    """Convertit une erreur de validation d'entrée en réponse ``ErreurKuma``.

    FastAPI lève ``RequestValidationError`` avant d'atteindre le code du
    routeur lorsqu'un paramètre viole son type, ses bornes ou un
    ``model_validator``. Sans ce handler, la réponse sortirait au format
    FastAPI par défaut (``{"detail": [...]}``), hors contrat Kuma.
    """
    details = jsonable_encoder(exc.errors()) if isinstance(exc, RequestValidationError) else None
    erreur = ErreurKuma(
        erreur=DetailErreur(
            code=CodeErreur.VALIDATION_VALEUR_INVALIDE,
            message="Une ou plusieurs valeurs de la requête sont invalides.",
            details={"erreurs": details} if details is not None else None,
        )
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=erreur.model_dump(exclude_none=True),
    )


async def handler_exception_generique(request: Request, exc: Exception) -> JSONResponse:
    """Filet de sécurité : toute exception non gérée → 500 normalisé.

    Le détail technique de ``exc`` n'est PAS exposé au client (pas de
    fuite de stack trace, de chemin interne, de version de dépendance).
    Le diagnostic se fait via les logs structlog côté serveur :
    ``exc_info=exc`` sérialise la stack trace complète dans l'entrée
    de log (rendue lisible en dev par ``ConsoleRenderer``, JSON-isée
    en prod par ``JSONRenderer`` via le processeur ``format_exc_info``
    configuré dans ``core.logging``).
    """
    log = obtenir_logger("kuma.api.erreur_non_geree")
    log.error(
        "exception_non_geree",
        methode=request.method,
        chemin=request.url.path,
        type_exception=type(exc).__name__,
        exc_info=exc,
    )
    erreur = ErreurKuma(
        erreur=DetailErreur(
            code=CodeErreur.SERVEUR_ERREUR_INTERNE,
            message="Une erreur interne est survenue.",
            details=None,
        )
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=erreur.model_dump(exclude_none=True),
    )
