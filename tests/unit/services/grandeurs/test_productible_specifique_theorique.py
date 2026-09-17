"""Tests unitaires du module `services.grandeurs.productible_specifique_theorique`.

8 tests T-1 à T-8 + T-9 (PR paramétrable).

Particularité : pas de fonction d'agrégation pure type
`_agreger_<grandeur>` car les périodes sont héritées de HEP amont (pas
d'agrégation à refaire). T-1 à T-5 testent `_appliquer_pr_theorique` et
des cas d'erreur métier.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from kuma_data_core.editorial.niveaux_confiance import (
    calculer_niveau_confiance_derive,
)
from kuma_data_core.services.grandeurs.productible_specifique_theorique import (
    PR_THEORIQUE_DEFAUT,
    _appliquer_pr_theorique,
    calculer_et_inserer_productible_specifique_theorique,
)

pytestmark = pytest.mark.unit


def test_t1_mapping_unitaire_hep_par_pr_theorique_defaut() -> None:
    """T-1 : HEP=2000 * PR=0.8 → productible=1600."""
    assert _appliquer_pr_theorique(2000.0, PR_THEORIQUE_DEFAUT) == pytest.approx(1600.0)


def test_t2_pr_theorique_un_redonne_hep() -> None:
    """T-2 : PR=1.0 (théorique strict) → productible = HEP."""
    assert _appliquer_pr_theorique(1850.0, 1.0) == pytest.approx(1850.0)


def test_t3_pr_theorique_zero_donne_zero() -> None:
    """T-3 : PR=0.0 (cas dégénéré) → productible = 0."""
    assert _appliquer_pr_theorique(2000.0, 0.0) == pytest.approx(0.0)


def test_t4_sanity_plage_tropicale_avec_pr_default() -> None:
    """T-4 : sanity plage tropicale avec PR=0.8.

    HEP Guinée pilote ∈ [1727, 2060] (observé) → productible
    ∈ [1381, 1648] kWh/kWc/an.
    """
    for hep_observe in (1727.0, 1850.0, 2060.0):
        prod = _appliquer_pr_theorique(hep_observe, PR_THEORIQUE_DEFAUT)
        assert 1381.0 <= prod <= 1648.0


def test_t5_pr_parametrable_industry_standards() -> None:
    """T-5 : PR paramétrable selon norme métier.

    Vérifie linéarité productible = HEP * PR sur plusieurs PR
    industry-standards : 0.75 (conservateur), 0.8 (défaut Kuma), 0.85
    (médian), 0.84 (NREL PVWatts).
    """
    hep = 2000.0
    for pr in (0.75, 0.80, 0.85, 0.84):
        assert _appliquer_pr_theorique(hep, pr) == pytest.approx(hep * pr)


def test_t6_runtime_error_si_serie_hep_amont_absente() -> None:
    """T-6 : code_serie_hep_amont inexistant → RuntimeError."""
    session = MagicMock()
    serie_cible_row = MagicMock(
        serie_id=42,
        localite_id=1,
        grandeur_code="productible_specifique_theorique",
        methode_collecte="calcul_derive",
        fiabilite_source="haute",
    )
    session.execute.side_effect = [
        MagicMock(scalar=MagicMock(return_value=1)),  # version actuelle
        MagicMock(first=MagicMock(return_value=serie_cible_row)),  # serie cible
        MagicMock(first=MagicMock(return_value=None)),  # serie HEP -> None
    ]
    with pytest.raises(RuntimeError, match=r"Serie HEP amont .* introuvable"):
        calculer_et_inserer_productible_specifique_theorique(
            session=session,
            code_serie_productible="gin_test_productible",
            code_serie_hep_amont="gin_test_hep_inexistant",
        )


def test_t7_runtime_error_si_version_formule_desalignee() -> None:
    """T-7 : version_formule=2 mais version_formule_actuelle=1."""
    session = MagicMock()
    session.execute.return_value.scalar.return_value = 1
    with pytest.raises(RuntimeError, match="Desalignement version_formule"):
        calculer_et_inserer_productible_specifique_theorique(
            session=session,
            code_serie_productible="gin_test_productible",
            code_serie_hep_amont="gin_test_hep",
            version_formule=2,
        )


def test_t8_niveau_b_pour_calcul_derive_avec_fiabilite_haute() -> None:
    """T-8 : régression Drift 6."""
    assert (
        calculer_niveau_confiance_derive(methode_collecte="calcul_derive", fiabilite_source="haute")
        == "B"
    )
