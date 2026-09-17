"""Tests unitaires du module `services.grandeurs.indicateur_qualite_donnees`.

6 tests T-1 à T-6.

Tests centrés sur la fonction pure
`_calculer_score` et le helper `_binning_score`. L'orchestrateur
`calculer_et_inserer_indicateur_qualite_donnees` est testé en
intégration.
"""

from __future__ import annotations

import pytest

from kuma_data_core.services.grandeurs.indicateur_qualite_donnees import (
    _binning_score,
    _calculer_score,
)

pytestmark = pytest.mark.unit


def test_t1_completude_parfaite_phase_1() -> None:
    """T-1 : C1=1.0, C2=0.7 (niveaux B), C3=1.0 (haute) → 0.91 → bin 5.

    Scénario idéal : 1826 mesures sur 1826 attendues, toutes
    en niveau B (R4 catch-all NASA POWER + modele_satellitaire),
    source NASA POWER fiabilité haute. Maximum théorique dans ce régime.
    """
    resultat = _calculer_score(
        nb_mesures_courantes=1826,
        nb_jours_attendus=1826,
        niveaux_confiance=("B",) * 1826,
        fiabilite_source="haute",
    )
    assert resultat["c1_completude"] == pytest.approx(1.0)
    assert resultat["c2_confiance_moyenne"] == pytest.approx(0.7)
    assert resultat["c3_fiabilite_source"] == pytest.approx(1.0)
    assert resultat["score_continu"] == pytest.approx(0.91)
    assert resultat["score_discret"] == 5


def test_t2_completude_nulle_phase_1() -> None:
    """T-2 : C1=0.0, C2=0.7 (niveaux B), C3=1.0 → 0.41 → bin 3.

    Score minimum théorique dans ce régime (formule isolée, C2 fixée à 0.7
    pour refléter la constante du régime tout-B). Conséquence : plage
    effective majore 3.
    """
    resultat = _calculer_score(
        nb_mesures_courantes=0,
        nb_jours_attendus=1826,
        niveaux_confiance=("B",),
        fiabilite_source="haute",
    )
    assert resultat["c1_completude"] == pytest.approx(0.0)
    assert resultat["c2_confiance_moyenne"] == pytest.approx(0.7)
    assert resultat["c3_fiabilite_source"] == pytest.approx(1.0)
    assert resultat["score_continu"] == pytest.approx(0.41)
    assert resultat["score_discret"] == 3


def test_t3_binning_bornes_inferieures_fermees() -> None:
    """T-3 : intervalles fermé-ouvert sur les bornes inférieures des bins 1-4.

    Pour score continu = 0.2 exact, on attend bin 2 (et non bin 1).
    Idem 0.4 → bin 3, 0.6 → bin 4, 0.8 → bin 5.
    """
    assert _binning_score(0.0) == 1
    assert _binning_score(0.199999) == 1
    assert _binning_score(0.2) == 2
    assert _binning_score(0.4) == 3
    assert _binning_score(0.6) == 4
    assert _binning_score(0.8) == 5


def test_t4_binning_borne_superieure_fermee() -> None:
    """T-4 : intervalle [0.8, 1.0] fermé à droite, bin 5 couvre 1.0 exact."""
    assert _binning_score(1.0) == 5
    resultat = _calculer_score(
        nb_mesures_courantes=10,
        nb_jours_attendus=10,
        niveaux_confiance=("A",) * 10,
        fiabilite_source="haute",
    )
    assert resultat["score_continu"] == pytest.approx(1.0)
    assert resultat["score_discret"] == 5


def test_t5_c2_moyenne_ponderee_niveaux_mixtes() -> None:
    """T-5 : moyenne pondérée des niveaux A/B/C correcte.

    Mix `(A, B, C)` → C2 = (1.0 + 0.7 + 0.4) / 3 = 0.7.
    Mix `(A, A, B, C)` → C2 = (1.0 + 1.0 + 0.7 + 0.4) / 4 = 0.775.
    """
    r1 = _calculer_score(
        nb_mesures_courantes=3,
        nb_jours_attendus=3,
        niveaux_confiance=("A", "B", "C"),
        fiabilite_source="haute",
    )
    assert r1["c2_confiance_moyenne"] == pytest.approx(0.7)

    r2 = _calculer_score(
        nb_mesures_courantes=4,
        nb_jours_attendus=4,
        niveaux_confiance=("A", "A", "B", "C"),
        fiabilite_source="haute",
    )
    assert r2["c2_confiance_moyenne"] == pytest.approx(0.775)


def test_t6_c3_fiabilite_moyenne() -> None:
    """T-6 : `fiabilite_source='moyenne'` → C3 = 0.7 (et non 1.0)."""
    resultat = _calculer_score(
        nb_mesures_courantes=100,
        nb_jours_attendus=100,
        niveaux_confiance=("B",) * 100,
        fiabilite_source="moyenne",
    )
    assert resultat["c3_fiabilite_source"] == pytest.approx(0.7)
    expected = 0.5 * 1.0 + 0.3 * 0.7 + 0.2 * 0.7
    assert resultat["score_continu"] == pytest.approx(expected)
    assert resultat["score_discret"] == 5
