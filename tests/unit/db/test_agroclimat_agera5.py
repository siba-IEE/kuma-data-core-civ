"""Tests unitaires des contrats de l'agroclimat AgERA5 (ADR-0040) : grandeurs, requêtes CDS,
conversions, maille et contrats."""

from __future__ import annotations

import pytest

from kuma_data_core.db.seeds.agroclimat_agera5_civ import (
    CONTRATS_AGERA5_JOURNALIERS,
    CONTRATS_AGERA5_MENSUELS,
    GRANDEURS_AGERA5,
    ZONE_CDS,
    maille_agera5,
    requete_cds,
    sur_une_limite,
)
from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.series_csv import nb_jours

pytestmark = pytest.mark.unit


def test_grandeurs() -> None:
    """Variable demandée, variable lue et unités de chaque grandeur."""
    assert {
        g.code: (
            g.variable_cds,
            g.statistique,
            g.variable_netcdf,
            g.unite_source,
            g.unite_referentiel,
        )
        for g in GRANDEURS_AGERA5.values()
    } == {
        "et0": (
            "reference_evapotranspiration",
            None,
            "ReferenceET_PenmanMonteith_FAO56",
            "mm d-1",
            "mm_par_jour",
        ),
        "t2m_min": (
            "2m_temperature",
            "24_hour_minimum",
            "Temperature_Air_2m_Min_24h",
            "K",
            "degree_celsius",
        ),
        "t2m_max": (
            "2m_temperature",
            "24_hour_maximum",
            "Temperature_Air_2m_Max_24h",
            "K",
            "degree_celsius",
        ),
        "vpd_tmax": (
            "vapour_pressure_deficit_at_maximum_temperature",
            None,
            "Vapour_Pressure_Deficit_at_Maximum_Temperature",
            "hPa",
            "kilopascal",
        ),
    }


def test_conversions() -> None:
    """K → °C, hPa → kPa, mm/jour inchangé."""
    assert GRANDEURS_AGERA5["t2m_max"].convertir(305.15) == pytest.approx(32.0)
    assert GRANDEURS_AGERA5["t2m_min"].convertir(273.15) == pytest.approx(0.0)
    assert GRANDEURS_AGERA5["vpd_tmax"].convertir(25.5) == pytest.approx(2.55)
    assert GRANDEURS_AGERA5["et0"].convertir(4.1234) == 4.1234


@pytest.mark.parametrize("grandeur", list(GRANDEURS_AGERA5))
def test_requete_cds(grandeur: str) -> None:
    """Une grandeur, une année, la zone de la CIV ; statistique pour la seule température."""
    r = requete_cds(2024, grandeur)
    g = GRANDEURS_AGERA5[grandeur]
    assert r["variable"] == [g.variable_cds]
    assert r.get("statistic") == ([g.statistique] if g.statistique else None)
    assert (r["year"], r["version"], r["area"]) == (["2024"], "2_0", list(ZONE_CDS))
    assert len(r["month"]) == 12 and len(r["day"]) == 31  # type: ignore[arg-type]


def test_maille() -> None:
    """Maille contenant le point ; une limite rattache au sud et à l'est."""
    assert maille_agera5(6.0, -4.0) == (60, -40)
    assert maille_agera5(9.41666667, -5.61666667) == (94, -56)
    assert maille_agera5(5.15, -4.4) == (51, -44)  # Jacqueville : limite en latitude
    assert maille_agera5(6.92, -5.05) == (69, -50)  # Bélier : limite en longitude
    assert maille_agera5(7.25, -3.86666667) == (72, -39)
    assert sur_une_limite(5.15, -4.4) and sur_une_limite(6.92, -5.05)
    assert not sur_une_limite(6.0, -4.0)


def test_mailles_des_142_localites() -> None:
    """119 mailles pour 142 localités, 38 localités sur une limite, toutes dans la zone."""
    points = points_nationaux()
    mailles = {maille_agera5(lat, lon) for _, _, lat, lon in points}
    assert len(points) == 142 and len(mailles) == 119
    assert sum(sur_une_limite(lat, lon) for _, _, lat, lon in points) == 38
    nord, ouest, sud, est = (round(c * 10) for c in ZONE_CDS)
    assert all(sud <= la < nord and ouest < lo <= est for la, lo in mailles)


@pytest.mark.parametrize("granularite", ["journalier", "mensuel"])
def test_contrats(granularite: str) -> None:
    contrats = (
        CONTRATS_AGERA5_JOURNALIERS if granularite == "journalier" else CONTRATS_AGERA5_MENSUELS
    )
    assert tuple(contrats) == ("et0", "t2m_min", "t2m_max", "vpd_tmax")
    plus_long = max(len(code) for code, _, _, _ in points_nationaux())
    for g, c in contrats.items():
        assert (c.source_code, c.source_id, c.methode_collecte) == ("agera5", 19, "reanalyse")
        assert (c.prefixe_code, c.grandeur_code, c.granularite) == (
            f"agera5_{g}_{granularite}",
            g,
            granularite,
        )
        assert (c.annee_debut, c.annee_fin, c.lacunes_admises) == (1991, 2025, False)
        assert c.libelle_grandeur == GRANDEURS_AGERA5[g].libelle
        assert len(c.code_serie("x" * plus_long)) <= 80  # series_metadonnees.code
    bornes = {g: c.borne_max for g, c in contrats.items()}
    if granularite == "journalier":
        assert bornes == {"et0": 15.0, "t2m_min": 50.0, "t2m_max": 50.0, "vpd_tmax": 10.0}
    else:
        assert bornes == {"et0": 15.0, "t2m_min": 45.0, "t2m_max": 45.0, "vpd_tmax": 10.0}
    assert nb_jours(CONTRATS_AGERA5_JOURNALIERS["et0"]) == 12_784
    assert CONTRATS_AGERA5_MENSUELS["et0"].nb_mois == 420
