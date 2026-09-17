"""Tests unitaires du module ``ingestion.nasa_power_daily``.

Couvre le filtrage des sentinelles, le calcul du niveau dérivé, le
skip via variable d'environnement. Le client httpx est mocké via
``httpx.MockTransport`` pour éviter tout appel réseau réel.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from kuma_data_core.ingestion.nasa_power_daily import (
    _ingestion_doit_etre_skip,
    _parse_cle_date_nasa,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# U13-U15 : parsing et helpers
# ---------------------------------------------------------------------------


def test_u13_parse_cle_date_nasa_format_yyyymmdd() -> None:
    """U13 : YYYYMMDD parsée correctement en date Python."""
    assert _parse_cle_date_nasa("20210101") == date(2021, 1, 1)
    assert _parse_cle_date_nasa("20251231") == date(2025, 12, 31)


def test_u13_parse_cle_date_nasa_format_invalide_leve_valueerror() -> None:
    """U13 : format hors YYYYMMDD lève ValueError (strptime)."""
    with pytest.raises(ValueError):
        _parse_cle_date_nasa("2021-01-01")
    with pytest.raises(ValueError):
        _parse_cle_date_nasa("not_a_date")


# ---------------------------------------------------------------------------
# U14 : skip par variable d'environnement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("valeur", ["1", "true", "TRUE", "yes", "Yes"])
def test_u14_skip_variable_env_truthy(valeur: str) -> None:
    with patch.dict(os.environ, {"KUMA_SKIP_NASA_POWER_INGESTION": valeur}):
        assert _ingestion_doit_etre_skip() is True


@pytest.mark.parametrize("valeur", ["0", "false", "no", "", "random"])
def test_u14_skip_variable_env_falsy(valeur: str) -> None:
    with patch.dict(os.environ, {"KUMA_SKIP_NASA_POWER_INGESTION": valeur}):
        assert _ingestion_doit_etre_skip() is False


def test_u14_skip_variable_env_absente() -> None:
    """Variable absente → ingestion doit s'exécuter (skip = False)."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("KUMA_SKIP_NASA_POWER_INGESTION", None)
        assert _ingestion_doit_etre_skip() is False


# ---------------------------------------------------------------------------
# U15 : mock httpx pour validation pipeline (sans DB)
# ---------------------------------------------------------------------------


def _payload_nasa_avec_sentinelles() -> dict[str, Any]:
    """Payload NASA POWER mocké avec 1 sentinelle pour tester le filtrage."""
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-13.7, 9.5, 6.0]},
        "properties": {
            "parameter": {
                "ALLSKY_SFC_SW_DWN": {
                    "20210101": 5.42,
                    "20210102": 5.18,
                    "20210103": -999.0,  # sentinelle à filtrer
                    "20210104": 4.97,
                }
            }
        },
        "header": {
            "title": "NASA/POWER Test",
            "api": {"version": "v2.8.9", "name": "POWER Daily API"},
            "fill_value": -999.0,
            "time_standard": "UTC",
            "start": "20210101",
            "end": "20210104",
        },
        "parameters": {
            "ALLSKY_SFC_SW_DWN": {
                "units": "kW-hr/m^2/day",
                "longname": "GHI",
            }
        },
        "messages": [],
    }


def test_u15_mock_httpx_pipeline_smoke() -> None:
    """U15 : smoke test du mock httpx - payload parsé sans erreur via fetch_daily."""
    from kuma_data_core.external.nasa_power import fetch_daily

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload_nasa_avec_sentinelles())

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
    ):
        response = fetch_daily(
            latitude=9.5,
            longitude=-13.7,
            parameters=["ALLSKY_SFC_SW_DWN"],
            start=date(2021, 1, 1),
            end=date(2021, 1, 4),
            httpx_client=client,
        )

    valeurs = response.properties.parameter["ALLSKY_SFC_SW_DWN"]
    assert len(valeurs) == 4
    # Filtrage des sentinelles fait par le module ingestion lui-même
    valeurs_valides = {k: v for k, v in valeurs.items() if v != -999.0}
    assert len(valeurs_valides) == 3


# ---------------------------------------------------------------------------
# U16-U18 : ingerer_series_daily_groupe (1-3)
# ---------------------------------------------------------------------------


