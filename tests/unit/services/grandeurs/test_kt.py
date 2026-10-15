"""Tests unitaires de ``services.grandeurs.kt`` (indice de clarté, fonctions pures).

Couvre :

- T-KT-1, T-KT-2 : valeurs de référence publiées de Duffie & Beckman (5ᵉ éd.,
  2020) — exemple 1.10.1 et table 1.10.1 (``H0`` moyen mensuel, MJ/m², aux
  latitudes 0°, 5°N, 10°N et 15°N), reproduites avec la convention du livre
  (Cooper 1969, ``1 + 0,033 cos``, ``Gsc = 1367 W/m²``) ;
- T-KT-3, T-KT-4 : formules de Spencer et de Cooper recoupées avec une
  implémentation indépendante (pvlib) ;
- T-KT-5 à T-KT-7 : cas limites géométriques (équateur, nuit et jour polaires,
  moyenne mensuelle sur les jours civils, février bissextile) ;
- T-KT-8 à T-KT-11 : ``kt`` mensuel et annuel (rapport de sommes pondéré par
  les jours, complétude stricte), ``calculer_kt``, effet de la constante solaire ;
- T-KT-12 : écart borné entre la convention retenue (Spencer, 1361 W/m²) et
  la table de Duffie & Beckman à 5°N et 10°N.

Fonctions pures, aucun accès base ni réseau.
"""

from __future__ import annotations

import calendar
import math
from datetime import date, timedelta

import numpy as np
import pvlib  # type: ignore[import-untyped]
import pytest

from kuma_data_core.services.grandeurs.kt import (
    CONSTANTE_SOLAIRE_DUFFIE_BECKMAN_W_M2,
    CONSTANTE_SOLAIRE_W_M2,
    angle_horaire_coucher,
    calculer_kt,
    declinaison,
    facteur_excentricite,
    h0_journalier,
    h0_mensuel,
    h0_rang,
    kt_annuel,
    kt_mensuel,
)

pytestmark = pytest.mark.unit

MJ_PAR_KWH: float = 3.6

# Duffie & Beckman, Solar Engineering of Thermal Processes, 5ᵉ éd. (2020),
# table 1.10.1 « Monthly Average Daily Extraterrestrial Radiation, MJ/m² », p. 40.
TABLE_1_10_1: dict[int, tuple[float, ...]] = {
    15: (29.6, 32.6, 35.9, 38.0, 38.5, 38.4, 38.3, 38.0, 36.4, 33.4, 30.1, 28.5),
    10: (32.0, 34.4, 36.8, 37.9, 37.5, 37.0, 37.1, 37.5, 37.0, 35.0, 32.4, 31.1),
    5: (34.2, 36.0, 37.5, 37.4, 36.3, 35.3, 35.6, 36.7, 37.2, 36.3, 34.5, 33.5),
    0: (36.2, 37.4, 37.8, 36.7, 34.8, 33.5, 34.0, 35.7, 37.2, 37.3, 36.3, 35.7),
}


def _h0_duffie_beckman_mj(latitude: float, mois: int) -> float:
    """``H0`` mensuel (MJ/m²) dans la convention du livre, année non bissextile."""
    return (
        h0_mensuel(
            latitude,
            2001,
            mois,
            constante_solaire=CONSTANTE_SOLAIRE_DUFFIE_BECKMAN_W_M2,
            modele="cooper",
        )
        * MJ_PAR_KWH
    )


# --- Références publiées -----------------------------------------------------


def test_t_kt_1_exemple_1_10_1_duffie_beckman() -> None:
    """T-KT-1 : 43°N, 15 avril (n = 105), Gsc = 1367 W/m² → H0 = 33,8 MJ/m²."""
    h0_mj = h0_rang(43.0, 105, constante_solaire=1367.0, modele="cooper") * MJ_PAR_KWH
    assert h0_mj == pytest.approx(33.8, abs=0.05)
    # Étapes intermédiaires de l'exemple : δ = 9,4° et ωs = 98,9°.
    assert math.degrees(declinaison(105, "cooper")) == pytest.approx(9.4, abs=0.05)
    ws = angle_horaire_coucher(math.radians(43.0), declinaison(105, "cooper"))
    assert math.degrees(ws) == pytest.approx(98.9, abs=0.05)


