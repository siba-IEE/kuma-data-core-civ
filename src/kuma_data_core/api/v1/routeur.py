"""Agrégation des routeurs de la version v1.

Tous les routeurs métier de la v1 sont montés ici, sous le préfixe
``/v1``. ``main.creer_application()`` inclut ``routeur_v1`` une seule
fois ; l'ajout d'un nouveau domaine se fait par un nouvel
``include_router(...)`` dans ce module.
"""

from __future__ import annotations

from fastapi import APIRouter

from kuma_data_core.api.v1 import (
    calage,
    cles,
    edition,
    etudes,
    grandeurs,
    health,
    horaire,
    localites,
    series,
)

routeur_v1 = APIRouter(prefix="/v1")
routeur_v1.include_router(health.routeur)
routeur_v1.include_router(edition.routeur)
routeur_v1.include_router(cles.routeur)
routeur_v1.include_router(series.routeur)
routeur_v1.include_router(localites.routeur)
routeur_v1.include_router(grandeurs.routeur)
routeur_v1.include_router(horaire.routeur)
routeur_v1.include_router(calage.routeur)
routeur_v1.include_router(etudes.routeur)
