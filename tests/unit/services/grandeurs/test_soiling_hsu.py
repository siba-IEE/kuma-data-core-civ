"""Tests unitaires de ``services.grandeurs.soiling_hsu``.

Couvre le proxy de salissure (modele HSU, pvlib). Fonction pure
sans mock DB. Invariants : PM croissant -> perte croissante ; pluie au-dela du seuil
-> perte remise vers 0 ; perte = (1 - ratio) x 100 bornee [0, 100] ; spin-up (perte
quasi nulle au tout premier jour) ; conversion µg/m³ -> g/m³ (garde-fou).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from kuma_data_core.services.grandeurs.soiling_hsu import (
    MesureEntreeSoiling,
    calculer_taux_salissure_proxy,
)

pytestmark = pytest.mark.unit

_BASE = date(2021, 1, 1)


def _mesures(n: int, rainfall: list[float], pm2_5: float, pm10: float) -> list[MesureEntreeSoiling]:
    """n jours contigus, PM constants (µg/m³), pluie fournie par jour (mm)."""
    return [
        MesureEntreeSoiling(
            instant_mesure=_BASE + timedelta(days=i),
            rainfall_mm=rainfall[i],
            pm2_5=pm2_5,
            pm10=pm10,
        )
        for i in range(n)
    ]


def test_vide() -> None:
    """Mesures vides -> resultat vide, caveat present."""
    r = calculer_taux_salissure_proxy([])
    assert r.mesures == []
    assert "spin-up" in r.limite


def test_pertes_bornees_et_coherentes() -> None:
    """Perte = (1 - ratio) x 100, bornee [0, 100], confiance B, 1 par jour."""
    r = calculer_taux_salissure_proxy(_mesures(60, [0.0] * 60, pm2_5=40.0, pm10=70.0))
    assert len(r.mesures) == 60
    for m in r.mesures:
        assert 0.0 <= m.perte_pct <= 100.0
        assert m.niveau_confiance == "B"


def test_pm_croissant_perte_croissante() -> None:
    """PM plus eleve -> perte de salissure plus forte (sur fenetre seche identique)."""
    sec = [0.0] * 60
    perte_basse = max(
        m.perte_pct
        for m in calculer_taux_salissure_proxy(_mesures(60, sec, pm2_5=20.0, pm10=35.0)).mesures
    )
    perte_haute = max(
        m.perte_pct
        for m in calculer_taux_salissure_proxy(_mesures(60, sec, pm2_5=90.0, pm10=150.0)).mesures
    )
    assert perte_haute > perte_basse


def test_pluie_au_dela_du_seuil_remet_vers_zero() -> None:
    """Une journee de pluie > seuil nettoie : perte 0 ce jour, < la veille."""
    rain = [0.0] * 60
    rain[30] = 5.0  # 5 mm > seuil 1 mm
    pertes = [
        m.perte_pct
        for m in calculer_taux_salissure_proxy(_mesures(60, rain, pm2_5=50.0, pm10=85.0)).mesures
    ]
    assert pertes[30] < 0.05, f"reset attendu au jour de pluie, perte={pertes[30]}"
    assert pertes[29] > pertes[30], "la perte doit chuter au jour de pluie"


def test_spin_up_premier_jour_quasi_nul() -> None:
    """Spin-up : HSU demarre propre, perte quasi nulle au tout premier jour."""
    r = calculer_taux_salissure_proxy(_mesures(60, [0.0] * 60, pm2_5=50.0, pm10=85.0))
    assert r.mesures[0].perte_pct < 0.5, f"premier jour non quasi-propre : {r.mesures[0].perte_pct}"


def test_conversion_ug_vers_g_garde_fou() -> None:
    """Garde-fou conversion µg/m³ -> g/m³ : a 30 µg/m³ la perte reste de l'ordre du %
    (< 5 % sur un mois sec), pas 34 % (ce qu'on aurait sans conversion)."""
    perte_max = max(
        m.perte_pct
        for m in calculer_taux_salissure_proxy(
            _mesures(60, [0.0] * 60, pm2_5=30.0, pm10=50.0)
        ).mesures
    )
    assert perte_max < 5.0, (
        f"perte {perte_max:.1f}% implausible : la conversion µg/m³ -> g/m³ a-t-elle saute ?"
    )
