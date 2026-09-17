"""Tests unitaires du module ``ingestion.nasa_power_hourly``.

Couvre le parsing des cles horaires ``YYYYMMDDHH`` -> ``datetime`` UTC,
le skip via variable d'environnement, et un smoke test du pipeline
``fetch_hourly`` via ``httpx.MockTransport`` (sans appel reseau reel).
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from kuma_data_core.ingestion.nasa_power_hourly import (
    _ingestion_doit_etre_skip,
    _parse_cle_yyyymmddhh,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Parsing des cles horaires
# ---------------------------------------------------------------------------


def test_parse_cle_yyyymmddhh_valide() -> None:
    """YYYYMMDDHH parsee en datetime UTC tz-aware."""
    assert _parse_cle_yyyymmddhh("2021060112") == datetime(2021, 6, 1, 12, tzinfo=UTC)
    assert _parse_cle_yyyymmddhh("2021010100") == datetime(2021, 1, 1, 0, tzinfo=UTC)
    assert _parse_cle_yyyymmddhh("2023123123") == datetime(2023, 12, 31, 23, tzinfo=UTC)


def test_parse_cle_yyyymmddhh_tz_aware_utc() -> None:
    """Le datetime retourne porte bien le fuseau UTC (pas naif)."""
    instant = _parse_cle_yyyymmddhh("2021060112")
    assert instant is not None
    assert instant.tzinfo is UTC


def test_parse_cle_yyyymmddhh_invalide_retourne_none() -> None:
    """Cle non conforme -> None (pas d'exception)."""
    assert _parse_cle_yyyymmddhh("20210601") is None  # 8 chiffres (daily)
    assert _parse_cle_yyyymmddhh("2021-06-0112") is None  # non numerique
    assert _parse_cle_yyyymmddhh("not_a_key!") is None
    assert _parse_cle_yyyymmddhh("2021139912") is None  # mois 13 hors bornes
    assert _parse_cle_yyyymmddhh("2021060124") is None  # heure 24 hors bornes


# ---------------------------------------------------------------------------
# Skip par variable d'environnement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("valeur", ["1", "true", "TRUE", "yes", "Yes"])
def test_skip_variable_env_truthy(valeur: str) -> None:
    with patch.dict(os.environ, {"KUMA_SKIP_NASA_POWER_INGESTION": valeur}):
        assert _ingestion_doit_etre_skip() is True


@pytest.mark.parametrize("valeur", ["0", "false", "no", "", "random"])
def test_skip_variable_env_falsy(valeur: str) -> None:
    with patch.dict(os.environ, {"KUMA_SKIP_NASA_POWER_INGESTION": valeur}):
        assert _ingestion_doit_etre_skip() is False


def test_skip_variable_env_absente() -> None:
    """Variable absente -> ingestion doit s'executer (skip = False)."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("KUMA_SKIP_NASA_POWER_INGESTION", None)
        assert _ingestion_doit_etre_skip() is False


# ---------------------------------------------------------------------------
# Smoke test pipeline via mock httpx (sans DB)
# ---------------------------------------------------------------------------


def _payload_nasa_hourly_avec_sentinelles() -> dict[str, Any]:
    """Payload NASA POWER hourly mocke (cles YYYYMMDDHH, 1 sentinelle)."""
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-13.7, 9.5, 6.0]},
        "properties": {
            "parameter": {
                "ALLSKY_SFC_SW_DWN": {
                    "2021060110": 612.3,
                    "2021060111": 740.1,
                    "2021060112": -999.0,  # sentinelle a filtrer
                    "2021060113": 705.8,
                }
            }
        },
        "header": {
            "title": "NASA/POWER Test hourly",
            "api": {"version": "v2.8.9", "name": "POWER Hourly API"},
            "fill_value": -999.0,
            "time_standard": "UTC",
            "start": "20210601",
            "end": "20210601",
        },
        "parameters": {
            "ALLSKY_SFC_SW_DWN": {"units": "Wh/m^2", "longname": "GHI"},
        },
        "messages": [],
    }


def test_smoke_fetch_hourly_mock() -> None:
    """Smoke : payload hourly parse via fetch_hourly, sentinelle reperable."""
    from kuma_data_core.external.nasa_power import fetch_hourly

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload_nasa_hourly_avec_sentinelles())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = fetch_hourly(
            latitude=9.5,
            longitude=-13.7,
            parameters=["ALLSKY_SFC_SW_DWN"],
            start=date(2021, 6, 1),
            end=date(2021, 6, 1),
            time_standard="UTC",
            httpx_client=client,
        )

    valeurs = response.properties.parameter["ALLSKY_SFC_SW_DWN"]
    assert len(valeurs) == 4
    valeurs_valides = {k: v for k, v in valeurs.items() if v != -999.0}
    assert len(valeurs_valides) == 3
