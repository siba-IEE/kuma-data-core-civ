"""Tests unitaires de ``services.grandeurs.pr_realiste``.

Couvre le PR realiste = PR_fourni x ratio_T x (1 - salissure) selon le mode de
correction. Fonction pure sans mock DB. Invariants : ``aucune``
echo ; ``temperature`` degrade en climat chaud ; ``salissure`` degrade quand PM↑ et
remonte apres pluie ; ``temperature_salissure`` = produit ; composition exacte avec
``calculer_taux_salissure_proxy`` ; bornes.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from kuma_data_core.services.grandeurs.pr_realiste import (
    MesureJourPRRealiste,
    calculer_pr_realiste,
)
from kuma_data_core.services.grandeurs.soiling_hsu import (
    MesureEntreeSoiling,
    calculer_taux_salissure_proxy,
)

pytestmark = pytest.mark.unit

_BASE = date(2021, 1, 1)
_PR = 0.80
_NOCT = 45.0
_GAMMA = -0.4  # %/°C


def _mesure(
    jour: date,
    ghi: float | None = None,
    t_amb: float | None = None,
    rain: float | None = None,
    pm2_5: float | None = None,
    pm10: float | None = None,
) -> MesureJourPRRealiste:
    return {
        "instant_mesure": jour,
        "ghi_kwh_par_m2_jour": ghi,
        "t_amb_degc": t_amb,
        "rainfall_mm": rain,
        "pm2_5": pm2_5,
        "pm10": pm10,
    }


def _jours(n: int) -> list[date]:
    return [_BASE + timedelta(days=i) for i in range(n)]


def test_vide() -> None:
    """Mesures vides -> resultat vide, caveat present."""
    r = calculer_pr_realiste([], _PR, "temperature_salissure", _NOCT, _GAMMA)
    assert r.mesures == []
    assert "PR-reference" in r.limite


def test_aucune_echo() -> None:
    """Mode 'aucune' -> pr_realiste == PR_fourni (echo, baseline)."""
    mesures = [_mesure(j) for j in _jours(10)]
    r = calculer_pr_realiste(mesures, _PR, "aucune")
    assert all(abs(m.pr_realiste - _PR) < 1e-12 for m in r.mesures)
    assert all(m.niveau_confiance == "B" for m in r.mesures)


def test_temperature_degrade_en_climat_chaud() -> None:
    """Climat chaud (T_amb 30, G eleve) -> ratio_T < 1 -> pr_realiste < PR_fourni."""
    mesures = [_mesure(j, ghi=6.0, t_amb=30.0) for j in _jours(10)]
    r = calculer_pr_realiste(mesures, _PR, "temperature", _NOCT, _GAMMA)
    assert all(m.pr_realiste < _PR for m in r.mesures)


def test_salissure_degrade_et_reset_apres_pluie() -> None:
    """PM eleves -> pr_realiste < PR_fourni (sf < 1) ; pluie > seuil -> remonte vers PR_fourni."""
    jours = _jours(60)
    mesures = [
        _mesure(j, rain=(5.0 if i == 30 else 0.0), pm2_5=80.0, pm10=130.0)
        for i, j in enumerate(jours)
    ]
    r = calculer_pr_realiste(mesures, _PR, "salissure")
    prs = [m.pr_realiste for m in r.mesures]
    assert all(p <= _PR + 1e-12 for p in prs)  # salissure ne peut qu'abaisser
    assert prs[29] < _PR  # salissure accumulee
    assert prs[30] > prs[29]  # nettoyage par la pluie
    assert abs(prs[30] - _PR) < 1e-9  # ~ propre apres reset


def test_temperature_salissure_est_le_produit() -> None:
    """temperature_salissure = PR_fourni x ratio_T x sf = temp x sal / PR_fourni."""
    jours = _jours(40)
    mesures = [_mesure(j, ghi=6.0, t_amb=30.0, rain=0.0, pm2_5=60.0, pm10=100.0) for j in jours]
    temp = calculer_pr_realiste(mesures, _PR, "temperature", _NOCT, _GAMMA).mesures
    sal = calculer_pr_realiste(mesures, _PR, "salissure").mesures
    ts = calculer_pr_realiste(mesures, _PR, "temperature_salissure", _NOCT, _GAMMA).mesures
    for i in range(len(jours)):
        attendu = temp[i].pr_realiste * sal[i].pr_realiste / _PR
        assert abs(ts[i].pr_realiste - attendu) < 1e-9


def test_composition_exacte_avec_taux_salissure_proxy() -> None:
    """Le facteur salissure = exactement (1 - perte_pct/100) du proxy de salissure."""
    jours = _jours(40)
    mesures = [_mesure(j, rain=0.0, pm2_5=70.0, pm10=115.0) for j in jours]
    sal = calculer_pr_realiste(mesures, _PR, "salissure").mesures
    entrees: list[MesureEntreeSoiling] = [
        {"instant_mesure": j, "rainfall_mm": 0.0, "pm2_5": 70.0, "pm10": 115.0} for j in jours
    ]
    soiling = calculer_taux_salissure_proxy(entrees).mesures
    for i in range(len(jours)):
        attendu = _PR * (1.0 - soiling[i].perte_pct / 100.0)
        assert abs(sal[i].pr_realiste - attendu) < 1e-9


def test_borne_basse_positive() -> None:
    """pr_realiste >= 0 (borne basse douce)."""
    mesures = [
        _mesure(j, ghi=7.0, t_amb=45.0, rain=0.0, pm2_5=200.0, pm10=320.0) for j in _jours(20)
    ]
    r = calculer_pr_realiste(mesures, _PR, "temperature_salissure", _NOCT, _GAMMA)
    assert all(m.pr_realiste >= 0.0 for m in r.mesures)


def test_temperature_sans_noct_gamma_rejete() -> None:
    """Mode thermique sans noct/gamma -> ValueError."""
    mesures = [_mesure(j, ghi=6.0, t_amb=30.0) for j in _jours(5)]
    with pytest.raises(ValueError, match="noct_degc"):
        calculer_pr_realiste(mesures, _PR, "temperature")
