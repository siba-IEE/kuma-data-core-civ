"""Tests unitaires des contrats et du calcul de l'humidité relative ERA5 (ADR-0038).

Fonctions pures : pression de vapeur saturante de Tetens sur l'eau (constantes
d'ECMWF), humidité relative depuis la température et le point de rosée,
moyennes du jour et du mois des humidités horaires ; contrats (source, période,
granularité, bornes).
"""

from __future__ import annotations

import math

import pytest

from kuma_data_core.db.seeds.humidite_era5_civ import (
    CONTRAT_HUMIDITE_ERA5_JOURNALIER,
    CONTRAT_HUMIDITE_ERA5_MENSUEL,
    humidite_journaliere,
    humidite_mensuelle,
    humidite_relative,
    humidites_horaires,
    pression_vapeur_saturante_eau,
)
from kuma_data_core.db.seeds.series_csv import nb_jours

pytestmark = pytest.mark.unit


def test_pression_vapeur_saturante_eau() -> None:
    """611,21 Pa au point triple ; formule de Tetens à 30 °C, croissante avec T."""
    assert pression_vapeur_saturante_eau(273.16) == 611.21
    attendu = 611.21 * math.exp(17.502 * (303.15 - 273.16) / (303.15 - 32.19))
    assert pression_vapeur_saturante_eau(303.15) == pytest.approx(attendu, rel=1e-15)
    assert 4_200 < pression_vapeur_saturante_eau(303.15) < 4_300  # environ 42,4 hPa
    assert pression_vapeur_saturante_eau(300.0) < pression_vapeur_saturante_eau(301.0)


def test_humidite_relative() -> None:
    """100 % quand Td = T ; proche de la formule de Magnus ; jamais écrêtée."""
    assert humidite_relative(300.0, 300.0) == 100.0
    hr = humidite_relative(303.15, 297.15)  # 30 °C, point de rosée 24 °C
    magnus = 100 * math.exp(17.67 * 24 / (24 + 243.5)) / math.exp(17.67 * 30 / (30 + 243.5))
    assert hr == pytest.approx(magnus, abs=0.2)
    assert 70 < hr < 71
    assert humidite_relative(300.0, 300.05) > 100.0  # sursaturation servie : pas d'écrêtage


def test_moyennes_des_humidites_horaires() -> None:
    """Le jour : 24 heures ; le mois : 24 heures par jour ; moyenne des humidités."""
    t = [300.0] * 24
    td = [300.0] * 12 + [290.0] * 12
    horaires = humidites_horaires(t, td)
    assert horaires[:12] == [100.0] * 12
    assert humidite_journaliere(horaires) == pytest.approx(
        (100.0 + humidite_relative(300.0, 290.0)) / 2, abs=1e-12
    )
    # Moyenne des humidités, et non humidité des moyennes (formule non linéaire).
    assert humidite_journaliere(horaires) > humidite_relative(300.0, 295.0)
    with pytest.raises(ValueError, match="24"):
        humidite_journaliere(horaires[:23])
    assert humidite_mensuelle([50.0] * 24 * 28 + [80.0] * 24 * 2, 30) == pytest.approx(52.0)
    with pytest.raises(ValueError, match="720"):
        humidite_mensuelle([50.0] * 24 * 29, 30)
    with pytest.raises(ValueError):
        humidites_horaires([300.0], [])


def test_contrats_humidite_era5() -> None:
    for contrat, granularite in (
        (CONTRAT_HUMIDITE_ERA5_JOURNALIER, "journalier"),
        (CONTRAT_HUMIDITE_ERA5_MENSUEL, "mensuel"),
    ):
        assert (contrat.source_code, contrat.source_id, contrat.methode_collecte) == (
            "ecmwf_era5",
            2,
            "reanalyse",
        )
        assert contrat.prefixe_code == f"ecmwf_era5_rh2m_{granularite}"
        assert (contrat.grandeur_code, contrat.granularite) == ("rh2m", granularite)
        assert (contrat.annee_debut, contrat.annee_fin, contrat.borne_max) == (1991, 2025, 100.0)
        assert contrat.libelle_grandeur == "Humidité relative à 2 m"
        assert not contrat.lacunes_admises
    assert nb_jours(CONTRAT_HUMIDITE_ERA5_JOURNALIER) == 12_784
    assert CONTRAT_HUMIDITE_ERA5_MENSUEL.nb_mois == 420
    assert CONTRAT_HUMIDITE_ERA5_JOURNALIER.nom_fichier("civ142") == (
        "ecmwf_era5_rh2m_journalier_civ142.csv.gz"
    )
