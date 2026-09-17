"""Tests unitaires du module `services.grandeurs.fraction_diffuse`.

Couvre 8 tests T-1 à T-8, symétrique de `test_hep.py` :

- T-1 à T-5 : fonction pure `_agreger_fraction_diffuse` (fixtures pures).
- T-6 et T-7 : garde-fous orchestrateur avec mock session SQLAlchemy.
- T-8 : régression niveau B pour `calcul_derive` + `haute`.
"""

from __future__ import annotations

import calendar as _calendar
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from kuma_data_core.editorial.niveaux_confiance import (
    calculer_niveau_confiance_derive,
)
from kuma_data_core.services.grandeurs.fraction_diffuse import (
    _agreger_fraction_diffuse,
    calculer_et_inserer_fraction_diffuse,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers de fixtures
# ---------------------------------------------------------------------------


def _serie_complete_annee(annee: int, valeur: float) -> list[tuple[date, float]]:
    debut = date(annee, 1, 1)
    fin = date(annee, 12, 31)
    nb_jours = (fin - debut).days + 1
    return [(debut + timedelta(days=i), valeur) for i in range(nb_jours)]


def _serie_complete_mois(annee: int, mois: int, valeur: float) -> list[tuple[date, float]]:
    nb_jours = _calendar.monthrange(annee, mois)[1]
    return [(date(annee, mois, j + 1), valeur) for j in range(nb_jours)]


# ---------------------------------------------------------------------------
# T-1 : Mapping unitaire ratio DHI/GHI
# ---------------------------------------------------------------------------


def test_t1_mapping_unitaire_ratio_dhi_ghi() -> None:
    """T-1 : DHI=2 et GHI=5 sur 28 jours février 2025 → fraction=0.4."""
    dhi = _serie_complete_mois(2025, 2, 2.0)
    ghi = _serie_complete_mois(2025, 2, 5.0)
    resultat = _agreger_fraction_diffuse(dhi, ghi)

    assert len(resultat["lignes_mensuelles"]) == 1
    assert len(resultat["lignes_annuelles"]) == 0
    ligne = resultat["lignes_mensuelles"][0]
    assert ligne["annee_debut"] == 2025
    assert ligne["mois"] == 2
    assert ligne["valeur"] == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# T-2 : Politique complétude annuelle stricte (1 jour manquant → skip)
# ---------------------------------------------------------------------------


def test_t2_completude_annuelle_skip_si_un_jour_dhi_manquant() -> None:
    """T-2 : si DHI manque 1 jour mais GHI complet → année + mois skip."""
    dhi = _serie_complete_annee(2025, 2.0)
    ghi = _serie_complete_annee(2025, 5.0)
    # Retire 2025-06-15 de DHI uniquement
    dhi = [(d, v) for (d, v) in dhi if d != date(2025, 6, 15)]
    assert len(dhi) == 364
    assert len(ghi) == 365

    resultat = _agreger_fraction_diffuse(dhi, ghi)

    assert resultat["lignes_annuelles"] == []
    assert resultat["annees_skip_completude"] == (2025,)
    # Juin est skip (1 jour manquant dans l'intersection)
    assert (2025, 6) in resultat["mois_skip_completude"]
    # 11 autres mois OK
    assert len(resultat["lignes_mensuelles"]) == 11


# ---------------------------------------------------------------------------
# T-3 : Politique complétude mensuelle stricte (mois incomplet → skip)
# ---------------------------------------------------------------------------


def test_t3_completude_mensuelle_stricte_skip_si_mois_incomplet() -> None:
    """T-3 : février 2025 avec 27 jours sur DHI et GHI → mois skip."""
    dhi = [(date(2025, 2, j), 2.0) for j in range(1, 28)]
    ghi = [(date(2025, 2, j), 5.0) for j in range(1, 28)]
    resultat = _agreger_fraction_diffuse(dhi, ghi)

    assert resultat["lignes_mensuelles"] == []
    assert resultat["mois_skip_completude"] == ((2025, 2),)


# ---------------------------------------------------------------------------
# T-4 : Sanity plage tropicale [0.2, 0.8]
# ---------------------------------------------------------------------------


def test_t4_sanity_plage_tropicale_fraction_diffuse_annuel() -> None:
    """T-4 : DHI 30% de GHI sur année complète (régime tropical typique)
    → fraction_diffuse_annuel ≈ 0.3, dans plage [0.2, 0.8] attendue."""
    dhi = _serie_complete_annee(2025, 1.65)  # 30% de 5.5 ≈ 1.65
    ghi = _serie_complete_annee(2025, 5.5)
    resultat = _agreger_fraction_diffuse(dhi, ghi)

    assert len(resultat["lignes_annuelles"]) == 1
    fd_annuel = resultat["lignes_annuelles"][0]["valeur"]
    assert fd_annuel == pytest.approx(0.3)
    assert 0.2 <= fd_annuel <= 0.8


# ---------------------------------------------------------------------------
# T-5 : Invariance fraction_diffuse ∈ [0, 1] sur série variable
# ---------------------------------------------------------------------------


def test_t5_invariance_fraction_dans_zero_un() -> None:
    """T-5 : fraction_diffuse mathématiquement garantie ∈ [0, 1] tant que
    DHI ≤ GHI (cohérence physique).

    Substitut additif au T-5 HEP (qui vérifiait sum mensuel = annuel,
    non applicable à un ratio non-additif).
    """
    debut = date(2025, 1, 1)
    nb_jours = 365
    # GHI variable, DHI = 30-50% de GHI (typique tropical)
    ghi = [(debut + timedelta(days=i), 4.5 + 1.5 * ((i % 30) / 30.0)) for i in range(nb_jours)]
    dhi = [(d, v * 0.4) for (d, v) in ghi]  # 40% systématique

    resultat = _agreger_fraction_diffuse(dhi, ghi)
    assert len(resultat["lignes_annuelles"]) == 1
    assert len(resultat["lignes_mensuelles"]) == 12
    for ligne in resultat["lignes_annuelles"] + resultat["lignes_mensuelles"]:
        assert 0.0 <= ligne["valeur"] <= 1.0


# ---------------------------------------------------------------------------
# T-6 : RuntimeError si série DHI amont absente
# ---------------------------------------------------------------------------


def test_t6_runtime_error_si_serie_dhi_amont_absente() -> None:
    """T-6 : code_serie_dhi_amont inexistant → RuntimeError."""
    session = MagicMock()
    serie_cible_row = MagicMock(
        serie_id=42,
        localite_id=1,
        grandeur_code="fraction_diffuse",
        methode_collecte="calcul_derive",
        fiabilite_source="haute",
    )
    session.execute.side_effect = [
        MagicMock(scalar=MagicMock(return_value=1)),  # version actuelle
        MagicMock(first=MagicMock(return_value=serie_cible_row)),  # serie cible
        MagicMock(first=MagicMock(return_value=None)),  # serie DHI -> None
    ]

    with pytest.raises(RuntimeError, match=r"Serie DHI amont .* introuvable"):
        calculer_et_inserer_fraction_diffuse(
            session=session,
            code_serie_fraction_diffuse="gin_test_fraction_diffuse",
            code_serie_dhi_amont="gin_test_dhi_inexistant",
            code_serie_ghi_amont="gin_test_ghi",
        )


# ---------------------------------------------------------------------------
# T-7 : RuntimeError si version_formule désalignée
# ---------------------------------------------------------------------------


def test_t7_runtime_error_si_version_formule_desalignee() -> None:
    """T-7 : argument version_formule=2 alors que version_formule_actuelle=1."""
    session = MagicMock()
    session.execute.return_value.scalar.return_value = 1

    with pytest.raises(RuntimeError, match="Desalignement version_formule"):
        calculer_et_inserer_fraction_diffuse(
            session=session,
            code_serie_fraction_diffuse="gin_test_fraction_diffuse",
            code_serie_dhi_amont="gin_test_dhi",
            code_serie_ghi_amont="gin_test_ghi",
            version_formule=2,
        )


# ---------------------------------------------------------------------------
# T-8 : Niveau B pour calcul_derive + fiabilité haute (R4)
# ---------------------------------------------------------------------------


def test_t8_niveau_b_pour_calcul_derive_avec_fiabilite_haute() -> None:
    """T-8 : régression Drift 6 - niveau dérivé attendu 'B' (R4 catch-all)."""
    niveau = calculer_niveau_confiance_derive(
        methode_collecte="calcul_derive",
        fiabilite_source="haute",
    )
    assert niveau == "B"
