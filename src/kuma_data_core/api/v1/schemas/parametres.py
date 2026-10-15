"""Base des modèles de paramètres de requête injectés par ``Depends()``.

FastAPI construit ces modèles **après** sa propre validation des paramètres :
une erreur levée par un ``model_validator`` croisant plusieurs paramètres (ex.
``periode_fin < periode_debut``) sort donc en ``pydantic.ValidationError``, que
FastAPI ne convertit pas, et finissait en 500 ``SERVEUR_ERREUR_INTERNE``.

Les modèles de paramètres héritent de ``ParametresRequete`` ; le gestionnaire
``handler_validation_parametres`` (``api/erreurs.py``) répond 422
``VALIDATION_VALEUR_INVALIDE`` pour une ``ValidationError`` de l'un d'eux, et
laisse toute autre ``ValidationError`` (construction d'une réponse) en erreur
serveur.
"""

from __future__ import annotations

from pydantic import BaseModel


class ParametresRequete(BaseModel):
    """Modèle de paramètres de requête : ses erreurs de validation sont des 422."""


def noms_modeles_parametres() -> frozenset[str]:
    """Noms (``ValidationError.title``) de tous les modèles de paramètres."""
    noms: set[str] = set()
    a_visiter: list[type[BaseModel]] = [ParametresRequete]
    while a_visiter:
        classe = a_visiter.pop()
        for sous_classe in classe.__subclasses__():
            noms.add(sous_classe.__name__)
            a_visiter.append(sous_classe)
    return frozenset(noms)
