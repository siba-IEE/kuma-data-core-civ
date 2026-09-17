"""Tests unitaires de ``services.grandeurs.productible_correction_thermique``.

Couvre le modele NOCT simple (Ross 1980) sur la localite pilote
Conakry-Kaloum. Fonctions pures sans mock DB.

Convention fixtures : valeurs T2M en plage tropicale realiste
(20-35 °C, mediane Conakry 27 °C), irradiance en plage realiste
(3-7 kWh/m²/jour pour la Guinee selon saison). Aucune valeur arbitraire
hors physique tropicale.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from kuma_data_core.api.v1.schemas.grandeurs import (
    ParametresProductibleCorrectionThermique,
)
from kuma_data_core.services.grandeurs.productible_correction_thermique import (
    NIVEAU_CONFIANCE_DERIVE_F2_V1,
    UNITE_PRODUCTIBLE,
    MesureHeureThermique,
    MesureJourThermique,
    calculer_productible_correction_thermique,
    calculer_productible_correction_thermique_horaire,
)

pytestmark = pytest.mark.unit


def _parametres_standard() -> ParametresProductibleCorrectionThermique:
    """Parametres typiques c-Si : NOCT 45 °C, gamma_Pmax -0.4 %/°C, 1 kWc."""
    return ParametresProductibleCorrectionThermique(
        code_serie_source="gin_conakry_ghi_nasa_power_2021_2025",
        periode_debut=date(2024, 6, 15),
        periode_fin=date(2024, 6, 15),
        noct_degc=45,
        coeff_temp_pourcent_par_degc=-0.4,
        puissance_stc_wc=1000,
    )


def test_t_therm_1_cas_standard() -> None:
    """T-THERM-1 : cas standard journalier, productible coherent positif.

    Conakry juin (saison chaude), T2M=28°C, GHI=5.5 kWh/m²/jour.
    Productible attendu : 5 kWh/jour (1 kWc x 5 h equivalentes
    x facteur thermique < 1).
    """
    mesures: list[MesureJourThermique] = [
        {
            "instant_mesure": date(2024, 6, 15),
            "t_amb_degc": 28.0,
            "irradiance_kwh_par_m2_jour": 5.5,
        }
    ]
    resultats = calculer_productible_correction_thermique(
        mesures=mesures,
        parametres=_parametres_standard(),
    )
    assert len(resultats) == 1
    r = resultats[0]
    assert r.granularite == "journalier"
    assert r.instant == date(2024, 6, 15)
    assert r.unite == UNITE_PRODUCTIBLE
    assert r.niveau_confiance == NIVEAU_CONFIANCE_DERIVE_F2_V1
    # Productible coherent : 5 kWh, facteur thermique < 1 donc < 5.5
    assert 4.5 < r.valeur < 5.5


def test_t_therm_2_temperature_stc_facteur_unite() -> None:
    """T-THERM-2 : T_amb tres basse (T_cell 25°C STC) -> facteur thermique = 1.

    Cas limite : si T_cell egale T_STC=25°C, la correction thermique est
    nulle et P_AC = P_STC * G/G_STC sans degradation. Avec NOCT=45,
    G_jour=5.5 kWh/m²/jour 229 W/m² moyen 24h, alors :
        T_cell = T_amb + 25 x 229/800 = T_amb + 7.16
    Pour T_cell = 25, il faut T_amb = 17.84°C.
    """
    t_amb_stc = 25.0 - (45 - 20) * (5500 / 24) / 800  # = 17.84°C
    mesures: list[MesureJourThermique] = [
        {
            "instant_mesure": date(2024, 6, 15),
            "t_amb_degc": t_amb_stc,
            "irradiance_kwh_par_m2_jour": 5.5,
        }
    ]
    resultats = calculer_productible_correction_thermique(
        mesures=mesures,
        parametres=_parametres_standard(),
    )
    # Facteur thermique = 1 -> productible = 1 kWc x 5.5 kWh/m²/jour x 1 = 5.5
    assert abs(resultats[0].valeur - 5.5) / 5.5 < 0.01


def test_t_therm_3_temperature_haute_degrade() -> None:
    """T-THERM-3 : T_amb elevee (Conakry saison chaude) degrade le productible."""
    mesures_froide: list[MesureJourThermique] = [
        {
            "instant_mesure": date(2024, 1, 15),
            "t_amb_degc": 24.0,  # saison seche relative
            "irradiance_kwh_par_m2_jour": 5.5,
        }
    ]
    mesures_chaude: list[MesureJourThermique] = [
        {
            "instant_mesure": date(2024, 4, 15),
            "t_amb_degc": 32.0,  # saison chaude pre-mousson
            "irradiance_kwh_par_m2_jour": 5.5,
        }
    ]
    r_froide = calculer_productible_correction_thermique(
        mesures=mesures_froide, parametres=_parametres_standard()
    )
    r_chaude = calculer_productible_correction_thermique(
        mesures=mesures_chaude, parametres=_parametres_standard()
    )
    # Productible diminue avec T_amb croissante (gamma_Pmax negatif).
    assert r_chaude[0].valeur < r_froide[0].valeur


def test_t_therm_4_liste_vide() -> None:
    """T-THERM-4 : mesures vide -> liste resultats vide."""
    resultats = calculer_productible_correction_thermique(
        mesures=[], parametres=_parametres_standard()
    )
    assert resultats == []


def test_t_therm_5_proportionnel_puissance_stc() -> None:
    """T-THERM-5 : productible proportionnel a puissance_stc_wc a parametres egaux."""
    mesures: list[MesureJourThermique] = [
        {
            "instant_mesure": date(2024, 6, 15),
            "t_amb_degc": 28.0,
            "irradiance_kwh_par_m2_jour": 5.5,
        }
    ]
    params_1kwc = _parametres_standard()
    params_3kwc = ParametresProductibleCorrectionThermique(
        code_serie_source="x",
        periode_debut=date(2024, 6, 15),
        periode_fin=date(2024, 6, 15),
        noct_degc=45,
        coeff_temp_pourcent_par_degc=-0.4,
        puissance_stc_wc=3000,
    )
    r_1kwc = calculer_productible_correction_thermique(mesures, params_1kwc)
    r_3kwc = calculer_productible_correction_thermique(mesures, params_3kwc)
    # Productible 3 kWc = 3 x productible 1 kWc (linearite en P_STC).
    assert abs(r_3kwc[0].valeur - 3.0 * r_1kwc[0].valeur) < 0.001


def test_t_therm_6_idempotence() -> None:
    """T-THERM-6 : deux appels avec memes parametres -> meme reponse."""
    mesures: list[MesureJourThermique] = [
        {
            "instant_mesure": date(2024, 6, 15),
            "t_amb_degc": 28.0,
            "irradiance_kwh_par_m2_jour": 5.5,
        }
    ]
    params = _parametres_standard()
    r1 = calculer_productible_correction_thermique(mesures, params)
    r2 = calculer_productible_correction_thermique(mesures, params)
    assert r1[0].valeur == r2[0].valeur


def test_t_therm_7_serie_pluri_jours_ordre_preserve() -> None:
    """T-THERM-7 : serie 5 jours -> 5 resultats, ordre preserve, niveau 'B' uniforme."""
    mesures: list[MesureJourThermique] = [
        {
            "instant_mesure": date(2024, 1, d),
            "t_amb_degc": 26.0,
            "irradiance_kwh_par_m2_jour": 5.0,
        }
        for d in (1, 2, 3, 4, 5)
    ]
    resultats = calculer_productible_correction_thermique(mesures, _parametres_standard())
    assert len(resultats) == 5
    assert [r.instant for r in resultats] == [date(2024, 1, d) for d in (1, 2, 3, 4, 5)]
    assert all(r.niveau_confiance == NIVEAU_CONFIANCE_DERIVE_F2_V1 for r in resultats)


# === Methode integration horaire (pour le thermique) ===========


def _mesures_horaires(jour: date, profil_ghi_w: list[float], t_amb: float = 25.0):
    """24 mesures horaires (GHI W/m² par heure, T_amb constante)."""
    return [
        MesureHeureThermique(
            instant_mesure=datetime(jour.year, jour.month, jour.day, h, tzinfo=UTC),
            t_amb_degc=t_amb,
            irradiance_w_par_m2=profil_ghi_w[h],
        )
        for h in range(24)
    ]


def test_t_therm_h1_vide() -> None:
    """Mesures horaires vides -> liste vide."""
    assert calculer_productible_correction_thermique_horaire([], _parametres_standard()) == []


def test_t_therm_h2_plat_egal_journalier() -> None:
    """Profil plat (GHI constant) -> horaire == journaliere (pas de biais).

    24 h a 250 W/m² (= 6 kWh/m²/jour). La methode journaliere utilise
    G_24h = 6000/24 = 250 W/m² : meme T_cell que chaque heure -> totaux
    identiques.
    """
    jour = date(2024, 6, 15)
    total_h = sum(
        r.valeur
        for r in calculer_productible_correction_thermique_horaire(
            _mesures_horaires(jour, [250.0] * 24), _parametres_standard()
        )
    )
    mesure_jour: MesureJourThermique = {
        "instant_mesure": jour,
        "t_amb_degc": 25.0,
        "irradiance_kwh_par_m2_jour": 6.0,
    }
    total_j = calculer_productible_correction_thermique([mesure_jour], _parametres_standard())[
        0
    ].valeur
    assert abs(total_h - total_j) < 1e-9


def test_t_therm_h3_pic_journaliere_surestime() -> None:
    """Profil piqué (même énergie concentrée à midi) -> horaire < journaliere.

    6 h a 1000 W/m² + 18 h a 0 (= 6 kWh/m²/jour, comme le cas plat). Le pic
    de midi porte T_cell bien plus haut (perte thermique reelle) que la
    moyenne 24 h ; la methode journaliere lisse ce pic et surestime donc le
    productible. Coeur du biais de moyennage pour le thermique.
    """
    jour = date(2024, 6, 15)
    profil = [1000.0 if 9 <= h < 15 else 0.0 for h in range(24)]  # 6 h a 1000
    total_h = sum(
        r.valeur
        for r in calculer_productible_correction_thermique_horaire(
            _mesures_horaires(jour, profil), _parametres_standard()
        )
    )
    mesure_jour: MesureJourThermique = {
        "instant_mesure": jour,
        "t_amb_degc": 25.0,
        "irradiance_kwh_par_m2_jour": 6.0,
    }
    total_j = calculer_productible_correction_thermique([mesure_jour], _parametres_standard())[
        0
    ].valeur
    assert total_h < total_j


def test_t_therm_h4_structure_multi_jours() -> None:
    """Heures sur 2 jours -> 2 ResultatJournalier (structure, unite, niveau)."""
    mesures = _mesures_horaires(date(2024, 6, 15), [400.0] * 24) + _mesures_horaires(
        date(2024, 6, 16), [400.0] * 24
    )
    r = calculer_productible_correction_thermique_horaire(mesures, _parametres_standard())
    assert len(r) == 2
    assert r[0].instant == date(2024, 6, 15)
    assert r[1].instant == date(2024, 6, 16)
    assert all(x.unite == UNITE_PRODUCTIBLE for x in r)
    assert all(x.niveau_confiance == NIVEAU_CONFIANCE_DERIVE_F2_V1 for x in r)
    assert all(x.valeur > 0.0 for x in r)
