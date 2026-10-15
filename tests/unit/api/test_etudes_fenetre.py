"""Tests unitaires de la fenetre horaire de ``GET /v1/etudes/capsule`` (ADR-0029).

Les bornes ``annee_min`` / ``annee_max`` ne controlent que la
plausibilite : une periode figee (ancien ``2001-2025``) refuserait toute
annee ajoutee par une edition ulterieure. L'assemblage et la session sont
simules : ces tests ne touchent ni la base ni le reseau.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from kuma_data_core.api.codes_erreur import CodeErreur
from kuma_data_core.api.main import app
from kuma_data_core.db.session import obtenir_session

pytestmark = pytest.mark.unit


@pytest.fixture
def client_sans_base() -> Iterator[TestClient]:
    def _session_factice() -> Iterator[Session]:
        yield MagicMock(spec=Session)

    app.dependency_overrides[obtenir_session] = _session_factice
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(obtenir_session, None)


@pytest.mark.parametrize(("annee_min", "annee_max"), [(2026, 2026), (2024, 2030), (1995, 2000)])
def test_fenetre_hors_ancienne_periode_figee_acceptee(
    client_sans_base: TestClient,
    headers_auth: dict[str, str],
    annee_min: int,
    annee_max: int,
) -> None:
    with patch(
        "kuma_data_core.api.v1.etudes.assembler_capsule", return_value="capsule"
    ) as assembler:
        r = client_sans_base.get(
            "/v1/etudes/capsule",
            params={"lat": 5.4, "lon": -4.0, "annee_min": annee_min, "annee_max": annee_max},
            headers=headers_auth,
        )
    assert r.status_code == 200, r.text
    assert r.text == "capsule"
    source = assembler.call_args.kwargs["source"]
    assert (source.annee_min, source.annee_max) == (annee_min, annee_max)


@pytest.mark.parametrize("annee", [1899, 2101])
def test_fenetre_implausible_refusee(
    client_sans_base: TestClient, headers_auth: dict[str, str], annee: int
) -> None:
    r = client_sans_base.get(
        "/v1/etudes/capsule",
        params={"lat": 5.4, "lon": -4.0, "annee_min": annee},
        headers=headers_auth,
    )
    assert r.status_code == 422
    assert r.json()["erreur"]["code"] == CodeErreur.VALIDATION_VALEUR_INVALIDE.value


def test_fenetre_inversee_refusee(
    client_sans_base: TestClient, headers_auth: dict[str, str]
) -> None:
    r = client_sans_base.get(
        "/v1/etudes/capsule",
        params={"lat": 5.4, "lon": -4.0, "annee_min": 2030, "annee_max": 2026},
        headers=headers_auth,
    )
    assert r.status_code == 400
    assert r.json()["erreur"]["code"] == CodeErreur.VALIDATION_VALEUR_INVALIDE.value
