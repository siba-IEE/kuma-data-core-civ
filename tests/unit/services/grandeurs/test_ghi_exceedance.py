"""Tests unitaires de ``services.grandeurs.ghi_exceedance``.

Couvre :

- T-EXC-1 a T-EXC-4 : fonction pure ``calculer_ghi_exceedance``
  (cas standard, garantie P90 < P50, sequence vide, sequence d'une
  valeur).
- T-EXC-5, T-EXC-6 : ``calculer_totaux_annuels`` (ponderation par
  jours du mois, annee bissextile vs commune).
- T-EXC-8 : base de 30 annees (normale OMM 1991-2020).
- T-EXC-9 a T-EXC-11 : ``calculer_totaux_annuels_climatologiques``
  (fenetre 1991-2020, annees incompletes ecartees, bornes).

- T-EXC-12 a T-EXC-14 : ``grouper_jumeaux_pixel`` (jumeaux de pixel detectes
  a la lecture par identite exacte des series, et non plus par une constante
  de co-localisation).

Fonctions pures, aucun mock DB.
"""

from __future__ import annotations

import pytest

from kuma_data_core.services.grandeurs.ghi_exceedance import (
    NOMBRE_ANNEES_BASE,
    calculer_ghi_exceedance,
    calculer_totaux_annuels,
    calculer_totaux_annuels_climatologiques,
    grouper_jumeaux_pixel,
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


def test_t_exc_8_nombre_annees_base_constant() -> None:
    """T-EXC-8 : 30 annees (1991-2020 inclus, OMM)."""
    assert NOMBRE_ANNEES_BASE == 30


def test_t_exc_9_fenetre_climatologique_ecarte_hors_normale() -> None:
    """T-EXC-9 : une serie prolongee ne contribue que par ses annees 1991-2020.

    Les annees 2021-2025 (serie prolongee) et 1990 (serie anterieure) sont
    ecartees : 30 totaux exactement, egaux a ceux du calcul brut.
    """
    mesures = [(a, m, 5.0 + a % 7) for a in range(1990, 2026) for m in range(1, 13)]
    totaux = calculer_totaux_annuels_climatologiques(mesures)
    assert list(totaux) == list(range(1991, 2021))
    assert len(totaux) == NOMBRE_ANNEES_BASE
    bruts = calculer_totaux_annuels(mesures)
    assert all(totaux[a] == bruts[a] for a in totaux)


def test_t_exc_10_annee_incomplete_ecartee() -> None:
    """T-EXC-10 : une annee a 11 mois n'est pas retenue (total sous-estime)."""
    mesures = [(a, m, 5.0) for a in (1991, 1992, 1993) for m in range(1, 13)]
    mesures = [(a, m, v) for a, m, v in mesures if (a, m) != (1992, 7)]
    totaux = calculer_totaux_annuels_climatologiques(mesures)
    assert list(totaux) == [1991, 1993]
    assert totaux[1991] == 5.0 * 365


def test_t_exc_11_bornes_parametrables_et_ordre_indifferent() -> None:
    """T-EXC-11 : bornes explicites, entree non triee, sortie triee par annee."""
    mesures = [(a, m, 4.0) for a in (2003, 2001, 2002) for m in range(12, 0, -1)]
    totaux = calculer_totaux_annuels_climatologiques(mesures, annee_debut=2001, annee_fin=2002)
    assert list(totaux) == [2001, 2002]
    assert totaux[2002] == 4.0 * 365


def test_t_exc_12_jumeaux_reciproques_et_point_resolu() -> None:
    """T-EXC-12 : vecteurs identiques = jumeaux reciproques ; unique = resolu."""
    jumeaux = grouper_jumeaux_pixel({"loc_b": (5.1, 5.2), "loc_a": (5.1, 5.2), "loc_c": (4.9, 5.0)})
    assert jumeaux == {"loc_a": ["loc_b"], "loc_b": ["loc_a"], "loc_c": []}


def test_t_exc_13_egalite_exacte_seulement() -> None:
    """T-EXC-13 : quasi-egalite ou vecteur incomplet = points distincts."""
    jumeaux = grouper_jumeaux_pixel({"a": (5.0, 5.1), "b": (5.0, 5.1000001), "c": (5.0,)})
    assert jumeaux == {"a": [], "b": [], "c": []}


def test_t_exc_14_groupe_de_trois_trie() -> None:
    """T-EXC-14 : chaque membre liste les autres, tries."""
    jumeaux = grouper_jumeaux_pixel(dict.fromkeys(("z", "x", "y"), (1.0, 2.0)))
    assert jumeaux == {"x": ["y", "z"], "y": ["x", "z"], "z": ["x", "y"]}
