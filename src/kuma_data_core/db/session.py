"""Moteur et fabrique de sessions SQLAlchemy pour Kuma Data Core.

Le moteur est créé paresseusement (``lru_cache``) afin qu'une simple
importation du module n'ouvre pas de connexion réseau. La fabrique de
sessions est elle aussi memoizée, et reste utilisable comme point
d'entrée unique tant que la couche FastAPI n'introduit pas son propre
gestionnaire de contexte.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from kuma_data_core.core.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Retourne le moteur SQLAlchemy unique du processus.

    ``pool_pre_ping=True`` valide chaque connexion avant usage : utile
    en développement où PostgreSQL peut redémarrer indépendamment de
    l'application.
    """
    settings = get_settings()
    return create_engine(
        settings.database_url,
        echo=False,
        future=True,
        pool_pre_ping=True,
    )


@lru_cache(maxsize=4)
def _engine_pour_url(url: str) -> Engine:
    """Moteur memoizé par DSN (base de service, tests)."""
    return create_engine(url, echo=False, future=True, pool_pre_ping=True)


def get_engine_meta() -> Engine:
    """Moteur de la base de service ``kuma_api_meta`` (ADR-0003, D3).

    Distinct du moteur principal : la base de service persiste à
    travers les bascules d'édition et porte ``cles_api``. Lève si la
    configuration ne désigne pas de base de service (``META_DB``
    absente = régime local, self-service désactivé).
    """
    url = get_settings().database_url_meta
    if url is None:
        raise RuntimeError("META_DB non configurée : pas de base de service sur ce déploiement.")
    return _engine_pour_url(url)


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Retourne la fabrique de sessions associée au moteur unique."""
    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )


def obtenir_session() -> Iterator[Session]:
    """Dépendance FastAPI : ouvre une session, la cède, la ferme.

    Utilisée via ``Depends(obtenir_session)`` dans les routeurs. Le
    contextmanager garantit la fermeture (rollback implicite si
    l'endpoint a levé une exception, commit explicite à la charge du
    code applicatif).

    Implémentation **synchrone** alignée sur l'engine sync du projet.
    FastAPI exécute les handlers ``def`` (non ``async def``) dans un
    threadpool, ce qui rend l'usage de psycopg3 sync sans risque pour
    la boucle d'événements en phase 0.
    """
    factory = get_session_factory()
    with factory() as session:
        yield session
