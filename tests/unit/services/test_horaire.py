"""Tests unitaires des helpers de conversion `services/horaire.py`.

Couvre les 4 cas T-CONV :

- T-CONV-1 : conversion cle YYYYMMDDHH -> datetime ISO.
- T-CONV-2 : sentinelle -999.0 -> None.
- T-CONV-3 : valeur legitime preservee.
- T-CONV-4 : Kt nocturne -999.0 -> None (cohorent T-CONV-2, pas de
  cas particulier).
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from kuma_data_core.services.horaire import (
    code_parametre_amont,
    convertir_valeurs_amont_en_resultats,
    filtrer_resultats_par_plage,
    parser_cle_horaire,
    unite_cible,
)

pytestmark = pytest.mark.unit


def test_t_conv_1_parser_cle_horaire_valide() -> None:
    """T-CONV-1 : cle YYYYMMDDHH valide -> datetime ISO LST naif."""
    instant = parser_cle_horaire("2024060112")
    assert instant == datetime(2024, 6, 1, 12, 0, 0)


def test_t_conv_1_parser_cle_horaire_invalide_levee_value_error() -> None:
    """T-CONV-1 bis : cle hors format YYYYMMDDHH -> ValueError."""
    with pytest.raises(ValueError, match="cle horaire invalide"):
        parser_cle_horaire("2024-06-01")  # mauvais format


def test_t_conv_2_sentinelle_devient_none() -> None:
    """T-CONV-2 : -999.0 -> None dans le ResultatHoraire."""
    resultats = convertir_valeurs_amont_en_resultats(
        valeurs_par_cle={"2024060100": -999.0},
        grandeur="ghi",
    )
    assert len(resultats) == 1
    assert resultats[0].valeur is None
    assert resultats[0].unite == "Wh/m²"


def test_t_conv_3_valeur_legitime_preservee() -> None:
    """T-CONV-3 : valeur reelle preservee telle quelle."""
    resultats = convertir_valeurs_amont_en_resultats(
        valeurs_par_cle={"2024060112": 893.4},
        grandeur="ghi",
    )
    assert resultats[0].valeur == 893.4


def test_t_conv_4_kt_nocturne_sentinelle_devient_none() -> None:
    """T-CONV-4 : Kt -999.0 nocturne -> None (uniforme avec T-CONV-2).

    Le mapping Kt -> None pour les heures nocturnes (indice de clarte
    non defini la nuit) est traite uniformement par la sentinelle
    -999.0, sans cas particulier en v1. Differencier les raisons de None
    reste une evolution possible ulterieure.
    """
    resultats = convertir_valeurs_amont_en_resultats(
        valeurs_par_cle={
            "2024060103": -999.0,  # 3h LST, Kt non defini
            "2024060112": 0.687,  # 12h LST, Kt valide
        },
        grandeur="kt",
    )
    assert resultats[0].valeur is None
    assert resultats[0].unite == "sans dimension"
    assert resultats[1].valeur == 0.687


def test_t_conv_5_mapping_grandeur_code_amont() -> None:
    """T-CONV-5 : mapping grandeur Kuma -> code amont coherent."""
    assert code_parametre_amont("ghi") == "ALLSKY_SFC_SW_DWN"
    assert code_parametre_amont("dni") == "ALLSKY_SFC_SW_DNI"
    assert code_parametre_amont("dhi") == "ALLSKY_SFC_SW_DIFF"
    assert code_parametre_amont("t2m") == "T2M"
    assert code_parametre_amont("rh2m") == "RH2M"
    assert code_parametre_amont("kt") == "ALLSKY_KT"


def test_t_conv_6_unites_cibles() -> None:
    """T-CONV-6 : unites cibles coherentes."""
    assert unite_cible("ghi") == "Wh/m²"
    assert unite_cible("t2m") == "°C"
    assert unite_cible("rh2m") == "%"
    assert unite_cible("kt") == "sans dimension"


def test_t_conv_7_filtrage_par_plage() -> None:
    """T-CONV-7 : filtrage des resultats sur fenetre temporelle inclusive."""
    resultats = convertir_valeurs_amont_en_resultats(
        valeurs_par_cle={
            "2024060100": 1.0,  # dans
            "2024060123": 2.0,  # dans (23h le 06-01)
            "2024060200": 3.0,  # dans (00h le 06-02)
            "2024060300": 4.0,  # hors (00h le 06-03)
        },
        grandeur="ghi",
    )
    filtres = filtrer_resultats_par_plage(
        resultats=resultats,
        periode_debut=date(2024, 6, 1),
        periode_fin=date(2024, 6, 2),
    )
    assert len(filtres) == 3  # 00h 06-01 + 23h 06-01 + 00h 06-02
    assert filtres[-1].instant == datetime(2024, 6, 2, 0, 0, 0)