@pytest.mark.parametrize("latitude", sorted(TABLE_1_10_1))
def test_t_kt_2_table_1_10_1_duffie_beckman(latitude: int) -> None:
    """T-KT-2 : moyenne des H0 journaliers du mois = table 1.10.1, à l'arrondi près.

    La table est imprimée au dixième de MJ/m² : l'écart toléré est d'un demi
    dixième. Elle correspond à une année non bissextile (2001 ici).
    """
    for mois, attendu in enumerate(TABLE_1_10_1[latitude], start=1):
        assert _h0_duffie_beckman_mj(latitude, mois) == pytest.approx(attendu, abs=0.05), (
            latitude,
            mois,
        )


# --- Recoupement avec une implémentation indépendante (pvlib) ----------------


@pytest.mark.parametrize("latitude", [4.42, 5.41667, 7.5, 10.4869, -12.0])
def test_t_kt_3_spencer_recoupe_pvlib(latitude: float) -> None:
    """T-KT-3 : modèle Spencer (défaut) = pvlib (declination_spencer71, spencer)."""
    rangs = np.arange(1, 367)
    delta = pvlib.solarposition.declination_spencer71(rangs)
    g_on = pvlib.irradiance.get_extra_radiation(
        rangs, solar_constant=CONSTANTE_SOLAIRE_W_M2, method="spencer"
    )
    phi = np.radians(latitude)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(delta), -1.0, 1.0))
    attendu = (
        24.0
        / np.pi
        * g_on
        * (np.cos(phi) * np.cos(delta) * np.sin(ws) + ws * np.sin(phi) * np.sin(delta))
        / 1000.0
    )
    obtenu = np.array([h0_rang(latitude, int(n)) for n in rangs])
    np.testing.assert_allclose(obtenu, attendu, rtol=1e-12)


def test_t_kt_4_cooper_recoupe_pvlib() -> None:
    """T-KT-4 : modèle Cooper = pvlib (declination_cooper69, méthode « asce »)."""
    rangs = np.arange(1, 366)
    np.testing.assert_allclose(
        [declinaison(int(n), "cooper") for n in rangs],
        pvlib.solarposition.declination_cooper69(rangs),
        rtol=1e-12,
        atol=1e-15,
    )
    np.testing.assert_allclose(
        [facteur_excentricite(int(n), "cooper") for n in rangs],
        pvlib.irradiance.get_extra_radiation(rangs, solar_constant=1.0, method="asce"),
        rtol=1e-12,
    )


# --- Géométrie : cas limites -------------------------------------------------


def test_t_kt_5_equateur() -> None:
    """T-KT-5 : à l'équateur, ωs = 90° et H0 = (24/π)·Gsc·E0·cos δ."""
    for n in (1, 80, 172, 266, 355):
        assert angle_horaire_coucher(0.0, declinaison(n)) == pytest.approx(math.pi / 2)
        attendu = 24 / math.pi * 1361.0 * facteur_excentricite(n) * math.cos(declinaison(n)) / 1e3
        assert h0_rang(0.0, n) == pytest.approx(attendu, rel=1e-12)


def test_t_kt_6_nuit_et_jour_polaires() -> None:
    """T-KT-6 : ``cos ωs`` borné — H0 nul en nuit polaire, soleil permanent en jour polaire."""
    assert angle_horaire_coucher(math.radians(80.0), math.radians(-23.0)) == 0.0
    assert angle_horaire_coucher(math.radians(80.0), math.radians(23.0)) == math.pi
    assert h0_rang(80.0, 355) == pytest.approx(0.0, abs=1e-12)
    # Jour polaire : H0 = (24/π)·Gsc·E0·π·sin φ sin δ.
    n = 172
    attendu = (
        24
        * 1361.0
        * facteur_excentricite(n)
        * math.sin(math.radians(80.0))
        * math.sin(declinaison(n))
        / 1e3
    )
    assert h0_rang(80.0, n) == pytest.approx(attendu, rel=1e-12)


def test_t_kt_7_moyenne_mensuelle_et_bissextile() -> None:
    """T-KT-7 : H0 mensuel = moyenne des jours civils ; février bissextile à 29 jours."""
    for annee in (2023, 2024):
        nb = calendar.monthrange(annee, 2)[1]
        jours = [date(annee, 2, 1) + timedelta(days=i) for i in range(nb)]
        attendu = math.fsum(h0_journalier(5.4, j) for j in jours) / nb
        assert h0_mensuel(5.4, annee, 2) == pytest.approx(attendu, rel=1e-14)
    assert h0_mensuel(5.4, 2024, 2) != h0_mensuel(5.4, 2023, 2)
    # Seule la bissextilité compte : deux années communes donnent le même H0.
    assert h0_mensuel(5.4, 2021, 7) == h0_mensuel(5.4, 2023, 7)
    with pytest.raises(ValueError):
        h0_mensuel(5.4, 2023, 13)


