"""Tests unitaires du client NASA POWER.

Couvre les chemins fonctionnels et erreurs de
``kuma_data_core.external.nasa_power`` via ``httpx.MockTransport``,
sans appel réseau réel. Les tests d'intégration avec NASA POWER
effective relèvent d'un script d'extraction dédié.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest

from kuma_data_core.exceptions import (
    NasaPowerHttpError,
    NasaPowerPayloadError,
    NasaPowerRateLimitError,
    NasaPowerTimeoutError,
)
from kuma_data_core.external.nasa_power import (
    BASE_URL,
    DEFAULT_COMMUNITY,
    SENTINELLE_VALEUR_MANQUANTE,
    NasaPowerResponse,
    calculer_indice_ciel_clair,
    fetch_daily,
    fetch_hourly,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Payload de référence (Conakry-Kaloum, 3 jours, 2 paramètres)
# ---------------------------------------------------------------------------


def _payload_daily_valide() -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [-13.71222, 9.50917, 6.0],
        },
        "properties": {
            "parameter": {
                "ALLSKY_SFC_SW_DWN": {
                    "20210101": 5.42,
                    "20210102": 5.18,
                    "20210103": 4.97,
                },
                "T2M": {
                    "20210101": 27.3,
                    "20210102": 27.5,
                    "20210103": 26.9,
                },
            }
        },
        "header": {
            "title": "NASA/POWER Source Native Resolution Daily Data",
            "api": {"version": "v2.5.6", "name": "POWER Daily API"},
            "fill_value": -999.0,
            "time_standard": "UTC",
            "start": "20210101",
            "end": "20210103",
            "sources": ["MERRA-2", "CERES SYN1deg"],
        },
        "parameters": {
            "ALLSKY_SFC_SW_DWN": {
                "units": "kW-hr/m^2/day",
                "longname": "All Sky Surface Shortwave Downward Irradiance",
            },
            "T2M": {"units": "C", "longname": "Temperature at 2 Meters"},
        },
        "messages": [],
    }


def _client_avec_handler(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


# ---------------------------------------------------------------------------
# 1. fetch_daily - happy path
# ---------------------------------------------------------------------------


def test_fetch_daily_happy_path_parse_le_payload() -> None:
    payload = _payload_daily_valide()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "temporal/daily/point" in str(request.url)
        return httpx.Response(200, json=payload)

    with _client_avec_handler(httpx.MockTransport(handler)) as client:
        result = fetch_daily(
            latitude=9.50917,
            longitude=-13.71222,
            parameters=["ALLSKY_SFC_SW_DWN", "T2M"],
            start=date(2021, 1, 1),
            end=date(2021, 1, 3),
            httpx_client=client,
        )

    assert isinstance(result, NasaPowerResponse)
    assert result.geometry.coordinates == (-13.71222, 9.50917, 6.0)
    assert result.properties.parameter["ALLSKY_SFC_SW_DWN"]["20210101"] == 5.42
    assert result.header.fill_value == SENTINELLE_VALEUR_MANQUANTE
    assert result.parameters["ALLSKY_SFC_SW_DWN"].units == "kW-hr/m^2/day"


def test_fetch_daily_construit_lurl_avec_format_yyyymmdd() -> None:
    urls_appelees: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls_appelees.append(str(request.url))
        return httpx.Response(200, json=_payload_daily_valide())

    with _client_avec_handler(httpx.MockTransport(handler)) as client:
        fetch_daily(
            latitude=9.50917,
            longitude=-13.71222,
            parameters=["ALLSKY_SFC_SW_DWN", "T2M"],
            start=date(2021, 1, 1),
            end=date(2025, 12, 31),
            httpx_client=client,
        )

    assert len(urls_appelees) == 1
    url = urls_appelees[0]
    assert url.startswith(f"{BASE_URL}/daily/point")
    assert "start=20210101" in url
    assert "end=20251231" in url
    assert "parameters=ALLSKY_SFC_SW_DWN%2CT2M" in url or "parameters=ALLSKY_SFC_SW_DWN,T2M" in url
    assert f"community={DEFAULT_COMMUNITY}" in url
    assert "latitude=9.50917" in url
    assert "longitude=-13.71222" in url
    assert "format=JSON" in url


# ---------------------------------------------------------------------------
# 2. fetch_hourly - happy path et format yyyymmddhh
# ---------------------------------------------------------------------------


def test_fetch_hourly_construit_lurl_avec_format_yyyymmdd_et_time_standard() -> None:
    """L'endpoint hourly accepte les paramètres
    ``start``/``end`` au format ``YYYYMMDD``, pas ``YYYYMMDDHH``. Les
    clés de réponse restent en ``YYYYMMDDHH``.
    """
    payload_hourly = _payload_daily_valide()
    # Réécrire les clés date au format horaire pour respecter le schéma
    payload_hourly["properties"]["parameter"] = {
        "ALLSKY_SFC_SW_DWN": {"2024070100": 0.0, "2024070112": 4.8},
        "T2M": {"2024070100": 24.1, "2024070112": 28.7},
    }
    payload_hourly["header"]["start"] = "20240701"
    payload_hourly["header"]["end"] = "20240701"

    urls_appelees: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls_appelees.append(str(request.url))
        return httpx.Response(200, json=payload_hourly)

    with _client_avec_handler(httpx.MockTransport(handler)) as client:
        result = fetch_hourly(
            latitude=9.50917,
            longitude=-13.71222,
            parameters=["ALLSKY_SFC_SW_DWN", "T2M"],
            start=date(2024, 7, 1),
            end=date(2024, 7, 1),
            httpx_client=client,
        )

    assert isinstance(result, NasaPowerResponse)
    url = urls_appelees[0]
    assert "temporal/hourly/point" in url
    assert "start=20240701" in url
    assert "end=20240701" in url
    assert "time-standard=UTC" in url


# ---------------------------------------------------------------------------
# 3. HTTP 429 - NasaPowerRateLimitError
# ---------------------------------------------------------------------------


def test_fetch_daily_http_429_leve_nasapowerratelimit_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="Too Many Requests")

    with (
        _client_avec_handler(httpx.MockTransport(handler)) as client,
        pytest.raises(NasaPowerRateLimitError) as exc_info,
    ):
        fetch_daily(
            latitude=9.50917,
            longitude=-13.71222,
            parameters=["ALLSKY_SFC_SW_DWN"],
            start=date(2021, 1, 1),
            end=date(2021, 1, 3),
            httpx_client=client,
        )

    erreur = exc_info.value
    assert erreur.status_code == 429
    assert "Too Many Requests" in erreur.body
    # Sous-type de NasaPowerHttpError donc isinstance valide
    assert isinstance(erreur, NasaPowerHttpError)


# ---------------------------------------------------------------------------
# 4. HTTP 500 - NasaPowerHttpError générique
# ---------------------------------------------------------------------------


def test_fetch_daily_http_500_leve_nasapowerhttperror_generique() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    with (
        _client_avec_handler(httpx.MockTransport(handler)) as client,
        pytest.raises(NasaPowerHttpError) as exc_info,
    ):
        fetch_daily(
            latitude=9.50917,
            longitude=-13.71222,
            parameters=["ALLSKY_SFC_SW_DWN"],
            start=date(2021, 1, 1),
            end=date(2021, 1, 3),
            httpx_client=client,
        )

    erreur = exc_info.value
    assert erreur.status_code == 500
    assert not isinstance(erreur, NasaPowerRateLimitError)


# ---------------------------------------------------------------------------
# 5. JSON invalide - NasaPowerPayloadError
# ---------------------------------------------------------------------------


def test_fetch_daily_json_invalide_leve_nasapowerpayload_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not a valid json {{{")

    with (
        _client_avec_handler(httpx.MockTransport(handler)) as client,
        pytest.raises(NasaPowerPayloadError) as exc_info,
    ):
        fetch_daily(
            latitude=9.50917,
            longitude=-13.71222,
            parameters=["ALLSKY_SFC_SW_DWN"],
            start=date(2021, 1, 1),
            end=date(2021, 1, 3),
            httpx_client=client,
        )

    assert "non parsable en JSON" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 6. JSON parsable mais hors schéma - NasaPowerPayloadError
# ---------------------------------------------------------------------------


def test_fetch_daily_payload_hors_schema_leve_nasapowerpayload_error() -> None:
    payload_invalide: dict[str, Any] = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [0.0, 0.0, 0.0]},
        # `properties`, `header`, `parameters` manquants → ValidationError pydantic
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload_invalide)

    with (
        _client_avec_handler(httpx.MockTransport(handler)) as client,
        pytest.raises(NasaPowerPayloadError) as exc_info,
    ):
        fetch_daily(
            latitude=0.0,
            longitude=0.0,
            parameters=["ALLSKY_SFC_SW_DWN"],
            start=date(2021, 1, 1),
            end=date(2021, 1, 3),
            httpx_client=client,
        )

    assert "schéma NasaPowerResponse" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 7. Timeout - NasaPowerTimeoutError
# ---------------------------------------------------------------------------


def test_fetch_daily_timeout_leve_nasapowertimeout_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Mocked timeout", request=request)

    with (
        _client_avec_handler(httpx.MockTransport(handler)) as client,
        pytest.raises(NasaPowerTimeoutError) as exc_info,
    ):
        fetch_daily(
            latitude=9.50917,
            longitude=-13.71222,
            parameters=["ALLSKY_SFC_SW_DWN"],
            start=date(2021, 1, 1),
            end=date(2021, 1, 3),
            timeout=5.0,
            httpx_client=client,
        )

    assert exc_info.value.timeout_seconds == 5.0


# ---------------------------------------------------------------------------
# 8. calculer_indice_ciel_clair
# ---------------------------------------------------------------------------


def test_calculer_indice_ciel_clair_valeur_normale() -> None:
    # Cas pleinement nuageux : K = 0.3
    k = calculer_indice_ciel_clair(allsky=2.4, clrsky=8.0)
    assert k == pytest.approx(0.3)


def test_calculer_indice_ciel_clair_ciel_clair() -> None:
    # Cas ciel clair : K ≈ 1
    k = calculer_indice_ciel_clair(allsky=8.0, clrsky=8.0)
    assert k == pytest.approx(1.0)


def test_calculer_indice_ciel_clair_anomalie_allsky_superieur_clrsky() -> None:
    # Anomalie GHI > CLRSKY : K > 1, doit être retourné tel quel
    # (la caractérisation se fait en aval par le rapport éditorial)
    k = calculer_indice_ciel_clair(allsky=8.5, clrsky=8.0)
    assert k is not None and k > 1.0


def test_calculer_indice_ciel_clair_sentinelle_allsky() -> None:
    assert calculer_indice_ciel_clair(allsky=-999.0, clrsky=8.0) is None


def test_calculer_indice_ciel_clair_sentinelle_clrsky() -> None:
    assert calculer_indice_ciel_clair(allsky=5.0, clrsky=-999.0) is None


def test_calculer_indice_ciel_clair_division_par_zero() -> None:
    # Cas nuit ou pôle hivernal : CLRSKY = 0
    assert calculer_indice_ciel_clair(allsky=0.0, clrsky=0.0) is None
