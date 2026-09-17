"""Tests unitaires de `api/services/serie_lecture.resolve_table_from_series_metadata`.

Routage source-first puis granularite. 6 tests
T-1 a T-6 couvrant les 4 tables-cibles + les cas fail-fast. Fonction pure
(sans I/O) - pas de mock DB requis.
"""

from __future__ import annotations

import pytest

from kuma_data_core.api.services.serie_lecture import (
    TableMesures,
    resolve_table_from_series_metadata,
)

pytestmark = pytest.mark.unit


def test_t1_resolve_kuma_calculs() -> None:
    """T-1 : source=kuma_calculs -> GRANDEURS_METIER, granularite ignoree (NULL)."""
    for granularite in (None, "mensuel", "horaire"):
        result = resolve_table_from_series_metadata(
            source_code="kuma_calculs",
            granularite=granularite,
        )
        assert result == TableMesures.GRANDEURS_METIER
        assert result.value == "grandeurs_metier"


def test_t2_resolve_granularite_mensuel() -> None:
    """T-2 : granularite=mensuel -> MENSUEL_RESSOURCE (nasa_power clim, sarah3)."""
    for source in ("nasa_power", "sarah3_monthly"):
        result = resolve_table_from_series_metadata(
            source_code=source,
            granularite="mensuel",
        )
        assert result == TableMesures.MENSUEL_RESSOURCE
        assert result.value == "mesures_ressource_mensuelles"


def test_t3_resolve_granularite_journalier() -> None:
    """T-3 : granularite=journalier -> JOURNALIER."""
    result = resolve_table_from_series_metadata(
        source_code="nasa_power",
        granularite="journalier",
    )
    assert result == TableMesures.JOURNALIER
    assert result.value == "mesures_ressource"


def test_t4_resolve_granularite_horaire() -> None:
    """T-4 : granularite=horaire -> HORAIRE."""
    result = resolve_table_from_series_metadata(
        source_code="nasa_power",
        granularite="horaire",
    )
    assert result == TableMesures.HORAIRE
    assert result.value == "mesures_ressource_horaires"


def test_t5_resolve_granularite_null_non_kuma_fail_fast() -> None:
    """T-5 : granularite NULL sur serie non-kuma_calculs -> ValueError (fail-fast)."""
    with pytest.raises(ValueError, match="Routage non resolu"):
        resolve_table_from_series_metadata(
            source_code="nasa_power",
            granularite=None,
        )


def test_t6_resolve_granularite_inconnue_fail_fast() -> None:
    """T-6 : granularite hors domaine routage -> ValueError (fail-fast)."""
    # 'annuel' / 'statique' existent pour grandeurs_metier.periode_type
    # mais ne sont pas des granularites de table-cible routables.
    with pytest.raises(ValueError, match="Routage non resolu"):
        resolve_table_from_series_metadata(
            source_code="nasa_power",
            granularite="annuel",
        )
    with pytest.raises(ValueError, match="Routage non resolu"):
        resolve_table_from_series_metadata(
            source_code="era5_reanalyse_future",
            granularite="journalier_3h",
        )
