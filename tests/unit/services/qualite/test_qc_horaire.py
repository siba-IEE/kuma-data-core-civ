"""Tests unitaires du QC horaire BSRN - fonctions pures.

Vérifie les bornes BSRN (jour/nuit, ok/rare/impossible), les tests de
fermeture et de ratio diffus, et l'agrégation par instant. Pas de DB ni
de pvlib (le runner ``executer_qc_horaire`` est couvert en intégration
via la migration 055).
"""

from __future__ import annotations

import pytest

from kuma_data_core.services.qualite.qc_horaire import (
    MesureHoraire,
    evaluer_instant,
    fermeture_ok,
    plausibilite_non_radiative,
    plausibilite_radiative,
    ratio_diffus_ok,
    tolerance_fermeture,
)

pytestmark = pytest.mark.unit

# Géométrie de référence : jour (SZA=30°, μ₀≈0.866) et nuit (μ₀=0).
_SA = 1360.0
_MU0_JOUR = 0.8660254
_SZA_JOUR = 30.0
_MU0_NUIT = 0.0
_SZA_NUIT = 120.0


# === Plausibilité radiative (BSRN §4.1) ===================================


def test_ghi_jour_ok_rare_impossible() -> None:
    # Bornes a μ₀≈0.866 : possible 1360*1.5*0.866^1.2+100, rare 1360*1.2*...+50.
    assert plausibilite_radiative("ghi", 800.0, _SA, _MU0_JOUR) == "ok"
    assert plausibilite_radiative("ghi", 2500.0, _SA, _MU0_JOUR) == "impossible"
    # Valeur entre rare et possible -> "rare".
    assert plausibilite_radiative("ghi", 1600.0, _SA, _MU0_JOUR) == "rare"


def test_ghi_nuit_borne_reduite_a_offset() -> None:
    # μ₀=0 -> max possible = 100, max rare = 50.
    assert plausibilite_radiative("ghi", 0.0, _SA, _MU0_NUIT) == "ok"
    assert plausibilite_radiative("ghi", 80.0, _SA, _MU0_NUIT) == "rare"
    assert plausibilite_radiative("ghi", 150.0, _SA, _MU0_NUIT) == "impossible"


def test_dni_borne_haute_possible_egale_sa() -> None:
    assert plausibilite_radiative("dni", 900.0, _SA, _MU0_JOUR) == "ok"
    # > Sa -> impossible (borne possible DNI = Sa).
    assert plausibilite_radiative("dni", _SA + 1.0, _SA, _MU0_JOUR) == "impossible"


def test_bornes_basses_negatives() -> None:
    assert plausibilite_radiative("ghi", -3.0, _SA, _MU0_JOUR) == "rare"  # entre -4 et -2
    assert plausibilite_radiative("ghi", -5.0, _SA, _MU0_JOUR) == "impossible"  # < -4


# === Plausibilité non radiative ===========================================


def test_plausibilite_non_radiative_bornes() -> None:
    assert plausibilite_non_radiative("rh2m", 78.0) == "ok"
    assert plausibilite_non_radiative("rh2m", 105.0) == "impossible"
    assert plausibilite_non_radiative("t2m", 27.0) == "ok"
    assert plausibilite_non_radiative("t2m", -120.0) == "impossible"
    assert plausibilite_non_radiative("kt", 0.5) == "ok"
    assert plausibilite_non_radiative("kt", 1.5) == "impossible"


# === Fermeture (BSRN §4.2) ================================================


def test_tolerance_fermeture_bandes() -> None:
    assert tolerance_fermeture(30.0) == 0.08
    assert tolerance_fermeture(80.0) == 0.15
    assert tolerance_fermeture(95.0) is None


def test_fermeture_ok_coherent_et_hors_tolerance() -> None:
    # sum = 200 + 700*0.866 = 806.2 ; ghi=800 -> ratio≈0.992, |.|<0.08 -> True.
    assert fermeture_ok(800.0, 200.0, 700.0, _MU0_JOUR, _SZA_JOUR) is True
    # ghi=500 -> ratio≈0.62 -> hors tolerance.
    assert fermeture_ok(500.0, 200.0, 700.0, _MU0_JOUR, _SZA_JOUR) is False


def test_fermeture_non_applicable_si_somme_faible() -> None:
    assert fermeture_ok(10.0, 10.0, 10.0, 0.5, _SZA_JOUR) is None  # sum=15 <= 50


# === Ratio diffus (BSRN §4.3) =============================================


def test_ratio_diffus_ok_et_eleve() -> None:
    assert ratio_diffus_ok(200.0, 800.0, _SZA_JOUR) is True  # 0.25 < 1.05
    assert ratio_diffus_ok(900.0, 800.0, _SZA_JOUR) is False  # 1.125 !< 1.05


def test_ratio_diffus_non_applicable_si_ghi_faible() -> None:
    assert ratio_diffus_ok(10.0, 40.0, _SZA_JOUR) is None  # ghi <= 50


# === Agrégation par instant ===============================================


def test_evaluer_instant_clean_tout_valide() -> None:
    mesures = [
        MesureHoraire(1, "ghi", 800.0),
        MesureHoraire(2, "dhi", 200.0),
        MesureHoraire(3, "dni", 700.0),
        MesureHoraire(4, "t2m", 27.0),
    ]
    verdicts = {v.row_id: v for v in evaluer_instant(mesures, _SA, _MU0_JOUR, _SZA_JOUR)}
    assert all(v.statut_cible == "valide_auto" for v in verdicts.values())
    assert all(v.flags == () for v in verdicts.values())
    assert all(v.niveau == "B" for v in verdicts.values())


def test_evaluer_instant_valeur_impossible_rejetee() -> None:
    verdicts = evaluer_instant([MesureHoraire(9, "ghi", 3000.0)], _SA, _MU0_JOUR, _SZA_JOUR)
    assert verdicts[0].statut_cible == "brut"
    assert verdicts[0].motif_rejet is not None
    assert "rejet" in verdicts[0].commentaire()


def test_evaluer_instant_valeur_rare_flaggee() -> None:
    verdicts = evaluer_instant([MesureHoraire(7, "ghi", 1600.0)], _SA, _MU0_JOUR, _SZA_JOUR)
    assert verdicts[0].statut_cible == "valide_auto"
    assert any("rare" in f for f in verdicts[0].flags)


def test_evaluer_instant_fermeture_flagge_radiatives() -> None:
    # ghi incoherent avec dhi+dni*mu0 -> les 3 radiatives flaggees fermeture.
    mesures = [
        MesureHoraire(1, "ghi", 400.0),
        MesureHoraire(2, "dhi", 200.0),
        MesureHoraire(3, "dni", 700.0),
    ]
    verdicts = {v.row_id: v for v in evaluer_instant(mesures, _SA, _MU0_JOUR, _SZA_JOUR)}
    assert all(v.statut_cible == "valide_auto" for v in verdicts.values())
    assert any("fermeture" in f for f in verdicts[1].flags)
