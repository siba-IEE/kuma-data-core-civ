"""Tests unitaires du module ``services.grandeurs.referentiels``.

7 tests T-1 a T-7 sur les fonctions pures.
Orchestrateur ``calculer_et_inserer_referentiels`` teste en integration.
"""

from __future__ import annotations

import pytest

from kuma_data_core.services.grandeurs.referentiels import (
    _agreger_mensuel,
    _calcul_ecart_relatif,
    _calcul_rang_spatial,
    _calcul_rang_temporel,
)

pytestmark = pytest.mark.unit


def test_t1_agreger_mensuel_moyenne_basique() -> None:
    """T-1 : moyenne arithmetique sur 31 valeurs (mois complet)."""
    valeurs = [5.0] * 31
    assert _agreger_mensuel(valeurs) == pytest.approx(5.0)

    valeurs_var = [4.0, 5.0, 6.0]
    assert _agreger_mensuel(valeurs_var) == pytest.approx(5.0)


def test_t2_agreger_mensuel_vide_rejete() -> None:
    """T-2 : sequence vide -> ValueError."""
    with pytest.raises(ValueError, match="Aucune valeur"):
        _agreger_mensuel([])


def test_t3_calcul_ecart_relatif_signe() -> None:
    """T-3 : ecart relatif signe (positif si kuma > sarah3, negatif sinon).

    Cas typique : Kuma NASA POWER 5.5 kWh/m^2/j Conakry,
    SARAH-3 ICDR 5.3 kWh/m^2/j. Ecart positif petit +3.8%.
    """
    ecart = _calcul_ecart_relatif(valeur_kuma=5.5, valeur_sarah3=5.3)
    assert ecart == pytest.approx(3.7735849, rel=1e-5)

    # Cas inverse : Kuma sous-estime SARAH-3
    ecart_negatif = _calcul_ecart_relatif(valeur_kuma=5.0, valeur_sarah3=5.5)
    assert ecart_negatif == pytest.approx(-9.0909, rel=1e-3)

    # Cas egalite
    assert _calcul_ecart_relatif(valeur_kuma=5.0, valeur_sarah3=5.0) == pytest.approx(0.0)


def test_t4_calcul_ecart_relatif_sarah3_nul_rejete() -> None:
    """T-4 : division par zero rejete (cas theorique de robustesse)."""
    with pytest.raises(ValueError, match="valeur SARAH-3 nulle"):
        _calcul_ecart_relatif(valeur_kuma=5.0, valeur_sarah3=0.0)


def test_t5_calcul_rang_temporel_mediane_50() -> None:
    """T-5 : valeur a la mediane d'une distribution -> percentile 50.

    Distribution n=30 (climatologie 1991-2020 typique) : valeurs 1..30.
    Mediane = 15.5. Valeur 15 ou 16 -> percentile 50.
    """
    distribution = list(range(1, 31))  # 1..30, mediane = 15.5
    # Valeur exactement entre rangs 15 et 16
    percentile_15_5 = _calcul_rang_temporel(15.5, distribution)
    # rang = 15 strict_inf + 0 egal = 15 (avec demi-rang : 15 + 0.5 = 15.5)
    # En realite valeur 15.5 n'est pas dans la distrib donc nb_egaux=0
    # rang = 15 + (0+1)/2 = 15.5 -> percentile = 14.5 / 29 * 100 = 50%
    assert percentile_15_5 == pytest.approx(50.0, abs=0.01)


def test_t6_calcul_rang_temporel_capping() -> None:
    """T-6 : capping 0/100 hors plage haute et basse + n<2 rejete."""
    distribution = [10.0, 20.0, 30.0]
    # Valeur tres en-dessous -> 0
    assert _calcul_rang_temporel(5.0, distribution) == pytest.approx(0.0)
    # Valeur tres au-dessus -> 100
    assert _calcul_rang_temporel(100.0, distribution) == pytest.approx(100.0)

    # n=1 rejete
    with pytest.raises(ValueError, match="Distribution insuffisante"):
        _calcul_rang_temporel(5.0, [10.0])

    # n=0 rejete
    with pytest.raises(ValueError, match="Distribution insuffisante"):
        _calcul_rang_temporel(5.0, [])


def test_t7_calcul_rang_spatial_6_villes() -> None:
    """T-7 : rang ordinal 1-6 sur 6 villes (tri croissant).

    Cas typique : 6 villes avec valeurs GHI mensuelles distinctes.
    """
    valeurs = {
        56: 4.5,  # Conakry  -> rang 1 (le plus bas)
        51: 5.8,  # Kankan   -> rang 6 (le plus haut)
        52: 5.0,  # Kindia   -> rang 3
        53: 4.7,  # Labe     -> rang 2
        54: 5.2,  # Mamou    -> rang 4
        55: 5.5,  # Nzerekore-> rang 5
    }
    rangs = _calcul_rang_spatial(valeurs)
    assert rangs[56] == 1
    assert rangs[53] == 2
    assert rangs[52] == 3
    assert rangs[54] == 4
    assert rangs[55] == 5
    assert rangs[51] == 6

    # Dict vide rejete
    with pytest.raises(ValueError, match="Aucune valeur"):
        _calcul_rang_spatial({})
