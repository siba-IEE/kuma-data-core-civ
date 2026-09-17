"""Tests unitaires de ``services.grandeurs.ghi_exceedance``.

Couvre :

- T-EXC-1 a T-EXC-4 : fonction pure ``calculer_ghi_exceedance``
  (cas standard, garantie P90 < P50, sequence vide, sequence d'une
  valeur).
- T-EXC-5, T-EXC-6 : ``calculer_totaux_annuels`` (ponderation par
  jours du mois, annee bissextile vs commune).
- T-EXC-7 : constante de co-localisation (Kindia / Mamou
  reciproques).

Fonctions pures, aucun mock DB.
"""

from __future__ import annotations

import pytest

from kuma_data_core.services.grandeurs.ghi_exceedance import (
    NOMBRE_ANNEES_BASE,
    PAIRES_COLOCALISEES_D29,
    calculer_ghi_exceedance,
    calculer_totaux_annuels,
)

pytestmark = pytest.mark.unit


def test_t_exc_1_cas_standard_30_valeurs() -> None:
    """T-EXC-1 : cas standard sur 30 totaux annuels factices.

    Sequence triee de 1700 a 2099 (pas de 13.79), P50 attendu 1899
    (mediane), P90 attendu 1755 (10e percentile = 3.9e plus petite
    valeur interpolee).
    """
    totaux = [1700.0 + i * (399.0 / 29.0) for i in range(30)]
    assert len(totaux) == 30
    r = calculer_ghi_exceedance(totaux)
    # mediane : moyenne des 2 valeurs centrales (indices 14 et 15)
    assert abs(r.p50 - (totaux[14] + totaux[15]) / 2) < 0.01
    # P90 = percentile 10 = entre indices 2 et 3 par interpolation lineaire
    # numpy.percentile linear : pos = 0.10 * (30 - 1) = 2.9
    valeur_attendue_p90 = totaux[2] + 0.9 * (totaux[3] - totaux[2])
    assert abs(r.p90 - valeur_attendue_p90) < 0.01


def test_t_exc_2_p90_strictement_inferieur_p50() -> None:
    """T-EXC-2 : P90 < P50 garanti sur une distribution non degeneree.

    Garantie de la semantique exceedance : P90 = valeur depassee
    90 % des annees = percentile 10 (cote bas de distribution).
    """
    # Plage realiste guineenne : 1750-2050 kWh/m²/an
    totaux = [1750.0 + i * 10.0 for i in range(30)]
    r = calculer_ghi_exceedance(totaux)
    assert r.p90 < r.p50


def test_t_exc_3_distribution_degeneree_p50_egal_p90() -> None:
    """T-EXC-3 : sur une distribution constante (toutes valeurs egales),
    P50 == P90 (cas limite acceptable, pas une regression)."""
    totaux = [2000.0] * 30
    r = calculer_ghi_exceedance(totaux)
    assert r.p50 == 2000.0
    assert r.p90 == 2000.0


def test_t_exc_4_sequence_insuffisante_leve_erreur() -> None:
    """T-EXC-4 : moins de 2 valeurs -> ValueError clair."""
    with pytest.raises(ValueError, match="au moins 2 totaux"):
        calculer_ghi_exceedance([])
    with pytest.raises(ValueError, match="au moins 2 totaux"):
        calculer_ghi_exceedance([2000.0])


def test_t_exc_5_totaux_annuels_annee_commune_vs_bissextile() -> None:
    """T-EXC-5 : ponderation correcte fevrier 28 (commune) vs 29 (bissextile).

    1991 : annee commune (fevrier 28). 1992 : bissextile (fevrier 29).
    Pour une valeur mensuelle constante 5.0 kWh/m²/jour sur les 12 mois,
    total annuel = 5.0 x nb_jours_annee.
    """
    mesures_1991 = [(1991, m, 5.0) for m in range(1, 13)]
    mesures_1992 = [(1992, m, 5.0) for m in range(1, 13)]
    totaux_1991 = calculer_totaux_annuels(mesures_1991)
    totaux_1992 = calculer_totaux_annuels(mesures_1992)
    assert totaux_1991[1991] == 5.0 * 365  # annee commune
    assert totaux_1992[1992] == 5.0 * 366  # annee bissextile (+1 jour)


def test_t_exc_6_totaux_annuels_pondere_par_jours_mois() -> None:
    """T-EXC-6 : chaque mois pondere par son nombre de jours reel."""
    # 2023 : annee commune. Janvier 31, Fevrier 28, ..., Decembre 31.
    nb_jours_2023 = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    assert sum(nb_jours_2023) == 365
    # Valeur mensuelle distincte par mois pour eviter une compensation.
    mesures = [(2023, m, float(m)) for m in range(1, 13)]
    totaux = calculer_totaux_annuels(mesures)
    attendu = sum(float(m) * nb_jours_2023[m - 1] for m in range(1, 13))
    assert totaux[2023] == attendu


def test_t_exc_7_paires_colocalisees_d29_reciproques() -> None:
    """T-EXC-7 : Kindia et Mamou se referencent mutuellement."""
    assert PAIRES_COLOCALISEES_D29["gin_kindia"] == "gin_mamou"
    assert PAIRES_COLOCALISEES_D29["gin_mamou"] == "gin_kindia"
    # Ces 2 paires sont les seules connues a date.
    assert set(PAIRES_COLOCALISEES_D29.keys()) == {"gin_kindia", "gin_mamou"}


def test_t_exc_8_nombre_annees_base_constant() -> None:
    """T-EXC-8 : 30 annees (1991-2020 inclus, OMM)."""
    assert NOMBRE_ANNEES_BASE == 30
