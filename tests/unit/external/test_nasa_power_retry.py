"""Tests unitaires du retry transverse `external/nasa_power.py`.

Couvre la fonction privée ``_executer_get_avec_retry`` qui applique un
retry exponentiel sur les exceptions transitoires (HTTP 429, HTTP 503,
``httpx.TimeoutException``). 6 cas T-RETRY-1 a T-RETRY-6 :

- T-RETRY-1 : 200 OK direct -> pas de retry, retour immediat.
- T-RETRY-2 : 429 puis 200 OK -> succes apres 1 retry.
- T-RETRY-3 : 4x 429 (epuisement) -> raise NasaPowerRateLimitError.
- T-RETRY-4 : 4x 503 (epuisement) -> raise NasaPowerHttpError.
- T-RETRY-5 : 4x TimeoutException -> raise NasaPowerTimeoutError.
- T-RETRY-6 : 404 -> pas de retry, retour immediat (caller gere 4xx).

Backoffs forces a (0.0, 0.0, 0.0) en test pour eviter time.sleep reel.
"""

from __future__ import annotations

import httpx
import pytest

from kuma_data_core.exceptions import (
    NasaPowerHttpError,
    NasaPowerRateLimitError,
    NasaPowerTimeoutError,
)
from kuma_data_core.external.nasa_power import _executer_get_avec_retry

pytestmark = pytest.mark.unit

_BACKOFF_TEST: tuple[float, ...] = (0.0, 0.0, 0.0)
"""Backoffs nuls pour acceleration des tests (1 appel initial + 3 retries)."""


def _construire_client_avec_statuts(statuts: list[int]) -> httpx.Client:
    """Construit un client httpx mockable qui renvoie les statuts dans l'ordre.

    Utilise ``httpx.MockTransport``. Le corps des reponses est vide JSON
    pour 200 et texte pour les autres statuts.
    """
    iterateur = iter(statuts)

    def handler(request: httpx.Request) -> httpx.Response:
        statut = next(iterateur)
        if statut == 200:
            return httpx.Response(status_code=200, json={"ok": True})
        return httpx.Response(status_code=statut, text=f"Erreur {statut}")

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_t_retry_1_succes_premiere_tentative() -> None:
    """T-RETRY-1 : 200 OK direct -> retour immediat sans retry."""
    client = _construire_client_avec_statuts([200])
    response = _executer_get_avec_retry(
        client=client,
        url="http://test/api",
        query_params={"k": "v"},
        timeout=30.0,
        retry_backoff_seconds=_BACKOFF_TEST,
    )
    assert response.status_code == 200


def test_t_retry_2_succes_apres_429() -> None:
    """T-RETRY-2 : 429 -> 200 OK -> retour valeur apres 1 retry."""
    client = _construire_client_avec_statuts([429, 200])
    response = _executer_get_avec_retry(
        client=client,
        url="http://test/api",
        query_params={},
        timeout=30.0,
        retry_backoff_seconds=_BACKOFF_TEST,
    )
    assert response.status_code == 200


def test_t_retry_3_epuisement_429() -> None:
    """T-RETRY-3 : 4 x 429 -> raise NasaPowerRateLimitError a l'epuisement."""
    client = _construire_client_avec_statuts([429, 429, 429, 429])
    with pytest.raises(NasaPowerRateLimitError) as exc_info:
        _executer_get_avec_retry(
            client=client,
            url="http://test/api",
            query_params={},
            timeout=30.0,
            retry_backoff_seconds=_BACKOFF_TEST,
        )
    assert exc_info.value.status_code == 429


def test_t_retry_4_epuisement_503() -> None:
    """T-RETRY-4 : 4 x 503 -> raise NasaPowerHttpError a l'epuisement."""
    client = _construire_client_avec_statuts([503, 503, 503, 503])
    with pytest.raises(NasaPowerHttpError) as exc_info:
        _executer_get_avec_retry(
            client=client,
            url="http://test/api",
            query_params={},
            timeout=30.0,
            retry_backoff_seconds=_BACKOFF_TEST,
        )
    # NasaPowerRateLimitError herite de NasaPowerHttpError ; verifier
    # que ce n'est pas une rate limit mais bien un 503 generique.
    assert exc_info.value.status_code == 503
    assert not isinstance(exc_info.value, NasaPowerRateLimitError)


def test_t_retry_5_timeout_x4_raises_timeout_error() -> None:
    """T-RETRY-5 : 4 x httpx.TimeoutException -> raise NasaPowerTimeoutError."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout simule", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(NasaPowerTimeoutError):
        _executer_get_avec_retry(
            client=client,
            url="http://test/api",
            query_params={},
            timeout=30.0,
            retry_backoff_seconds=_BACKOFF_TEST,
        )


def test_t_retry_6_pas_de_retry_sur_autres_statuts() -> None:
    """T-RETRY-6 : 404 -> retour immediat sans retry (caller gere 4xx).

    Le helper retourne la response telle quelle pour les statuts non
    retryables (200, 4xx != 429, 5xx != 503). Le caller
    ``_executer_requete`` gere ensuite le statut >= 400 en levant
    NasaPowerHttpError terminal.
    """
    client = _construire_client_avec_statuts([404])
    response = _executer_get_avec_retry(
        client=client,
        url="http://test/api",
        query_params={},
        timeout=30.0,
        retry_backoff_seconds=_BACKOFF_TEST,
    )
    assert response.status_code == 404
