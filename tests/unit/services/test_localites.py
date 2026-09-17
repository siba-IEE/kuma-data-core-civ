"""Tests unitaires de `services/localites.py` (helper coordonnees).

Pattern : la fonction ``_charger_coordonnees`` est decoree
``@lru_cache(maxsize=1)`` - le cache est invalide entre tests via
``_charger_coordonnees.cache_clear()`` pour eviter la pollution.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from kuma_data_core.services.localites import (
    _charger_coordonnees,
    coordonnees_localite,
)

pytestmark = pytest.mark.unit


def _construire_mock_session(rows: list[tuple[str, float, float]]) -> MagicMock:
    """Construit un mock de Session SQLAlchemy retournant les rows donnes."""
    mock_rows = [MagicMock(code=code, latitude=lat, longitude=lon) for code, lat, lon in rows]
    mock_session = MagicMock()
    mock_session.execute.return_value.all.return_value = mock_rows
    # Le pattern `with factory() as session:` est emulé via context manager.
    mock_session.__enter__.return_value = mock_session
    mock_session.__exit__.return_value = None
    return mock_session


@pytest.fixture(autouse=True)
def _invalider_cache_entre_tests() -> None:
    """Invalide le cache @lru_cache entre tests pour isolation."""
    _charger_coordonnees.cache_clear()


def test_coordonnees_localite_retourne_tuple_pour_6_villes() -> None:
    """Les 6 codes Kuma (préfixés gin_) retournent un tuple (lat, lon).

    Verifie le contrat de coordonnees_localite : recherche par code DB
    complet et retour du tuple float.
    """
    rows_simules = [
        ("gin_conakry_kaloum", 9.5092, -13.7122),
        ("gin_kankan", 10.3886, -9.3056),
        ("gin_kindia", 10.04972222, -12.85416667),
        ("gin_labe", 11.3179, -12.2833),
        ("gin_mamou", 10.3753, -12.0911),
        ("gin_nzerekore", 7.75222222, -8.82166667),
    ]
    mock_session = _construire_mock_session(rows_simules)
    mock_factory = MagicMock(return_value=mock_session)

    with patch(
        "kuma_data_core.services.localites.get_session_factory",
        return_value=mock_factory,
    ):
        for code, lat_attendu, lon_attendu in rows_simules:
            lat, lon = coordonnees_localite(code)
            assert isinstance(lat, float)
            assert isinstance(lon, float)
            assert lat == pytest.approx(lat_attendu)
            assert lon == pytest.approx(lon_attendu)


def test_charger_coordonnees_cache_lru() -> None:
    """Le second appel ne relit pas la DB (verification @lru_cache effective)."""
    rows_simules = [("gin_conakry_kaloum", 9.5092, -13.7122)]
    mock_session = _construire_mock_session(rows_simules)
    mock_factory = MagicMock(return_value=mock_session)

    with patch(
        "kuma_data_core.services.localites.get_session_factory",
        return_value=mock_factory,
    ):
        # Premier appel : lecture DB.
        _charger_coordonnees()
        assert mock_factory.call_count == 1

        # Second appel : cache hit, pas de relecture DB.
        _charger_coordonnees()
        assert mock_factory.call_count == 1


def test_coordonnees_localite_code_inconnu_leve_key_error() -> None:
    """Un code absent de la table leve KeyError (validation amont Pydantic).

    En pratique, la validation Pydantic ``Literal[...]`` sur l'API
    empeche ce cas. Le test verifie le contrat brut de la fonction.
    """
    rows_simules = [("gin_conakry_kaloum", 9.5092, -13.7122)]
    mock_session = _construire_mock_session(rows_simules)
    mock_factory = MagicMock(return_value=mock_session)

    with (
        patch(
            "kuma_data_core.services.localites.get_session_factory",
            return_value=mock_factory,
        ),
        pytest.raises(KeyError),
    ):
        coordonnees_localite("gin_inexistant")