# --- Indice de clarté --------------------------------------------------------


def test_t_kt_8_kt_mensuel() -> None:
    """T-KT-8 : ``kt`` mensuel = GHI moyen / H0 moyen ; H0 non positif refusé."""
    assert kt_mensuel(5.0, 10.0) == 0.5
    with pytest.raises(ValueError):
        kt_mensuel(1.0, 0.0)


def test_t_kt_9_kt_annuel_rapport_de_sommes() -> None:
    """T-KT-9 : annuel = Σ GHI·n / Σ H0·n (pondéré par les jours), ≠ moyenne des rapports."""
    ghi = {m: 4.0 + 0.2 * m for m in range(1, 13)}
    h0 = {m: h0_mensuel(9.4, 2024, m) for m in range(1, 13)}
    jours = {m: calendar.monthrange(2024, m)[1] for m in range(1, 13)}
    attendu = sum(ghi[m] * jours[m] for m in ghi) / sum(h0[m] * jours[m] for m in h0)
    assert kt_annuel(ghi, h0, 2024) == pytest.approx(attendu, rel=1e-14)
    moyenne_des_rapports = sum(ghi[m] / h0[m] for m in ghi) / 12
    assert abs(kt_annuel(ghi, h0, 2024) - moyenne_des_rapports) > 1e-4
    del ghi[7]
    with pytest.raises(ValueError):
        kt_annuel(ghi, h0, 2024)


def test_t_kt_10_calculer_kt_completude() -> None:
    """T-KT-10 : 12 mensuelles + 1 annuelle par année complète ; année incomplète sans annuel."""
    ghi = {(2005, m): 5.0 for m in range(1, 13)} | {(2006, m): 4.5 for m in range(1, 7)}
    lignes = calculer_kt(ghi, 6.83)
    assert [(lg["periode_type"], lg["annee"], lg["mois"]) for lg in lignes] == (
        [("mensuel", 2005, m) for m in range(1, 13)]
        + [("annuel", 2005, None)]
        + [("mensuel", 2006, m) for m in range(1, 7)]
    )
    for lg in lignes:
        if lg["mois"] is not None:
            attendu = ghi[(lg["annee"], lg["mois"])] / h0_mensuel(6.83, lg["annee"], lg["mois"])
            assert lg["valeur"] == attendu
    h0 = {m: h0_mensuel(6.83, 2005, m) for m in range(1, 13)}
    assert lignes[12]["valeur"] == kt_annuel(dict.fromkeys(range(1, 13), 5.0), h0, 2005)


def test_t_kt_11_effet_constante_solaire() -> None:
    """T-KT-11 : kt ∝ 1/Gsc — 1367 W/m² donne des kt 0,44 % plus bas que 1361 W/m²."""
    ghi = {(2010, m): 5.2 for m in range(1, 13)}
    k_1361 = calculer_kt(ghi, 7.69)
    k_1367 = calculer_kt(ghi, 7.69, constante_solaire=1367.0)
    for a, b in zip(k_1361, k_1367, strict=True):
        assert b["valeur"] == pytest.approx(a["valeur"] * 1361.0 / 1367.0, rel=1e-12)
    reduction = 1 - 1361.0 / 1367.0
    assert reduction == pytest.approx(0.0044, abs=1e-4)


@pytest.mark.parametrize("latitude", [5, 10])
def test_t_kt_12_convention_retenue_vs_table(latitude: int) -> None:
    """T-KT-12 : (Spencer, 1361 W/m²) s'écarte de moins de 0,7 % de la table D&B à 5° et 10°N.

    L'écart vient de la constante solaire (−0,44 %) et de la déclinaison
    (Spencer vs Cooper, jusqu'à 1,4° d'écart).
    """
    for mois, reference in enumerate(TABLE_1_10_1[latitude], start=1):
        ecart = h0_mensuel(latitude, 2001, mois) * MJ_PAR_KWH / reference - 1
        assert abs(ecart) < 0.007, (latitude, mois, ecart)
