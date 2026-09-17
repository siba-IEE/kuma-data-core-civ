"""Tests d'intégration des endpoints de santé.

* Test 1 : ``GET /v1/health`` sans auth, base UP → 200, payload public.
* Test 2 : ``GET /v1/health/db`` sans auth → 401, code
  ``AUTH_HEADER_MANQUANT``.
* Test 3 : ``GET /v1/health/db`` avec clé valide, base UP → 200,
  composant ``postgresql`` opérationnel. Nécessite Docker (PostgreSQL
  joignable).
* Test 4 : ``GET /v1/health/db`` avec clé valide, base DOWN simulée →
  503, code ``INFRASTRUCTURE_BASE_INDISPONIBLE``. Utilise
  ``app.dependency_overrides[obtenir_session]`` pour injecter une
  session factice qui lève à ``execute()``.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from kuma_data_core.api.codes_erreur import CodeErreur
from kuma_data_core.api.main import app
from kuma_data_core.db.session import obtenir_session


@pytest.mark.integration
def test_health_public_repond_200(client: TestClient) -> None:
    response = client.get("/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["statut"] == "operationnel"
    # Le health public ne divulgue ni version ni environnement (F-05) :
    # ces champs restent reserves au /v1/health/db authentifie.
    assert "version" not in payload
    assert "environnement" not in payload


@pytest.mark.integration
def test_health_db_sans_auth_repond_401(client: TestClient) -> None:
    response = client.get("/v1/health/db")
    assert response.status_code == 401
    payload = response.json()
    assert payload["erreur"]["code"] == CodeErreur.AUTH_HEADER_MANQUANT.value


@pytest.mark.integration
def test_health_db_avec_auth_et_base_up_repond_200(
    client: TestClient, headers_auth: dict[str, str]
) -> None:
    """Requiert une base PostgreSQL joignable (Docker Compose démarré)."""
    response = client.get("/v1/health/db", headers=headers_auth)
    assert response.status_code == 200
    payload = response.json()
    assert payload["statut"] == "operationnel"
    composants = {c["nom"]: c["statut"] for c in payload["composants"]}
    assert composants.get("postgresql") == "operationnel"


@pytest.mark.integration
def test_health_db_avec_auth_et_base_down_repond_503(
    client: TestClient, headers_auth: dict[str, str]
) -> None:
    """Simule une base injoignable via ``dependency_overrides``."""

    def _session_qui_echoue() -> Iterator[Session]:
        session_factice = MagicMock(spec=Session)
        session_factice.execute.side_effect = OperationalError(
            "SELECT 1", params=None, orig=Exception("connexion refusée")
        )
        yield session_factice

    app.dependency_overrides[obtenir_session] = _session_qui_echoue
    try:
        response = client.get("/v1/health/db", headers=headers_auth)
    finally:
        app.dependency_overrides.pop(obtenir_session, None)

    assert response.status_code == 503
    payload = response.json()
    assert payload["erreur"]["code"] == CodeErreur.INFRASTRUCTURE_BASE_INDISPONIBLE.value
    composants = {c["nom"]: c["statut"] for c in payload["erreur"]["details"]["composants"]}
    assert composants.get("postgresql") == "indisponible"
