"""Tests unitaires du retry transverse `ingestion/sarah3_monthly.py`.

Couvre la fonction privée ``_fetch_sarah3_monthly_raw`` qui delegue au
helper partage ``external/_http_retry.executer_get_avec_retry`` et
traduit les exceptions generiques en exceptions PVGIS domaine-
specifiques (``PvgisRateLimitError``, ``PvgisHttpError``,
``PvgisTimeoutError``).

6 cas T-RETRY-SARAH3-1 a T-RETRY-SARAH3-6 :

- T-RETRY-SARAH3-1 : 200 OK direct -> pas de retry.
- T-RETRY-SARAH3-2 : 429 puis 200 OK -> succes apres 1 retry.
- T-RETRY-SARAH3-3 : 4x 429 -> raise PvgisRateLimitError.
- T-RETRY-SARAH3-4 : 4x 503 -> raise PvgisHttpError.
- T-RETRY-SARAH3-5 : 4x httpx.TimeoutException -> raise PvgisTimeoutError.
- T-RETRY-SARAH3-6 : 4x httpx.RemoteProtocolError -> raise PvgisTimeoutError
  (cas exact du flake CI observe sur migration 041 : disconnect
  serveur PVGIS depuis les runners GitHub Actions).

Patch ``time.sleep`` via ``conftest.py`` autouse pour acceleration
(backoffs reels 1s+4s+16s neutralises).
"""

from __future__ import annotations

import httpx
import pytest

from kuma_data_core.exceptions import (
    PvgisHttpError,
    PvgisRateLimitError,
    PvgisTimeoutError,
)
from kuma_data_core.ingestion.sarah3_monthly import _fetch_sarah3_monthly_raw

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _force_mode_live(monkeypatch: pytest.MonkeyPatch) -> None:
    """Épingle le mode ``live`` pour ces tests.

    Ils couvrent le chemin réseau/retry de ``_fetch_sarah3_monthly_raw``, qui est
    court-circuité par le chemin offline-seed. On force ``live`` pour
    qu'ils testent le réseau quel que soit ``KUMA_INGESTION_MODE`` ambiant.
    """
    monkeypatch.setenv("KUMA_INGESTION_MODE", "live")


def _construire_client_avec_statuts(statuts: list[int]) -> httpx.Client:
    """Construit un client httpx mockable qui renvoie les statuts dans l'ordre.

    Le corps JSON minimal pour les 200 reflete la structure PVGIS
    MRcalc attendue (``outputs.monthly`` liste).
    """
    iterateur = iter(statuts)

    def handler(request: httpx.Request) -> httpx.Response:
        statut = next(iterateur)
        if statut == 200:
            return httpx.Response(
                status_code=200,
                json={
                    "inputs": {},
                    "outputs": {"monthly": [{"year": 2022, "month": 1, "H(h)_m": 5.81}]},
                    "meta": {},
                },
            )
        return httpx.Response(status_code=statut, text=f"PVGIS erreur {statut}")

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_t_retry_sarah3_1_succes_premiere_tentative() -> None:
    """T-RETRY-SARAH3-1 : 200 OK direct -> retour immediat sans retry."""
    client = _construire_client_avec_statuts([200])
    payload = _fetch_sarah3_monthly_raw(
        latitude=9.5092,
        longitude=-13.7122,
        annee_debut=2022,
        annee_fin=2022,
        timeout=30.0,
        httpx_client=client,
    )
    assert "outputs" in payload


def test_t_retry_sarah3_2_succes_apres_429() -> None:
    """T-RETRY-SARAH3-2 : 429 -> 200 OK -> succes apres 1 retry."""
    client = _construire_client_avec_statuts([429, 200])
    payload = _fetch_sarah3_monthly_raw(
        latitude=9.5092,
        longitude=-13.7122,
        annee_debut=2022,
        annee_fin=2022,
        timeout=30.0,
        httpx_client=client,
    )
    assert "outputs" in payload


def test_t_retry_sarah3_3_epuisement_429() -> None:
    """T-RETRY-SARAH3-3 : 4 x 429 -> raise PvgisRateLimitError."""
    client = _construire_client_avec_statuts([429, 429, 429, 429])
    with pytest.raises(PvgisRateLimitError) as exc_info:
        _fetch_sarah3_monthly_raw(
            latitude=9.5092,
            longitude=-13.7122,
            annee_debut=2022,
            annee_fin=2022,
            timeout=30.0,
            httpx_client=client,
        )
    assert exc_info.value.status_code == 429


def test_t_retry_sarah3_4_epuisement_503() -> None:
    """T-RETRY-SARAH3-4 : 4 x 503 -> raise PvgisHttpError (non rate limit)."""
    client = _construire_client_avec_statuts([503, 503, 503, 503])
    with pytest.raises(PvgisHttpError) as exc_info:
        _fetch_sarah3_monthly_raw(
            latitude=9.5092,
            longitude=-13.7122,
            annee_debut=2022,
            annee_fin=2022,
            timeout=30.0,
            httpx_client=client,
        )
    assert exc_info.value.status_code == 503
    assert not isinstance(exc_info.value, PvgisRateLimitError)


def test_t_retry_sarah3_5_timeout_x4_raises_pvgis_timeout_error() -> None:
    """T-RETRY-SARAH3-5 : 4 x httpx.TimeoutException -> raise PvgisTimeoutError."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout simule", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(PvgisTimeoutError):
        _fetch_sarah3_monthly_raw(
            latitude=9.5092,
            longitude=-13.7122,
            annee_debut=2022,
            annee_fin=2022,
            timeout=30.0,
            httpx_client=client,
        )


def test_t_retry_sarah3_6_remote_protocol_error_x4_raises_pvgis_timeout_error() -> None:
    """T-RETRY-SARAH3-6 : 4 x httpx.RemoteProtocolError -> raise PvgisTimeoutError.

    Cas exact du flake CI observe sur migration 041 : disconnect
    serveur PVGIS upstream depuis les runners GitHub Actions. Le retry
    transverse l'absorbe au meme titre que TimeoutException et leve
    PvgisTimeoutError a l'epuisement.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError(
            "Server disconnected without sending a response.",
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(PvgisTimeoutError):
        _fetch_sarah3_monthly_raw(
            latitude=9.5092,
            longitude=-13.7122,
            annee_debut=2022,
            annee_fin=2022,
            timeout=30.0,
            httpx_client=client,
        )
