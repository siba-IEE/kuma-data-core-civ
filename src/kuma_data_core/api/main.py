"""Point d'entrée de l'API Kuma Data Core.

Construit l'application FastAPI via ``creer_application()`` et expose
l'instance ``app`` consommée par ``uvicorn`` :

.. code-block:: bash

    uv run uvicorn kuma_data_core.api.main:app --reload --host 127.0.0.1 --port 8000

Le ``lifespan`` configure le logging structuré au démarrage et trace
``api_demarrage`` / ``api_arret``. Le middleware HTTP journalise chaque
requête traitée (``methode``, ``chemin``, ``statut``, ``duree_ms``). Les
exceptions non gérées sont loggées par ``handler_exception_generique``
(voir ``api/erreurs.py``).
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from kuma_data_core.api.erreurs import (
    ExceptionKuma,
    handler_exception_generique,
    handler_exception_kuma,
    handler_validation_requete,
)
from kuma_data_core.api.v1.routeur import routeur_v1
from kuma_data_core.core.config import get_settings
from kuma_data_core.core.logging import configurer_logging, obtenir_logger


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Cycle de vie de l'application : init logging, log start/stop."""
    configurer_logging()
    settings = get_settings()
    log = obtenir_logger("kuma.api.lifespan")
    log.info(
        "api_demarrage",
        environnement=settings.api_environnement,
        version=settings.api_version,
    )
    yield
    log.info("api_arret")


def creer_application() -> FastAPI:
    """Construit l'application FastAPI selon la configuration courante.

    Documentation OpenAPI conditionnée par ``Settings.api_docs_actives``
    (le validateur de configuration impose ``False`` en prod). Les
    handlers d'erreur sont enregistrés avant l'inclusion des routeurs
    pour s'appliquer à toutes les routes, y compris celles ajoutées
    dynamiquement.
    """
    settings = get_settings()

    docs_url = "/docs" if settings.api_docs_actives else None
    redoc_url = "/redoc" if settings.api_docs_actives else None
    openapi_url = "/openapi.json" if settings.api_docs_actives else None

    app = FastAPI(
        title=settings.api_titre,
        version=settings.api_version,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
        lifespan=lifespan,
    )
    # Middleware CORS - autorise les consommateurs Bridge à appeler l'API.
    # En dev local, Solar Bridge (Vite + Tauri) tourne sur localhost:1420.
    # En production, l'origine sera le bundle Tauri signé (tauri://localhost
    # sur Windows/Linux, https://tauri.localhost sur macOS).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:1420",
            "http://127.0.0.1:1420",
            "tauri://localhost",
            "https://tauri.localhost",
            "http://tauri.localhost",
        ],
        # Auth par jeton Bearer, aucun cookie de session : les credentials
        # cross-origin sont inutiles. On retire l'en-tete Allow-Credentials
        # orphelin (finding F-06 pentest).
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["Authorization", "Content-Type"],
    )
    # Handlers d'erreur - enregistrement avant les routeurs.
    # Le typage strict de FastAPI 0.115 impose un cast côté add_exception_handler
    # quand on passe un handler typé sur ``Exception`` ; nos handlers le sont déjà.
    app.add_exception_handler(ExceptionKuma, handler_exception_kuma)
    app.add_exception_handler(RequestValidationError, handler_validation_requete)
    app.add_exception_handler(Exception, handler_exception_generique)

    @app.middleware("http")
    async def journaliser_requete(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        log = obtenir_logger("kuma.api.requete")
        debut = time.perf_counter()
        response = await call_next(request)
        duree_ms = (time.perf_counter() - debut) * 1000
        log.info(
            "requete_traitee",
            methode=request.method,
            chemin=request.url.path,
            statut=response.status_code,
            duree_ms=round(duree_ms, 2),
        )
        return response

    # Routeurs versionnés.
    app.include_router(routeur_v1)

    return app


app = creer_application()