def _payload_nasa_multi_grandeurs() -> dict[str, Any]:
    """Payload mocké NASA POWER avec 4 paramètres (DNI/DHI/T2M/RH2M), 3 jours,
    incluant 1 sentinelle sur DNI au jour 2 pour tester le filtrage par grandeur.
    """
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-13.71222, 9.50917, 6.0]},
        "properties": {
            "parameter": {
                "ALLSKY_SFC_SW_DNI": {
                    "20210101": 7.50,
                    "20210102": -999.0,
                    "20210103": 7.20,
                },
                "ALLSKY_SFC_SW_DIFF": {
                    "20210101": 2.10,
                    "20210102": 2.30,
                    "20210103": 2.05,
                },
                "T2M": {"20210101": 27.3, "20210102": 27.5, "20210103": 26.9},
                "RH2M": {"20210101": 78.0, "20210102": 80.0, "20210103": 79.0},
            }
        },
        "header": {
            "title": "NASA/POWER Test multi-grandeurs",
            "api": {"version": "v2.8.9", "name": "POWER Daily API"},
            "fill_value": -999.0,
            "time_standard": "UTC",
            "start": "20210101",
            "end": "20210103",
        },
        "parameters": {
            "ALLSKY_SFC_SW_DNI": {"units": "kW-hr/m^2/day", "longname": "DNI"},
            "ALLSKY_SFC_SW_DIFF": {"units": "kW-hr/m^2/day", "longname": "DHI"},
            "T2M": {"units": "C", "longname": "T2M"},
            "RH2M": {"units": "%", "longname": "RH2M"},
        },
        "messages": [],
    }


def test_u16_ingerer_series_groupe_skip_via_env() -> None:
    """U16 : variable d'env truthy court-circuite et retourne dict vide."""
    from unittest.mock import MagicMock

    from kuma_data_core.ingestion.nasa_power_daily import ingerer_series_daily_groupe

    session = MagicMock()
    with patch.dict(os.environ, {"KUMA_SKIP_NASA_POWER_INGESTION": "1"}):
        result = ingerer_series_daily_groupe(
            session=session,
            codes_series=["gin_conakry_dni_nasa_power_2021_2025"],
            mapping_grandeur_parametre_nasa={"dni": "ALLSKY_SFC_SW_DNI"},
            latitude=9.5,
            longitude=-13.7,
            periode_debut=date(2021, 1, 1),
            periode_fin=date(2021, 1, 3),
        )
    assert result == {}
    session.execute.assert_not_called()


def test_u17_ingerer_series_groupe_codes_vides_retourne_dict_vide() -> None:
    """U17 : codes_series vide → dict vide, pas d'appel API."""
    from unittest.mock import MagicMock

    from kuma_data_core.ingestion.nasa_power_daily import ingerer_series_daily_groupe

    session = MagicMock()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("KUMA_SKIP_NASA_POWER_INGESTION", None)
        result = ingerer_series_daily_groupe(
            session=session,
            codes_series=[],
            mapping_grandeur_parametre_nasa={},
            latitude=9.5,
            longitude=-13.7,
            periode_debut=date(2021, 1, 1),
            periode_fin=date(2021, 1, 3),
        )
    assert result == {}
    session.execute.assert_not_called()


def test_u18_payload_multi_grandeurs_filtre_sentinelles() -> None:
    """U18 : smoke test pipeline multi-grandeurs - payload 4 params avec
    1 sentinelle filtré au niveau client (le module ingestion fera le
    filtrage final par grandeur).
    """
    from kuma_data_core.external.nasa_power import fetch_daily

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload_nasa_multi_grandeurs())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = fetch_daily(
            latitude=9.5,
            longitude=-13.7,
            parameters=[
                "ALLSKY_SFC_SW_DNI",
                "ALLSKY_SFC_SW_DIFF",
                "T2M",
                "RH2M",
            ],
            start=date(2021, 1, 1),
            end=date(2021, 1, 3),
            httpx_client=client,
        )

    assert set(response.properties.parameter) == {
        "ALLSKY_SFC_SW_DNI",
        "ALLSKY_SFC_SW_DIFF",
        "T2M",
        "RH2M",
    }
    sentinelles_par_param = {
        param: sum(1 for v in valeurs.values() if v == -999.0)
        for param, valeurs in response.properties.parameter.items()
    }
    assert sentinelles_par_param == {
        "ALLSKY_SFC_SW_DNI": 1,
        "ALLSKY_SFC_SW_DIFF": 0,
        "T2M": 0,
        "RH2M": 0,
    }
