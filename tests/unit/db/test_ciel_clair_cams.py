"""Tests unitaires des contrats du ciel clair, de l'irradiation extraterrestre et de la
fiabilité CAMS Radiation (ADR-0039) : colonnes, conversions, contrats et bornes."""

from __future__ import annotations

import pytest

from kuma_data_core.db.seeds.ciel_clair_cams_civ import (
    COLONNES_CIEL_CLAIR,
    CONTRATS_CIEL_CLAIR_JOURNALIERS,
    CONTRATS_CIEL_CLAIR_MENSUELS,
    GRANDEURS_CIEL_CLAIR,
    valeur_journaliere,
    valeur_mensuelle,
)
from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.series_csv import nb_jours

pytestmark = pytest.mark.unit


def test_colonnes_cams() -> None:
    """Une colonne CAMS par grandeur, repérée par son nom."""
    assert COLONNES_CIEL_CLAIR == {
        "ghi_ciel_clair": "Clear sky GHI",
        "dni_ciel_clair": "Clear sky BNI",
        "dhi_ciel_clair": "Clear sky DHI",
        "irradiation_extraterrestre": "TOA",
        "fiabilite_satellite": "Reliability",
    }
    assert tuple(COLONNES_CIEL_CLAIR) == GRANDEURS_CIEL_CLAIR


def test_conversions() -> None:
    """Wh/m² du jour ou du mois → kWh/m²/jour ; fiabilité telle que servie."""
    assert valeur_journaliere("ghi_ciel_clair", 6116.2783) == pytest.approx(6.1162783)
    assert valeur_journaliere("fiabilite_satellite", 0.9778) == 0.9778
    assert valeur_mensuelle("irradiation_extraterrestre", 275_650.3438, 2005, 1) == (
        pytest.approx(275.6503438 / 31)
    )
    assert valeur_mensuelle("dni_ciel_clair", 28_000.0, 2024, 2) == pytest.approx(28.0 / 29)
    assert valeur_mensuelle("fiabilite_satellite", 0.963, 2005, 1) == 0.963


@pytest.mark.parametrize("granularite", ["journalier", "mensuel"])
def test_contrats(granularite: str) -> None:
    contrats = (
        CONTRATS_CIEL_CLAIR_JOURNALIERS
        if granularite == "journalier"
        else CONTRATS_CIEL_CLAIR_MENSUELS
    )
    assert tuple(contrats) == GRANDEURS_CIEL_CLAIR
    plus_long = max(len(code) for code, _, _, _ in points_nationaux())
    for g, c in contrats.items():
        assert (c.source_code, c.source_id, c.methode_collecte) == (
            "cams_radiation",
            13,
            "modele_satellitaire",
        )
        assert (c.prefixe_code, c.grandeur_code, c.granularite) == (
            f"cams_{g}_{granularite}",
            g,
            granularite,
        )
        assert (c.annee_debut, c.annee_fin, c.lacunes_admises) == (2005, 2025, False)
        assert len(c.code_serie("x" * plus_long)) <= 80  # series_metadonnees.code
    bornes = {g: c.borne_max for g, c in contrats.items()}
    assert bornes["irradiation_extraterrestre"] == 12.0
    assert bornes["fiabilite_satellite"] == 1.0
    assert bornes["ghi_ciel_clair"] == 9.0 and bornes["dni_ciel_clair"] == 12.0
    assert bornes["dhi_ciel_clair"] == (7.0 if granularite == "journalier" else 6.0)
    assert nb_jours(CONTRATS_CIEL_CLAIR_JOURNALIERS["ghi_ciel_clair"]) == 7_670
    assert CONTRATS_CIEL_CLAIR_MENSUELS["ghi_ciel_clair"].nb_mois == 252
