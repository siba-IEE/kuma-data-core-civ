"""Tests unitaires de la dérivation et override des niveaux A/B/C.

Couvre les règles mécaniques R1-R4 et l'override.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from kuma_data_core.editorial.niveaux_confiance import (
    NIVEAUX_CONFIANCE_AUTORISES,
    calculer_niveau_confiance_derive,
    overrider_niveau_confiance,
    retirer_override_niveau_confiance,
    valider_niveau_confiance,
)
from kuma_data_core.exceptions import JustificationRequise, NiveauConfianceInvalide

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Structure de référence pour les tests override (mock léger sans SQLAlchemy)
# ---------------------------------------------------------------------------


@dataclass
class _LigneSimulee:
    niveau_confiance_override: str | None = None
    commentaire_editorial: str | None = None


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------


def test_niveaux_autorises_3_valeurs() -> None:
    attendus = frozenset({"A", "B", "C"})
    assert attendus == NIVEAUX_CONFIANCE_AUTORISES


# ---------------------------------------------------------------------------
# Règles R1-R4
# ---------------------------------------------------------------------------


def test_r1_source_faible_donne_c() -> None:
    """R1 : source.fiabilite='faible' → C (prioritaire)."""
    assert (
        calculer_niveau_confiance_derive(
            methode_collecte="mesure_directe",  # eligible R3 si R1 ne matchait pas
            fiabilite_source="faible",
        )
        == "C"
    )


def test_r2_expertise_humaine_donne_c() -> None:
    """R2 : methode_collecte='expertise_humaine' (R1 ne matche pas) → C."""
    assert (
        calculer_niveau_confiance_derive(
            methode_collecte="expertise_humaine",
            fiabilite_source="haute",
        )
        == "C"
    )


def test_r3_mesure_directe_et_source_haute_donne_a() -> None:
    """R3 : mesure_directe + source haute (R1, R2 ne matchent pas) → A."""
    assert (
        calculer_niveau_confiance_derive(
            methode_collecte="mesure_directe",
            fiabilite_source="haute",
        )
        == "A"
    )


def test_r4_catchall_donne_b_modele_satellitaire() -> None:
    """R4 catch-all : modele_satellitaire + source haute → B (cas NASA POWER)."""
    assert (
        calculer_niveau_confiance_derive(
            methode_collecte="modele_satellitaire",
            fiabilite_source="haute",
        )
        == "B"
    )


def test_r4_catchall_source_moyenne() -> None:
    assert (
        calculer_niveau_confiance_derive(
            methode_collecte="modele_satellitaire",
            fiabilite_source="moyenne",
        )
        == "B"
    )


def test_r4_catchall_mesure_directe_source_moyenne() -> None:
    """R3 ne s'applique qu'avec source haute. Source moyenne tombe en R4 = B."""
    assert (
        calculer_niveau_confiance_derive(
            methode_collecte="mesure_directe",
            fiabilite_source="moyenne",
        )
        == "B"
    )


def test_r4_catchall_methode_none() -> None:
    """methode None → tombe en R4 catch-all → B."""
    assert (
        calculer_niveau_confiance_derive(
            methode_collecte=None,
            fiabilite_source="haute",
        )
        == "B"
    )


def test_r4_catchall_fiabilite_none() -> None:
    """fiabilite None → tombe en R4 (R3 demande haute explicite) → B."""
    assert (
        calculer_niveau_confiance_derive(
            methode_collecte="mesure_directe",
            fiabilite_source=None,
        )
        == "B"
    )


def test_r1_prioritaire_sur_r2() -> None:
    """Si méthode = expertise_humaine ET source = faible : R1 matche en premier."""
    # Les deux donnent C dans les faits, mais sémantiquement R1 est prioritaire
    assert (
        calculer_niveau_confiance_derive(
            methode_collecte="expertise_humaine",
            fiabilite_source="faible",
        )
        == "C"
    )


# ---------------------------------------------------------------------------
# valider_niveau_confiance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("niveau", ["A", "B", "C"])
def test_valider_niveau_confiance_passe(niveau: str) -> None:
    valider_niveau_confiance(niveau)  # ne lève pas


@pytest.mark.parametrize("niveau", ["D", "a", "", "X", "AB"])
def test_valider_niveau_confiance_refuse(niveau: str) -> None:
    with pytest.raises(NiveauConfianceInvalide) as exc_info:
        valider_niveau_confiance(niveau)
    assert exc_info.value.valeur_recue == niveau


# ---------------------------------------------------------------------------
# overrider_niveau_confiance
# ---------------------------------------------------------------------------


def test_overrider_pose_override_et_justification() -> None:
    ligne = _LigneSimulee()
    overrider_niveau_confiance(ligne, "A", "Validation manuelle après audit campagne.")
    assert ligne.niveau_confiance_override == "A"
    assert ligne.commentaire_editorial is not None
    assert "Override -> A" in ligne.commentaire_editorial
    assert "Validation manuelle après audit campagne." in ligne.commentaire_editorial


def test_overrider_preserve_commentaire_existant() -> None:
    ligne = _LigneSimulee(commentaire_editorial="Commentaire initial.")
    overrider_niveau_confiance(ligne, "C", "Reclassement après incident QC.")
    assert ligne.commentaire_editorial is not None
    assert ligne.commentaire_editorial.startswith("Commentaire initial.")
    assert "Override -> C" in ligne.commentaire_editorial


def test_overrider_niveau_invalide_refuse() -> None:
    ligne = _LigneSimulee()
    with pytest.raises(NiveauConfianceInvalide):
        overrider_niveau_confiance(ligne, "D", "Justification valide.")


def test_overrider_sans_justification_refuse() -> None:
    ligne = _LigneSimulee()
    with pytest.raises(JustificationRequise):
        overrider_niveau_confiance(ligne, "A", "")
    with pytest.raises(JustificationRequise):
        overrider_niveau_confiance(ligne, "A", "   ")


# ---------------------------------------------------------------------------
# retirer_override_niveau_confiance
# ---------------------------------------------------------------------------


def test_retirer_override_remet_a_none() -> None:
    ligne = _LigneSimulee(
        niveau_confiance_override="A",
        commentaire_editorial="[Override -> A] Précédente justification.",
    )
    retirer_override_niveau_confiance(ligne, "Donnée recalculée, retour au dérivé.")
    assert ligne.niveau_confiance_override is None
    assert ligne.commentaire_editorial is not None
    assert "Retrait override" in ligne.commentaire_editorial


def test_retirer_override_sans_justification_refuse() -> None:
    ligne = _LigneSimulee(niveau_confiance_override="A")
    with pytest.raises(JustificationRequise):
        retirer_override_niveau_confiance(ligne, "")
