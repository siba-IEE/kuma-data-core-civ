"""Tests unitaires de ``services.grandeurs.degre_jour_climatisation``.

Couvre la methode moyenne journaliere (Erbs 1983 + Schoenau & Kehrig 1990)
sur la localite pilote Conakry-Kaloum. Fonctions pures
sans mock DB.

Convention fixtures : T_moy_jour en plage tropicale realiste Guinee
(20-32 °C, T_amb moyenne annuelle Conakry 26.5 °C). Bases T_b standards :
24 °C (RTAA DOM, CEDEAO), 26 °C (Butera 2014 tropical chaud humide).
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from kuma_data_core.api.v1.schemas.grandeurs import ParametresDegreJourClimatisation
from kuma_data_core.services.grandeurs.degre_jour_climatisation import (
    NIVEAU_CONFIANCE_DERIVE_F2_V1,
    UNITE_DJC,
    MesureHeureTemperature,
    MesureJourTemperature,
    calculer_degre_jour_climatisation,
    calculer_degre_jour_climatisation_horaire,
)

pytestmark = pytest.mark.unit


def _parametres_base_24() -> ParametresDegreJourClimatisation:
    """Base T_b = 24°C (consigne CEDEAO climatisation tropicale)."""
    return ParametresDegreJourClimatisation(
        code_serie_source="gin_conakry_t2m_nasa_power_2021_2025",
        periode_debut=date(2024, 1, 1),
        periode_fin=date(2024, 1, 31),
        base_temperature_degc=24.0,
    )


def test_t_djc_1_cas_standard_un_mois() -> None:
    """T-DJC-1 : 5 jours janvier Conakry T_moy=27°C, base=24°C.

    Ecart par jour = 27-24 = 3 °C·j. Cumule sur 5 jours = 15 °C·j.
    Resultat unique mensuel pour 2024-01.
    """
    mesures: list[MesureJourTemperature] = [
        {"instant_mesure": date(2024, 1, d), "t_moy_degc": 27.0} for d in (1, 2, 3, 4, 5)
    ]
    resultats = calculer_degre_jour_climatisation(mesures=mesures, parametres=_parametres_base_24())
    assert len(resultats) == 1
    r = resultats[0]
    assert r.granularite == "mensuel"
    assert r.instant == "2024-01"
    assert r.unite == UNITE_DJC
    assert r.niveau_confiance == NIVEAU_CONFIANCE_DERIVE_F2_V1
    # 5 jours x 3 °C·j = 15 °C·j
    assert abs(r.valeur - 15.0) < 0.001


def test_t_djc_2_jours_froids_ecart_zero() -> None:
    """T-DJC-2 : T_moy < T_b -> ecart = 0 (pas de refroidissement requis)."""
    mesures: list[MesureJourTemperature] = [
        {"instant_mesure": date(2024, 1, d), "t_moy_degc": 22.0}  # < base 24
        for d in (1, 2, 3)
    ]
    resultats = calculer_degre_jour_climatisation(mesures=mesures, parametres=_parametres_base_24())
    # Aucun ecart positif, DJC mensuel = 0.
    assert resultats[0].valeur == 0.0


def test_t_djc_3_pluri_mois_separes() -> None:
    """T-DJC-3 : 2 mois distincts -> 2 ResultatMensuel separes."""
    mesures: list[MesureJourTemperature] = [
        {"instant_mesure": date(2024, 1, 15), "t_moy_degc": 26.0},
        {"instant_mesure": date(2024, 1, 16), "t_moy_degc": 27.0},
        {"instant_mesure": date(2024, 2, 1), "t_moy_degc": 28.0},
        {"instant_mesure": date(2024, 2, 2), "t_moy_degc": 29.0},
    ]
    r = calculer_degre_jour_climatisation(mesures, _parametres_base_24())
    assert len(r) == 2
    # Janvier : (26-24) + (27-24) = 5
    assert abs(r[0].valeur - 5.0) < 0.001
    assert r[0].instant == "2024-01"
    # Fevrier : (28-24) + (29-24) = 9
    assert abs(r[1].valeur - 9.0) < 0.001
    assert r[1].instant == "2024-02"


def test_t_djc_4_base_haute_plus_strict() -> None:
    """T-DJC-4 : base T_b plus elevee -> DJC plus faible (moins de degres-jours)."""
    mesures: list[MesureJourTemperature] = [
        {"instant_mesure": date(2024, 1, d), "t_moy_degc": 27.0} for d in (1, 2, 3)
    ]
    params_24 = _parametres_base_24()
    params_26 = ParametresDegreJourClimatisation(
        code_serie_source="x",
        periode_debut=date(2024, 1, 1),
        periode_fin=date(2024, 1, 31),
        base_temperature_degc=26.0,
    )
    r_24 = calculer_degre_jour_climatisation(mesures, params_24)
    r_26 = calculer_degre_jour_climatisation(mesures, params_26)
    # Base 24 : 3 jours x 3 = 9. Base 26 : 3 jours x 1 = 3.
    assert r_24[0].valeur > r_26[0].valeur


def test_t_djc_5_melange_jours_chauds_froids() -> None:
    """T-DJC-5 : melange jours T_moy > T_b et T_moy < T_b -> seuls les positifs comptent."""
    mesures: list[MesureJourTemperature] = [
        {"instant_mesure": date(2024, 1, 1), "t_moy_degc": 28.0},  # ecart +4
        {"instant_mesure": date(2024, 1, 2), "t_moy_degc": 22.0},  # ecart 0 (froid)
        {"instant_mesure": date(2024, 1, 3), "t_moy_degc": 26.0},  # ecart +2
        {"instant_mesure": date(2024, 1, 4), "t_moy_degc": 23.0},  # ecart 0 (froid)
    ]
    r = calculer_degre_jour_climatisation(mesures, _parametres_base_24())
    # 4 + 0 + 2 + 0 = 6
    assert abs(r[0].valeur - 6.0) < 0.001


def test_t_djc_6_liste_vide() -> None:
    """T-DJC-6 : mesures vide -> liste resultats vide."""
    r = calculer_degre_jour_climatisation(mesures=[], parametres=_parametres_base_24())
    assert r == []


def test_t_djc_7_idempotence() -> None:
    """T-DJC-7 : deux appels avec memes parametres -> meme reponse."""
    mesures: list[MesureJourTemperature] = [
        {"instant_mesure": date(2024, 1, d), "t_moy_degc": 27.0} for d in (1, 2, 3, 4, 5)
    ]
    params = _parametres_base_24()
    r1 = calculer_degre_jour_climatisation(mesures, params)
    r2 = calculer_degre_jour_climatisation(mesures, params)
    assert r1[0].valeur == r2[0].valeur


def test_t_djc_8_agregation_mensuelle_coherente() -> None:
    """T-DJC-8 : agregation 30 jours -> 1 ResultatMensuel.

    Conakry saison chaude T_moy=29°C constant pendant 30 jours.
    Ecart par jour = 29-24 = 5 °C·j. Cumule = 150 °C·j.
    """
    mesures: list[MesureJourTemperature] = [
        {"instant_mesure": date(2024, 4, d), "t_moy_degc": 29.0} for d in range(1, 31)
    ]
    r = calculer_degre_jour_climatisation(mesures, _parametres_base_24())
    assert len(r) == 1
    assert r[0].instant == "2024-04"
    # 30 jours x 5 °C·j = 150 °C·j
    assert abs(r[0].valeur - 150.0) < 0.001
    assert r[0].granularite == "mensuel"
    assert r[0].niveau_confiance == NIVEAU_CONFIANCE_DERIVE_F2_V1


# === Methode integration horaire (Erbs 1983) ==================


def _parametres_horaire_base_26() -> ParametresDegreJourClimatisation:
    """Base T_b = 26°C, methode integration horaire."""
    return ParametresDegreJourClimatisation(
        code_serie_source="gin_conakry_t2m_nasa_power_2001_2025",
        periode_debut=date(2024, 1, 1),
        periode_fin=date(2024, 1, 31),
        base_temperature_degc=26.0,
        methode="integration_horaire",
    )


def test_t_djc_h1_constant_egal_methode_journaliere() -> None:
    """T-DJC-H1 : temperature constante sur le jour -> horaire == journaliere.

    24 h a 29°C, base 26 : chaque heure contribue (29-26)/24 ; cumul sur
    24 h = 3.0 °C·j. Identique au resultat de la moyenne journaliere pour
    un jour a 29°C (sanity : pas de biais quand le cycle diurne est plat).
    """
    mesures: list[MesureHeureTemperature] = [
        {"instant_mesure": datetime(2024, 1, 1, h), "t_degc": 29.0} for h in range(24)
    ]
    r = calculer_degre_jour_climatisation_horaire(mesures, _parametres_horaire_base_26())
    assert len(r) == 1
    assert r[0].instant == "2024-01"
    assert r[0].unite == UNITE_DJC
    assert r[0].granularite == "mensuel"
    assert r[0].niveau_confiance == NIVEAU_CONFIANCE_DERIVE_F2_V1
    assert abs(r[0].valeur - 3.0) < 1e-9


def test_t_djc_h2_leve_biais_de_moyennage() -> None:
    """T-DJC-H2 : jour a moyenne < T_b mais pics horaires > T_b.

    20 h a 22°C + 4 h a 32°C, base 26. Moyenne journaliere = 23.67°C < 26
    -> la methode journaliere donne 0 (sous-estimation).
    L'integration horaire capte les 4 h chaudes : 4 x (32-26)/24 = 1.0 °C·j.
    """
    mesures: list[MesureHeureTemperature] = [
        {"instant_mesure": datetime(2024, 1, 1, h), "t_degc": 22.0 if h < 20 else 32.0}
        for h in range(24)
    ]
    params = _parametres_horaire_base_26()
    r_horaire = calculer_degre_jour_climatisation_horaire(mesures, params)
    assert abs(r_horaire[0].valeur - 1.0) < 1e-9

    # Contraste explicite : la moyenne journaliere du meme jour est sous la
    # base -> la methode journaliere sous-estime a 0.
    t_moy = sum(m["t_degc"] for m in mesures) / 24
    assert t_moy < params.base_temperature_degc
    r_journalier = calculer_degre_jour_climatisation(
        [{"instant_mesure": date(2024, 1, 1), "t_moy_degc": t_moy}], params
    )
    assert r_journalier[0].valeur == 0.0
    assert r_horaire[0].valeur > r_journalier[0].valeur


def test_t_djc_h3_toutes_heures_sous_base() -> None:
    """T-DJC-H3 : toutes les heures < T_b -> 0 °C·j."""
    mesures: list[MesureHeureTemperature] = [
        {"instant_mesure": datetime(2024, 1, 1, h), "t_degc": 22.0} for h in range(24)
    ]
    r = calculer_degre_jour_climatisation_horaire(mesures, _parametres_horaire_base_26())
    assert r[0].valeur == 0.0


def test_t_djc_h4_agregation_multi_mois() -> None:
    """T-DJC-H4 : heures sur 2 mois -> 2 ResultatMensuel ordonnes."""
    mesures: list[MesureHeureTemperature] = [
        {"instant_mesure": datetime(2024, 1, 10, h), "t_degc": 27.0} for h in range(24)
    ] + [{"instant_mesure": datetime(2024, 2, 10, h), "t_degc": 28.0} for h in range(24)]
    r = calculer_degre_jour_climatisation_horaire(mesures, _parametres_horaire_base_26())
    assert len(r) == 2
    # Janvier : 24 h x (27-26)/24 = 1.0 ; Fevrier : 24 h x (28-26)/24 = 2.0
    assert r[0].instant == "2024-01" and abs(r[0].valeur - 1.0) < 1e-9
    assert r[1].instant == "2024-02" and abs(r[1].valeur - 2.0) < 1e-9


def test_t_djc_h5_liste_vide() -> None:
    """T-DJC-H5 : mesures horaires vides -> liste resultats vide."""
    r = calculer_degre_jour_climatisation_horaire(
        mesures=[], parametres=_parametres_horaire_base_26()
    )
    assert r == []
