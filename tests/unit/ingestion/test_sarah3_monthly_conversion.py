"""Tests unitaires de la conversion H(h)_m cumul mensuel -> moyenne quotidienne.

Couvre la fonction privee ``_extraire_valeurs_mensuelles`` qui convertit
les valeurs natives PVGIS-SARAH3 (cumul mensuel kWh/m^2/mois) en moyenne
quotidienne kWh/m^2/jour par division par le nombre exact de jours du
mois (``calendar.monthrange``, gere les annees bissextiles).

Verifie 3 cas representatifs apres fix bug agregation mensuelle :

- T-CONV-SARAH3-1 : mois standard 31 jours (janvier).
- T-CONV-SARAH3-2 : fevrier annee bissextile 29 jours (2024).
- T-CONV-SARAH3-3 : fevrier annee non-bissextile 28 jours (2022).

Couverture supplementaire :

- T-CONV-SARAH3-4 : payload multi-mois retourne les 12 valeurs converties
  dans l'ordre.
- T-CONV-SARAH3-5 : entree avec H(h)_m manquant est ignoree silencieusement
  (preserve la robustesse historique).
"""

from __future__ import annotations

import pytest

from kuma_data_core.ingestion.sarah3_monthly import _extraire_valeurs_mensuelles

pytestmark = pytest.mark.unit


def test_t_conv_sarah3_1_mois_31_jours() -> None:
    """T-CONV-SARAH3-1 : 186.0 kWh/m^2/mois en janvier -> 6.0 kWh/m^2/jour."""
    payload = {
        "outputs": {
            "monthly": [{"year": 2022, "month": 1, "H(h)_m": 186.0}],
        },
    }
    valeurs = _extraire_valeurs_mensuelles(payload)
    assert valeurs == [(2022, 1, 6.0)]


def test_t_conv_sarah3_2_fevrier_bissextile_29_jours() -> None:
    """T-CONV-SARAH3-2 : 145.0 kWh/m^2/mois en fevrier 2024 -> 5.0 kWh/m^2/jour."""
    payload = {
        "outputs": {
            "monthly": [{"year": 2024, "month": 2, "H(h)_m": 145.0}],
        },
    }
    valeurs = _extraire_valeurs_mensuelles(payload)
    assert valeurs == [(2024, 2, 5.0)]


def test_t_conv_sarah3_3_fevrier_non_bissextile_28_jours() -> None:
    """T-CONV-SARAH3-3 : 140.0 kWh/m^2/mois en fevrier 2022 -> 5.0 kWh/m^2/jour."""
    payload = {
        "outputs": {
            "monthly": [{"year": 2022, "month": 2, "H(h)_m": 140.0}],
        },
    }
    valeurs = _extraire_valeurs_mensuelles(payload)
    assert valeurs == [(2022, 2, 5.0)]


def test_t_conv_sarah3_4_payload_12_mois_complet() -> None:
    """T-CONV-SARAH3-4 : 12 mois retournes dans l'ordre, chacun converti."""
    cumuls_par_mois = {
        1: 186.0,  # 31j -> 6.0
        2: 140.0,  # 28j -> 5.0 (non-bissextile)
        3: 217.0,  # 31j -> 7.0
        4: 180.0,  # 30j -> 6.0
        5: 186.0,  # 31j -> 6.0
        6: 150.0,  # 30j -> 5.0
        7: 124.0,  # 31j -> 4.0
        8: 124.0,  # 31j -> 4.0
        9: 150.0,  # 30j -> 5.0
        10: 186.0,  # 31j -> 6.0
        11: 180.0,  # 30j -> 6.0
        12: 186.0,  # 31j -> 6.0
    }
    payload = {
        "outputs": {
            "monthly": [
                {"year": 2022, "month": mois, "H(h)_m": cumul}
                for mois, cumul in cumuls_par_mois.items()
            ],
        },
    }
    valeurs = _extraire_valeurs_mensuelles(payload)
    assert len(valeurs) == 12
    # Verification echantillonnee : 1er, fevrier non-bissextile, 7e, dernier
    assert valeurs[0] == (2022, 1, 6.0)
    assert valeurs[1] == (2022, 2, 5.0)
    assert valeurs[6] == (2022, 7, 4.0)
    assert valeurs[11] == (2022, 12, 6.0)


def test_t_conv_sarah3_5_entree_sans_h_h_m_est_ignoree() -> None:
    """T-CONV-SARAH3-5 : H(h)_m manquant -> entree silencieusement filtree."""
    payload = {
        "outputs": {
            "monthly": [
                {"year": 2022, "month": 1, "H(h)_m": 186.0},
                {"year": 2022, "month": 2},  # H(h)_m absent
                {"year": 2022, "month": 3, "H(h)_m": 217.0},
            ],
        },
    }
    valeurs = _extraire_valeurs_mensuelles(payload)
    assert valeurs == [(2022, 1, 6.0), (2022, 3, 7.0)]
