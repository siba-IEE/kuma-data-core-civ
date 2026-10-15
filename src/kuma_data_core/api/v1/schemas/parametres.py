"""Base des modèles de paramètres de requête injectés par ``Depends()``.

FastAPI construit ces modèles **après** sa propre validation des paramètres :
une erreur levée par un ``model_validator`` croisant plusieurs paramètres (ex.
``periode_fin < periode_debut``) sort donc en ``pydantic.ValidationError``, que
FastAPI ne convertit pas, et finissait en 500 ``SERVEUR_ERREUR_INTERNE``. Cette
base la convertit en ``RequestValidationError`` : la réponse est le 422
``VALIDATION_VALEUR_INVALIDE`` habituel, avec le détail de l'erreur.

Seuls les modèles de paramètres en héritent : une ``ValidationError`` levée
ailleurs (construction d'une réponse) reste une erreur serveur.
"""

from __future__ import annotations

from typing import Any

from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError


class ParametresRequete(BaseModel):
    """Modèle de paramètres de requête : erreurs de validation en 422."""

    def __init__(self, /, **data: Any) -> None:
        try:
            super().__init__(**data)
        except ValidationError as exc:
            raise RequestValidationError(exc.errors(include_url=False)) from exc
