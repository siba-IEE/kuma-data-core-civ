"""Tests unitaires de la machine d'état statut éditorial.

Couvre exhaustivement la matrice des mécaniques transverses :
- Les 8 transitions autorisées passent.
- Toutes les autres paires (statuts standards x statuts standards et
  cas dégénérés) sont refusées via ``TransitionEditorialeRefusee``.
"""

from __future__ import annotations

import itertools

import pytest

from kuma_data_core.editorial.statuts import (
    STATUTS_EDITORIAUX_AUTORISES,
    TRANSITIONS_AUTORISEES,
    transition_autorisee,
    transition_statut,
)
from kuma_data_core.exceptions import TransitionEditorialeRefusee

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Constantes - vérifications structurelles
# ---------------------------------------------------------------------------


def test_statuts_autorises_5_valeurs() -> None:
    """Énumération exhaustive : 5 valeurs autorisées."""
    attendus = frozenset({"brut", "valide_auto", "valide_humain", "publie", "deprecie"})
    assert attendus == STATUTS_EDITORIAUX_AUTORISES


def test_transitions_autorisees_8_paires() -> None:
    """Énumération exhaustive : 8 transitions autorisées."""
    attendues = frozenset(
        {
            ("brut", "valide_auto"),
            ("brut", "valide_humain"),
            ("brut", "deprecie"),
            ("valide_auto", "valide_humain"),
            ("valide_auto", "deprecie"),
            ("valide_humain", "publie"),
            ("valide_humain", "deprecie"),
            ("publie", "deprecie"),
        }
    )
    assert attendues == TRANSITIONS_AUTORISEES
    assert len(TRANSITIONS_AUTORISEES) == 8


# ---------------------------------------------------------------------------
# Transitions autorisées
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("courant", "nouveau"),
    [
        ("brut", "valide_auto"),
        ("brut", "valide_humain"),
        ("brut", "deprecie"),
        ("valide_auto", "valide_humain"),
        ("valide_auto", "deprecie"),
        ("valide_humain", "publie"),
        ("valide_humain", "deprecie"),
        ("publie", "deprecie"),
    ],
)
def test_transition_autorisee_passe(courant: str, nouveau: str) -> None:
    assert transition_autorisee(courant, nouveau) is True
    transition_statut(courant, nouveau)  # ne lève pas


# ---------------------------------------------------------------------------
# Transitions refusées - couverture exhaustive 5 x 5 - 8 = 17 paires
# ---------------------------------------------------------------------------


def _toutes_paires_refusees() -> list[tuple[str, str]]:
    """5 x 5 = 25 paires de statuts standards, moins 8 autorisées = 17 refusées."""
    paires_possibles = list(itertools.product(STATUTS_EDITORIAUX_AUTORISES, repeat=2))
    return [p for p in paires_possibles if p not in TRANSITIONS_AUTORISEES]


@pytest.mark.parametrize(("courant", "nouveau"), _toutes_paires_refusees())
def test_transition_refusee_leve_exception(courant: str, nouveau: str) -> None:
    assert transition_autorisee(courant, nouveau) is False
    with pytest.raises(TransitionEditorialeRefusee) as exc_info:
        transition_statut(courant, nouveau)
    assert exc_info.value.statut_courant == courant
    assert exc_info.value.nouveau_statut == nouveau


# ---------------------------------------------------------------------------
# Cas dégénérés : statuts inconnus
# ---------------------------------------------------------------------------


def test_statut_inconnu_courant_refuse() -> None:
    with pytest.raises(TransitionEditorialeRefusee):
        transition_statut("inconnu", "valide_humain")


def test_statut_inconnu_nouveau_refuse() -> None:
    with pytest.raises(TransitionEditorialeRefusee):
        transition_statut("brut", "inconnu")


def test_transition_meme_statut_refusee() -> None:
    """``brut -> brut`` est refusé : pas de no-op silencieux."""
    for statut in STATUTS_EDITORIAUX_AUTORISES:
        with pytest.raises(TransitionEditorialeRefusee):
            transition_statut(statut, statut)


# ---------------------------------------------------------------------------
# État terminal ``deprecie`` : aucune transition sortante
# ---------------------------------------------------------------------------


def test_deprecie_est_terminal() -> None:
    """Depuis ``deprecie``, aucune transition n'est autorisée."""
    for autre_statut in STATUTS_EDITORIAUX_AUTORISES:
        with pytest.raises(TransitionEditorialeRefusee):
            transition_statut("deprecie", autre_statut)
