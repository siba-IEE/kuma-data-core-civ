"""Configuration du logging structuré pour Kuma Data Core.

Utilise ``structlog`` avec deux formats conditionnés par
``Settings.log_format`` :

- ``texte`` (défaut en dev) : sortie console colorisée, lisible.
- ``json`` (obligatoire en prod) : une ligne JSON par événement, parsable
  par les agrégateurs (Loki, ELK, Datadog…).

L'horodatage est en ISO 8601 UTC. Les variables de contexte attachées
via ``structlog.contextvars`` sont automatiquement fusionnées dans
chaque événement (utile pour propager un identifiant de requête, par
exemple).

Conventions de nommage des événements
-------------------------------------
Les ``event`` (premier argument positionnel de ``logger.info(...)``)
sont en snake_case français descriptif : ``api_demarrage``,
``api_arret``, ``requete_traitee``. Les attributs structurés sont
également en snake_case français : ``methode``, ``chemin``, ``statut``,
``duree_ms``.
"""

from __future__ import annotations

import logging
import sys
from typing import cast

import structlog
from structlog.types import Processor

from kuma_data_core.core.config import get_settings


def configurer_logging() -> None:
    """Configure ``structlog`` selon le format choisi (texte ou JSON).

    Cette fonction est idempotente - ``structlog.configure`` peut être
    appelée plusieurs fois sans effet de bord (par exemple, lors d'un
    redémarrage à chaud du serveur de dev).
    """
    settings = get_settings()

    processeurs_partages: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    rendu_final: Processor
    if settings.log_format == "json":
        rendu_final = structlog.processors.JSONRenderer()
    else:
        rendu_final = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*processeurs_partages, rendu_final],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_niveau)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def obtenir_logger(nom: str) -> structlog.stdlib.BoundLogger:
    """Retourne un logger nommé, conforme à la configuration courante.

    Utilisation :

        log = obtenir_logger("kuma.api.requete")
        log.info("requete_traitee", methode="GET", chemin="/v1/health")
    """
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(nom))
