"""Fixtures pytest partagées pour Kuma Data Core.

Le sujet sensible de ce module est l'**ordre d'initialisation** des
``Settings`` Pydantic :

* ``Settings.valider_coherence_environnement`` (validateur ``mode="after"``)
  refuserait l'instanciation si ``API_ENVIRONNEMENT=prod`` était lu sans
  les contraintes adaptées (docs, log_format, cle_admin).
* ``get_settings`` est ``@lru_cache`` : la première instanciation fige
  les valeurs pour toute la session de test.

D'où la fixture ``_configurer_env_test`` (``autouse=True``,
``scope="session"``) qui pose les variables d'environnement de test
**avant** tout import de l'application, puis vide explicitement le
cache de ``get_settings`` pour le cas où un module aurait déjà été
importé en amont (par un plugin pytest ou un import indirect).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


@pytest.fixture(scope="session", autouse=True)
def _configurer_env_test() -> None:
    """Force l'environnement de test avant tout import d'application."""
    os.environ["API_ENVIRONNEMENT"] = "dev"
    os.environ["API_DOCS_ACTIVES"] = "false"
    os.environ["API_CLE_SOLAR_BRIDGE"] = "test_cle_solar_xxxxxxxx"
    os.environ["API_CLE_ADMIN"] = "test_cle_admin_yyyyyyyy"
    os.environ["LOG_FORMAT"] = "json"
    os.environ["LOG_NIVEAU"] = "WARNING"

    # Le cache lru_cache de get_settings doit être vidé pour que les
    # nouvelles variables soient prises en compte si le module a déjà
    # été importé (par exemple par un plugin pytest).
    from kuma_data_core.core.config import get_settings

    get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:  # noqa: F821
    """Client HTTP synchrone pour interagir avec l'application FastAPI.

    Importé tardivement pour bénéficier des variables d'environnement
    posées par ``_configurer_env_test``.
    """
    from fastapi.testclient import TestClient

    from kuma_data_core.api.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def cle_solar_valide() -> str:
    """Clé API valide associée au consommateur ``solar_bridge`` en test."""
    return "test_cle_solar_xxxxxxxx"


@pytest.fixture
def cle_admin_valide() -> str:
    """Clé API valide associée au consommateur ``admin`` en test."""
    return "test_cle_admin_yyyyyyyy"


@pytest.fixture
def headers_auth(cle_solar_valide: str) -> dict[str, str]:
    """Headers d'authentification prêts à l'emploi avec une clé valide."""
    return {"Authorization": f"Bearer {cle_solar_valide}"}
