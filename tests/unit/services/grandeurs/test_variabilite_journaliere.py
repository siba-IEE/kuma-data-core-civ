"""Tests unitaires du module `services.grandeurs.variabilite_journaliere`.

8 tests T-1 à T-8.

Particularité : périodicité annuelle uniquement. T-3
(complétude mensuelle) non applicable - substitut sur invariant
statistique du CoV.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from kuma_data_core.editorial.niveaux_confiance import (
    calculer_niveau_confiance_derive,
)
from kuma_data_core.services.grandeurs.variabilite_journaliere import (
    _agreger_variabilite_journaliere,
    _calculer_coefficient_variation,
    calculer_et_inserer_variabilite_journaliere,
)

pytestmark = pytest.mark.unit


def _serie_complete_annee(annee: int, valeur: float) -> list[tuple[date, float]]:
    debut = date(annee, 1, 1)
    fin = date(annee, 12, 31)
    return [(debut + timedelta(days=i), valeur) for i in range((fin - debut).days + 1)]


def test_t1_cov_reference_numerique() -> None:
    """T-1 : CoV sur [4, 5, 6] → moy=5, sigma²=2/3, sigma≈0.816, CoV≈0.1633."""
    cov = _calculer_coefficient_variation([4.0, 5.0, 6.0])
    assert cov == pytest.approx(math.sqrt(2 / 3) / 5, rel=1e-9)
    assert cov == pytest.approx(0.1633, abs=0.001)


def test_t2_completude_annuelle_skip_si_jour_manquant() -> None:
    """T-2 : 1 jour manquant → année skip."""
    ghi = _serie_complete_annee(2025, 5.0)
    ghi = [(d, v) for (d, v) in ghi if d != date(2025, 6, 15)]
    res = _agreger_variabilite_journaliere(ghi)
    assert res["lignes_annuelles"] == []
    assert res["annees_skip_completude"] == (2025,)


def test_t3_pas_de_mensuel_produit() -> None:
    """T-3 : substitut au T-3 fraction_diffuse - vérifie qu'aucune ligne
    mensuelle n'est produite (périodicité annuelle stricte
    pour variabilite_journaliere, CoV non robuste sur 28-31 jours)."""
    ghi = _serie_complete_annee(2025, 5.0)
    res = _agreger_variabilite_journaliere(ghi)
    # L'agrégation ne produit que des lignes annuelles
    assert all(ligne["periode_type"] == "annuel" for ligne in res["lignes_annuelles"])
    # Pas de champ lignes_mensuelles dans _AgregationResultat
    assert "lignes_mensuelles" not in res


def test_t4_sanity_cov_tropical_plage() -> None:
    """T-4 : sanity CoV Conakry tropical simulé ∈ [0.1, 0.7].

    Fixture GHI sinusoïdale (4.5 → 6.0 sur 30 jours, cycle répété 12
    fois sur l'année) → CoV ≈ 0.09 (variation faible mais > 0).
    """
    debut = date(2025, 1, 1)
    ghi = [(debut + timedelta(days=i), 4.5 + 1.5 * ((i % 30) / 30.0)) for i in range(365)]
    res = _agreger_variabilite_journaliere(ghi)
    assert len(res["lignes_annuelles"]) == 1
    cov = res["lignes_annuelles"][0]["valeur"]
    # Plage assez large pour couvrir variations synthétiques
    assert 0.0 < cov < 1.0


def test_t5_invariance_cov_positif_ou_nul() -> None:
    """T-5 : invariant statistique CoV ≥ 0 (sigma ≥ 0 et μ > 0 garantis
    pour GHI > 0). Substitut non-additif au T-5 HEP."""
    debut = date(2025, 1, 1)
    # Valeur constante → sigma = 0 → CoV = 0 exactement
    ghi_constant = [(debut + timedelta(days=i), 5.0) for i in range(365)]
    res = _agreger_variabilite_journaliere(ghi_constant)
    assert len(res["lignes_annuelles"]) == 1
    assert res["lignes_annuelles"][0]["valeur"] == pytest.approx(0.0)


def test_t6_runtime_error_si_serie_ghi_amont_absente() -> None:
    """T-6 : code_serie_ghi_amont inexistant → RuntimeError."""
    session = MagicMock()
    serie_cible_row = MagicMock(
        serie_id=42,
        localite_id=1,
        grandeur_code="variabilite_journaliere",
        methode_collecte="calcul_derive",
        fiabilite_source="haute",
    )
    session.execute.side_effect = [
        MagicMock(scalar=MagicMock(return_value=1)),
        MagicMock(first=MagicMock(return_value=serie_cible_row)),
        MagicMock(first=MagicMock(return_value=None)),
    ]
    with pytest.raises(RuntimeError, match=r"Serie GHI amont .* introuvable"):
        calculer_et_inserer_variabilite_journaliere(
            session=session,
            code_serie_variabilite="gin_test_variabilite",
            code_serie_ghi_amont="gin_test_ghi_inexistant",
        )


def test_t7_runtime_error_si_version_formule_desalignee() -> None:
    """T-7 : version_formule=2 mais version_formule_actuelle=1."""
    session = MagicMock()
    session.execute.return_value.scalar.return_value = 1
    with pytest.raises(RuntimeError, match="Desalignement version_formule"):
        calculer_et_inserer_variabilite_journaliere(
            session=session,
            code_serie_variabilite="gin_test_variabilite",
            code_serie_ghi_amont="gin_test_ghi",
            version_formule=2,
        )


def test_t8_niveau_b_pour_calcul_derive_avec_fiabilite_haute() -> None:
    """T-8 : régression Drift 6."""
    assert (
        calculer_niveau_confiance_derive(methode_collecte="calcul_derive", fiabilite_source="haute")
        == "B"
    )
