"""Tests unitaires de la grandeur `productible_specifique_pr_std_thermique_mensuel`
(WP8 lecture climatique).
"""

from __future__ import annotations

import math

from kuma_data_core.services.grandeurs.productible_specifique_pr_std_thermique import (
    NB_MOIS,
    MesureJourGhiTamb,
    calculer_productible_specifique_pr_std_thermique_mensuel,
)

PR_STD = 0.78975
NOCT = 45.0
COEFF_TEMP = -0.4  # % / °C


NB_JOURS_MOIS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def _serie_annee(annee: int, ghi: float = 5.5, t_amb: float = 28.0) -> list[MesureJourGhiTamb]:
    """Fabrique une année de mesures constantes (365 jours simplifiés)."""
    mesures: list[MesureJourGhiTamb] = []
    for m in range(1, NB_MOIS + 1):
        for _ in range(NB_JOURS_MOIS[m - 1]):
            mesures.append(
                MesureJourGhiTamb(
                    annee=annee,
                    mois=m,
                    ghi_kwh_par_m2_jour=ghi,
                    t_amb_degc=t_amb,
                )
            )
    return mesures


def test_liste_de_12() -> None:
    res = calculer_productible_specifique_pr_std_thermique_mensuel(
        _serie_annee(1991), PR_STD, NOCT, COEFF_TEMP
    )
    assert len(res) == 12


def test_mois_sans_mesure_donne_zero() -> None:
    """Un mois absent des mesures doit produire 0.0 (pas NaN, pas erreur)."""
    mesures = [MesureJourGhiTamb(annee=1991, mois=1, ghi_kwh_par_m2_jour=5.0, t_amb_degc=25.0)]
    res = calculer_productible_specifique_pr_std_thermique_mensuel(
        mesures, PR_STD, NOCT, COEFF_TEMP
    )
    for i in range(1, 12):
        assert res[i] == 0.0
    assert res[0] > 0.0


def test_moyenne_sur_deux_annees_identiques_egale_une_annee() -> None:
    """Deux années strictement identiques -> mêmes 12 valeurs qu'une seule."""
    mesures_1a = _serie_annee(1991)
    mesures_2a = _serie_annee(1991) + _serie_annee(1992)
    r1 = calculer_productible_specifique_pr_std_thermique_mensuel(
        mesures_1a, PR_STD, NOCT, COEFF_TEMP
    )
    r2 = calculer_productible_specifique_pr_std_thermique_mensuel(
        mesures_2a, PR_STD, NOCT, COEFF_TEMP
    )
    for a, b in zip(r1, r2, strict=True):
        assert math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)


def test_ordre_de_grandeur_janvier_kankan_type() -> None:
    """Test de sanity : Kankan à 5.7 kWh/m²/j en janvier, 25°C ambiant type sec,
    NOCT 45, coeff -0.4 %/°C, PR_STD 0.78975. Sur 31 jours, on attend
    une centaine de kWh/kWc.
    """
    ghi = 5.7
    t_amb = 25.0
    mesures = [
        MesureJourGhiTamb(annee=1991, mois=1, ghi_kwh_par_m2_jour=ghi, t_amb_degc=t_amb)
        for _ in range(31)
    ]
    res = calculer_productible_specifique_pr_std_thermique_mensuel(
        mesures, PR_STD, NOCT, COEFF_TEMP
    )
    # Recalcul à la main pour vérification stricte :
    # t_cell = 25 + (45-20)/800 * (5.7*1000/24) = 25 + (25/800)*237.5 = 25 + 7.4218...
    irradiance_w = ghi * 1000.0 / 24.0
    t_cell = t_amb + (NOCT - 20.0) / 800.0 * irradiance_w
    ratio = 1.0 + COEFF_TEMP / 100.0 * (t_cell - 25.0)
    attendu_par_jour = ghi * PR_STD * ratio
    attendu_mois = attendu_par_jour * 31
    assert math.isclose(res[0], attendu_mois, rel_tol=1e-12)
    # Sanity : ordre de grandeur 120-160 kWh/kWc pour janvier chaud Kankan.
    assert 100.0 < res[0] < 200.0


def test_correction_thermique_reduit_la_production() -> None:
    """Avec T_amb 40°C au lieu de 15°C, la production doit être plus faible."""
    ghi = 6.0
    m_froid = [
        MesureJourGhiTamb(annee=1991, mois=4, ghi_kwh_par_m2_jour=ghi, t_amb_degc=15.0)
        for _ in range(30)
    ]
    m_chaud = [
        MesureJourGhiTamb(annee=1991, mois=4, ghi_kwh_par_m2_jour=ghi, t_amb_degc=40.0)
        for _ in range(30)
    ]
    r_froid = calculer_productible_specifique_pr_std_thermique_mensuel(
        m_froid, PR_STD, NOCT, COEFF_TEMP
    )
    r_chaud = calculer_productible_specifique_pr_std_thermique_mensuel(
        m_chaud, PR_STD, NOCT, COEFF_TEMP
    )
    assert r_chaud[3] < r_froid[3], "T_amb chaud doit réduire la production"


def test_toutes_valeurs_positives_pour_ghi_positif() -> None:
    res = calculer_productible_specifique_pr_std_thermique_mensuel(
        _serie_annee(1991), PR_STD, NOCT, COEFF_TEMP
    )
    for v in res:
        assert v >= 0.0


def test_puret_deterministe() -> None:
    """Appels répétés = même résultat (idempotence)."""
    m = _serie_annee(2000, ghi=5.2, t_amb=27.0)
    r1 = calculer_productible_specifique_pr_std_thermique_mensuel(m, PR_STD, NOCT, COEFF_TEMP)
    r2 = calculer_productible_specifique_pr_std_thermique_mensuel(m, PR_STD, NOCT, COEFF_TEMP)
    assert r1 == r2
