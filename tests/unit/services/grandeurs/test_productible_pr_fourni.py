"""Tests unitaires de ``services.grandeurs.productible_pr_fourni``.

Couvre les variantes PR brut (Marion 2005) et PR_T temperature-corrected
(Dierauf 2013) sur la localite pilote Conakry-Kaloum.
Fonctions pures sans mock DB.

Convention fixtures : T2M en plage tropicale realiste (24-32°C),
irradiance en plage realiste (4-7 kWh/m²/jour), PR en plage observee
en parc PV Afrique de l'Ouest (0.72-0.82, mediane 0.78).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from kuma_data_core.api.v1.schemas.grandeurs import ParametresProductiblePRFourni
from kuma_data_core.services.grandeurs.productible_pr_fourni import (
    NIVEAU_CONFIANCE_DERIVE_F2_V1,
    UNITE_PRODUCTIBLE,
    MesureHeurePRFourni,
    MesureJourPRFourni,
    calculer_productible_pr_fourni,
    calculer_productible_pr_fourni_horaire,
)

pytestmark = pytest.mark.unit


def _parametres_pr_brut() -> ParametresProductiblePRFourni:
    """Parametres typiques PR brut sans correction temperature."""
    return ParametresProductiblePRFourni(
        code_serie_source="gin_conakry_ghi_nasa_power_2021_2025",
        periode_debut=date(2024, 6, 15),
        periode_fin=date(2024, 6, 15),
        pr_fourni=0.80,
        correction="aucune",
        puissance_stc_wc=1000,
    )


def _parametres_pr_t() -> ParametresProductiblePRFourni:
    """Parametres typiques PR temperature-corrected (NOCT + gamma fournis)."""
    return ParametresProductiblePRFourni(
        code_serie_source="gin_conakry_ghi_nasa_power_2021_2025",
        periode_debut=date(2024, 6, 15),
        periode_fin=date(2024, 6, 15),
        pr_fourni=0.80,
        correction="temperature",
        puissance_stc_wc=1000,
        noct_degc=45,
        coeff_temp_pourcent_par_degc=-0.4,
    )


def test_t_pr_1_pr_brut_cas_standard() -> None:
    """T-PR-1 : PR brut Marion 2005, productible = P_STC x G x PR.

    P_STC=1 kWc, G=5.5 kWh/m²/jour, PR=0.80 -> productible=4.4 kWh.
    """
    mesures: list[MesureJourPRFourni] = [
        {
            "instant_mesure": date(2024, 6, 15),
            "irradiance_kwh_par_m2_jour": 5.5,
            "t_amb_degc": None,
        }
    ]
    resultats = calculer_productible_pr_fourni(mesures=mesures, parametres=_parametres_pr_brut())
    assert len(resultats) == 1
    r = resultats[0]
    assert r.granularite == "journalier"
    assert r.unite == UNITE_PRODUCTIBLE
    assert r.niveau_confiance == NIVEAU_CONFIANCE_DERIVE_F2_V1
    # E_AC = 1 kWc x 5.5 kWh/m²/jour x 0.80 = 4.4 kWh
    assert abs(r.valeur - 4.4) < 0.001


def test_t_pr_2_pr_t_cas_standard() -> None:
    """T-PR-2 : PR_T temperature-corrected Dierauf 2013, productible < PR brut.

    En climat tropical chaud (T_amb=28°C, T_cell elevee), le facteur
    thermique est < 1, donc PR_T < PR brut.
    """
    mesures: list[MesureJourPRFourni] = [
        {
            "instant_mesure": date(2024, 6, 15),
            "irradiance_kwh_par_m2_jour": 5.5,
            "t_amb_degc": 28.0,
        }
    ]
    r_brut = calculer_productible_pr_fourni(mesures, _parametres_pr_brut())
    r_t = calculer_productible_pr_fourni(mesures, _parametres_pr_t())
    # PR_T applique correction thermique negative -> productible inferieur.
    assert r_t[0].valeur < r_brut[0].valeur


def test_t_pr_3_proportionnel_puissance_stc() -> None:
    """T-PR-3 : productible proportionnel a puissance_stc_wc."""
    mesures: list[MesureJourPRFourni] = [
        {
            "instant_mesure": date(2024, 6, 15),
            "irradiance_kwh_par_m2_jour": 5.5,
            "t_amb_degc": None,
        }
    ]
    params_1kwc = _parametres_pr_brut()
    params_5kwc = ParametresProductiblePRFourni(
        code_serie_source="x",
        periode_debut=date(2024, 6, 15),
        periode_fin=date(2024, 6, 15),
        pr_fourni=0.80,
        correction="aucune",
        puissance_stc_wc=5000,
    )
    r_1 = calculer_productible_pr_fourni(mesures, params_1kwc)
    r_5 = calculer_productible_pr_fourni(mesures, params_5kwc)
    assert abs(r_5[0].valeur - 5.0 * r_1[0].valeur) < 0.001


def test_t_pr_4_pr_zero_productible_nul() -> None:
    """T-PR-4 : PR=0 -> productible=0 (cas degrade)."""
    mesures: list[MesureJourPRFourni] = [
        {
            "instant_mesure": date(2024, 6, 15),
            "irradiance_kwh_par_m2_jour": 5.5,
            "t_amb_degc": None,
        }
    ]
    params = ParametresProductiblePRFourni(
        code_serie_source="x",
        periode_debut=date(2024, 6, 15),
        periode_fin=date(2024, 6, 15),
        pr_fourni=0.0,
        correction="aucune",
        puissance_stc_wc=1000,
    )
    r = calculer_productible_pr_fourni(mesures, params)
    assert r[0].valeur == 0.0


def test_t_pr_5_liste_vide() -> None:
    """T-PR-5 : mesures vide -> liste resultats vide."""
    r = calculer_productible_pr_fourni(mesures=[], parametres=_parametres_pr_brut())
    assert r == []


def test_t_pr_6_idempotence() -> None:
    """T-PR-6 : deux appels avec memes parametres -> meme reponse."""
    mesures: list[MesureJourPRFourni] = [
        {
            "instant_mesure": date(2024, 6, 15),
            "irradiance_kwh_par_m2_jour": 5.5,
            "t_amb_degc": 28.0,
        }
    ]
    params = _parametres_pr_t()
    r1 = calculer_productible_pr_fourni(mesures, params)
    r2 = calculer_productible_pr_fourni(mesures, params)
    assert r1[0].valeur == r2[0].valeur


def test_t_pr_7_serie_pluri_jours() -> None:
    """T-PR-7 : serie 5 jours -> 5 resultats, ordre preserve, niveau 'B'."""
    mesures: list[MesureJourPRFourni] = [
        {
            "instant_mesure": date(2024, 1, d),
            "irradiance_kwh_par_m2_jour": 5.0,
            "t_amb_degc": None,
        }
        for d in (1, 2, 3, 4, 5)
    ]
    r = calculer_productible_pr_fourni(mesures, _parametres_pr_brut())
    assert len(r) == 5
    assert [m.instant for m in r] == [date(2024, 1, d) for d in (1, 2, 3, 4, 5)]
    assert all(m.niveau_confiance == NIVEAU_CONFIANCE_DERIVE_F2_V1 for m in r)


# === Methode integration horaire (PR_T uniquement ; PR brut lineaire) ===


def _mesures_horaires_pr(
    jour: date, profil_ghi_w: list[float], t_amb: float | None = None
) -> list[MesureHeurePRFourni]:
    """24 mesures horaires (GHI W/m² par heure, T_amb constante ou None)."""
    return [
        MesureHeurePRFourni(
            instant_mesure=datetime(jour.year, jour.month, jour.day, h, tzinfo=UTC),
            irradiance_w_par_m2=profil_ghi_w[h],
            t_amb_degc=t_amb,
        )
        for h in range(24)
    ]


def test_t_pr_h1_vide() -> None:
    """Mesures horaires vides -> liste vide."""
    assert calculer_productible_pr_fourni_horaire([], _parametres_pr_brut()) == []


def test_t_pr_h2_brut_horaire_egal_journalier_meme_pique() -> None:
    """INVARIANCE : PR brut lineaire en G -> horaire == journalier.

    Verrou d'honnêtete : meme avec un profil **pique** (6 h a 1000 W/m² =
    6 kWh/m²/jour), la linearite garantit l'egalite exacte horaire/journalier
    pour PR brut (aucun biais de moyennage a lever, contrairement a PR_T/ECS).
    """
    jour = date(2024, 6, 15)
    profil = [1000.0 if 9 <= h < 15 else 0.0 for h in range(24)]  # 6 h a 1000 = 6 kWh/m²/jour
    total_h = sum(
        r.valeur
        for r in calculer_productible_pr_fourni_horaire(
            _mesures_horaires_pr(jour, profil), _parametres_pr_brut()
        )
    )
    mesure_jour: MesureJourPRFourni = {
        "instant_mesure": jour,
        "irradiance_kwh_par_m2_jour": 6.0,
        "t_amb_degc": None,
    }
    total_j = calculer_productible_pr_fourni([mesure_jour], _parametres_pr_brut())[0].valeur
    assert abs(total_h - total_j) < 1e-9


def test_t_pr_h3_pr_t_pique_diffère_journalier() -> None:
    """JENSEN : PR_T (T_cell non-lineaire) -> horaire != journalier (profil pique).

    Le pic de midi porte T_cell bien plus haut (perte thermique reelle) ; la
    methode journaliere lisse ce pic sur 24 h et **surestime** donc le
    productible -> horaire < journalier.
    """
    jour = date(2024, 6, 15)
    profil = [1000.0 if 9 <= h < 15 else 0.0 for h in range(24)]
    total_h = sum(
        r.valeur
        for r in calculer_productible_pr_fourni_horaire(
            _mesures_horaires_pr(jour, profil, t_amb=28.0), _parametres_pr_t()
        )
    )
    mesure_jour: MesureJourPRFourni = {
        "instant_mesure": jour,
        "irradiance_kwh_par_m2_jour": 6.0,
        "t_amb_degc": 28.0,
    }
    total_j = calculer_productible_pr_fourni([mesure_jour], _parametres_pr_t())[0].valeur
    assert total_h < total_j


def test_t_pr_h4_structure_multi_jours() -> None:
    """Heures sur 2 jours -> 2 ResultatJournalier (structure, unite, niveau)."""
    mesures = _mesures_horaires_pr(date(2024, 6, 15), [400.0] * 24) + _mesures_horaires_pr(
        date(2024, 6, 16), [400.0] * 24
    )
    r = calculer_productible_pr_fourni_horaire(mesures, _parametres_pr_brut())
    assert len(r) == 2
    assert r[0].instant == date(2024, 6, 15)
    assert r[1].instant == date(2024, 6, 16)
    assert all(x.unite == UNITE_PRODUCTIBLE for x in r)
    assert all(x.niveau_confiance == NIVEAU_CONFIANCE_DERIVE_F2_V1 for x in r)
    assert all(x.valeur > 0.0 for x in r)
