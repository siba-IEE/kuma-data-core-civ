"""Tests unitaires des contrats journaliers ERA5 météo, CHIRPS v3 et CAMS Radiation.

Fonctions pures : moyenne journalière ERA5 (température, vitesse du vent),
rattachement d'une localité à sa maille CHIRPS de 0,05° (arithmétique exacte,
limites de maille), conversion de l'irradiation CAMS ; contrats (source,
période, bornes, lacunes).
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.meteo_era5_journaliere_civ import (
    CONTRATS_METEO_ERA5_JOURNALIERS,
    temperature_journaliere_c,
    vent_journalier,
)
from kuma_data_core.db.seeds.pluie_chirps_civ import (
    CONTRAT_PLUIE_CHIRPS,
    maille_chirps,
    sur_une_limite,
    url_cog,
    url_tif,
)
from kuma_data_core.db.seeds.rayonnement_cams_journalier_civ import (
    CONTRATS_CAMS_JOURNALIERS,
    kwh_par_jour,
)
from kuma_data_core.db.seeds.series_csv import nb_jours

pytestmark = pytest.mark.unit


def test_temperature_journaliere() -> None:
    """Moyenne des 24 heures en kelvins, ramenée en °C."""
    heures = [300.15] * 12 + [296.15] * 12
    assert temperature_journaliere_c(heures) == pytest.approx(25.0, abs=1e-12)
    with pytest.raises(ValueError, match="24"):
        temperature_journaliere_c(heures[:23])


def test_vent_journalier_moyenne_des_vitesses() -> None:
    """Moyenne des vitesses horaires, et non norme des composantes moyennes."""
    u = [3.0, -3.0] * 12  # direction qui s'inverse d'heure en heure
    v = [4.0, -4.0] * 12
    assert vent_journalier(u, v) == pytest.approx(5.0)
    assert math.hypot(sum(u) / 24, sum(v) / 24) == 0.0
    with pytest.raises(ValueError, match="24"):
        vent_journalier(u[:23], v[:23])


def test_contrats_era5_journaliers() -> None:
    assert sorted(CONTRATS_METEO_ERA5_JOURNALIERS) == ["t2m", "vent_10m"]
    for g, c in CONTRATS_METEO_ERA5_JOURNALIERS.items():
        assert (c.source_code, c.source_id, c.methode_collecte) == ("ecmwf_era5", 2, "reanalyse")
        assert c.prefixe_code == f"ecmwf_era5_{g}_journalier"
        assert (c.annee_debut, c.annee_fin, c.granularite) == (1991, 2025, "journalier")
        assert not c.lacunes_admises and nb_jours(c) == 12_784
    assert CONTRATS_METEO_ERA5_JOURNALIERS["t2m"].borne_max == 50.0
    assert CONTRATS_METEO_ERA5_JOURNALIERS["vent_10m"].borne_max == 30.0


@pytest.mark.parametrize(
    ("lat", "lon", "attendu", "limite"),
    [
        (5.33, -4.03, (1093, 3519), False),  # intérieur de maille
        (5.15, -4.4, (1097, 3512), True),  # sur une limite : maille au sud et à l'est
        (5.1499, -4.4001, (1097, 3511), False),
        (5.1501, -4.3999, (1096, 3512), False),
        (60.0, -180.0, (0, 0), True),  # coin nord-ouest de la grille
    ],
)
def test_maille_chirps(lat: float, lon: float, attendu: tuple[int, int], limite: bool) -> None:
    """Maille de 0,05° contenant le point ; limite rattachée au sud et à l'est."""
    assert maille_chirps(lat, lon) == attendu
    assert sur_une_limite(lat, lon) is limite


def test_maille_chirps_hors_grille() -> None:
    with pytest.raises(ValueError, match="hors de la grille"):
        maille_chirps(-60.0, 0.0)


def test_mailles_chirps_des_142_localites() -> None:
    """121 mailles distinctes ; 76 localités sur une limite de maille."""
    points = points_nationaux()
    assert len({maille_chirps(lat, lon) for _, _, lat, lon in points}) == 121
    assert sum(sur_une_limite(lat, lon) for _, _, lat, lon in points) == 76


def test_contrat_et_urls_chirps() -> None:
    c = CONTRAT_PLUIE_CHIRPS
    assert (c.source_code, c.source_id, c.prefixe_code) == (
        "chirps",
        18,
        "chirps_precipitation_journalier",
    )
    assert (c.annee_debut, c.annee_fin, c.borne_max, c.granularite) == (
        1991,
        2025,
        1000.0,
        "journalier",
    )
    assert url_cog(date(1992, 1, 1)).endswith("/rnl/cogs/1992/chirps-v3.0.rnl.1992.01.01.cog")
    assert url_tif(date(1992, 1, 1)).endswith("/final/rnl/1992/chirps-v3.0.rnl.1992.01.01.tif")


def test_contrats_cams_journaliers() -> None:
    assert sorted(CONTRATS_CAMS_JOURNALIERS) == ["dhi", "dni", "ghi"]
    for g, c in CONTRATS_CAMS_JOURNALIERS.items():
        assert (c.source_code, c.source_id, c.prefixe_code) == (
            "cams_radiation",
            13,
            f"cams_{g}_journalier",
        )
        assert (c.annee_debut, c.annee_fin, c.granularite) == (2005, 2025, "journalier")
        assert c.lacunes_admises and nb_jours(c) == 7_670
    assert [CONTRATS_CAMS_JOURNALIERS[g].borne_max for g in ("ghi", "dni", "dhi")] == [
        9.0,
        12.0,
        7.0,
    ]
    assert kwh_par_jour(5774.7021) == pytest.approx(5.7747021)
