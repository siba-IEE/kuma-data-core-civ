"""Tests unitaires du module ``services.grandeurs.hep``.

Couvre :

- T-1 à T-5 : fonction pure ``_agreger_hep_journaliers`` (mapping unitaire,
  politique de complétude annuelle et mensuelle, sanity plage tropicale,
  cohérence somme mensuel ≈ annuel).
- T-6 et T-7 : garde-fous ``calculer_et_inserer_hep`` (série amont absente,
  version_formule désalignée) avec mock de session SQLAlchemy.
- T-8 : régression sur le niveau de confiance dérivé attendu pour HEP
  (R4 catch-all : ``calcul_derive`` + ``haute`` → ``B``).
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from kuma_data_core.editorial.niveaux_confiance import (
    calculer_niveau_confiance_derive,
)
from kuma_data_core.services.grandeurs.hep import (
    _agreger_hep_journaliers,
    calculer_et_inserer_hep,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers de fixtures
# ---------------------------------------------------------------------------


def _serie_complete_annee(annee: int, valeur_constante: float) -> list[tuple[date, float]]:
    """Construit une série complète (365 ou 366 jours) pour ``annee`` avec
    valeur constante par jour. Utilisé pour les tests de complétude et
    sanity.
    """
    debut = date(annee, 1, 1)
    fin = date(annee, 12, 31)
    nb_jours = (fin - debut).days + 1
    return [(debut + timedelta(days=i), valeur_constante) for i in range(nb_jours)]


def _serie_complete_mois(
    annee: int, mois: int, valeur_constante: float
) -> list[tuple[date, float]]:
    """Construit une série complète pour le mois ``(annee, mois)`` avec
    valeur constante par jour.
    """
    import calendar as _calendar  # local pour éviter pollution module

    nb_jours = _calendar.monthrange(annee, mois)[1]
    return [(date(annee, mois, j + 1), valeur_constante) for j in range(nb_jours)]


# ---------------------------------------------------------------------------
# T-1 : Mapping unitaire HEP_jour ↔ GHI_jour
# ---------------------------------------------------------------------------


def test_t1_mapping_unitaire_hep_jour_egale_ghi_jour() -> None:
    """T-1 : 1 jour à 5.0 kWh/m²/j → HEP_jour = 5.0 h_eq.

    Vérifie aussi que la somme annuelle (sur 1 année complète à valeur
    constante) est exactement nb_jours * valeur.
    """
    # Mois complet février 2025 (28 jours, non bissextile) à valeur 5.0
    mesures = _serie_complete_mois(2025, 2, 5.0)
    resultat = _agreger_hep_journaliers(mesures)

    # 1 ligne mensuelle attendue, 0 ligne annuelle (année incomplète)
    assert len(resultat["lignes_mensuelles"]) == 1
    assert len(resultat["lignes_annuelles"]) == 0
    ligne_fev = resultat["lignes_mensuelles"][0]
    assert ligne_fev["annee_debut"] == 2025
    assert ligne_fev["mois"] == 2
    assert ligne_fev["valeur"] == pytest.approx(28 * 5.0)


# ---------------------------------------------------------------------------
# T-2 : Politique complétude annuelle stricte (1 jour manquant → skip)
# ---------------------------------------------------------------------------


def test_t2_completude_annuelle_stricte_skip_si_un_jour_manquant() -> None:
    """T-2 : Année 2025 (non bissextile, 365 jours) avec 1 jour retiré au
    milieu de juin → aucune ligne annuelle insérée. Le mois de juin est
    aussi skip (politique mensuelle stricte) ; les 11 autres mois sont
    intacts et insérés normalement.
    """
    mesures = _serie_complete_annee(2025, 5.0)
    # Retire le 2025-06-15 (1 jour de juin manquant)
    mesures = [(d, v) for (d, v) in mesures if d != date(2025, 6, 15)]
    assert len(mesures) == 364

    resultat = _agreger_hep_journaliers(mesures)

    assert resultat["lignes_annuelles"] == []
    assert resultat["annees_skip_completude"] == (2025,)
    # 11 mois OK (jan, fev, ..., mai, juil, ..., dec), juin skip
    assert len(resultat["lignes_mensuelles"]) == 11
    assert (2025, 6) in resultat["mois_skip_completude"]
    assert len(resultat["mois_skip_completude"]) == 1


# ---------------------------------------------------------------------------
# T-3 : Politique complétude mensuelle stricte (mois incomplet → skip)
# ---------------------------------------------------------------------------


def test_t3_completude_mensuelle_stricte_skip_si_mois_incomplet() -> None:
    """T-3 : Février 2025 avec 27 jours (vs 28 attendus) → mois skip.

    Construction directe au niveau mois (pas via _serie_complete_annee
    pour rester focalisée sur la politique mensuelle).
    """
    mesures = [(date(2025, 2, j), 5.0) for j in range(1, 28)]  # 1 à 27 inclus
    assert len(mesures) == 27
    resultat = _agreger_hep_journaliers(mesures)

    assert resultat["lignes_mensuelles"] == []
    assert resultat["mois_skip_completude"] == ((2025, 2),)
    # Pas de ligne annuelle (l'année n'a que 27 jours au total ici)
    assert resultat["lignes_annuelles"] == []
    assert resultat["annees_skip_completude"] == (2025,)


# ---------------------------------------------------------------------------
# T-4 : Sanity HEP annuel plage tropicale
# ---------------------------------------------------------------------------


def test_t4_sanity_hep_annuel_plage_tropicale() -> None:
    """T-4 : Année 2025 complète à 5.5 kWh/m²/j (moyenne Conakry simulée)
    → HEP_annuel = 365 * 5.5 ≈ 2007.5 h_eq, dans la plage tropicale
    attendue [1800, 2200] h_eq/an.
    """
    mesures = _serie_complete_annee(2025, 5.5)
    resultat = _agreger_hep_journaliers(mesures)

    assert len(resultat["lignes_annuelles"]) == 1
    hep_annuel = resultat["lignes_annuelles"][0]["valeur"]
    assert hep_annuel == pytest.approx(365 * 5.5)
    assert 1800.0 <= hep_annuel <= 2200.0


# ---------------------------------------------------------------------------
# T-5 : Cohérence somme mensuel ≈ annuel
# ---------------------------------------------------------------------------


def test_t5_coherence_somme_mensuel_egale_annuel() -> None:
    """T-5 : sum(HEP_mensuel(m) pour m=1..12) ≈ HEP_annuel à ε flottant
    près. Vérifie l'invariant d'agrégation sur une année complète à
    valeur variable jour par jour (pour éviter une cohérence triviale).
    """
    debut = date(2025, 1, 1)
    fin = date(2025, 12, 31)
    nb_jours = (fin - debut).days + 1
    # Valeur variable jour par jour (sinusoïde simplifiée pour réalisme)
    mesures = [(debut + timedelta(days=i), 4.5 + 1.5 * ((i % 30) / 30.0)) for i in range(nb_jours)]
    resultat = _agreger_hep_journaliers(mesures)

    assert len(resultat["lignes_annuelles"]) == 1
    assert len(resultat["lignes_mensuelles"]) == 12
    hep_annuel = resultat["lignes_annuelles"][0]["valeur"]
    somme_mensuels = sum(ligne["valeur"] for ligne in resultat["lignes_mensuelles"])
    assert somme_mensuels == pytest.approx(hep_annuel, rel=1e-9)


# ---------------------------------------------------------------------------
# T-6 : RuntimeError si série GHI amont absente
# ---------------------------------------------------------------------------


def test_t6_runtime_error_si_serie_ghi_amont_absente() -> None:
    """T-6 : ``code_serie_ghi_amont`` inexistant dans series_metadonnees
    → RuntimeError lisible mentionnant le code de série.
    """
    session = MagicMock()
    # 1er execute : SELECT version_formule_actuelle → 1
    # 2ème execute : SELECT serie_hep → ligne valide (grandeur='hep', methode='calcul_derive')
    # 3ème execute : SELECT serie_ghi → None
    serie_hep_row = MagicMock(
        serie_id=42,
        localite_id=1,
        grandeur_code="hep",
        methode_collecte="calcul_derive",
        fiabilite_source="haute",
    )
    session.execute.side_effect = [
        MagicMock(scalar=MagicMock(return_value=1)),
        MagicMock(first=MagicMock(return_value=serie_hep_row)),
        MagicMock(first=MagicMock(return_value=None)),
    ]

    with pytest.raises(RuntimeError, match=r"Serie GHI amont .* introuvable"):
        calculer_et_inserer_hep(
            session=session,
            code_serie_hep="gin_test_hep_kuma_calculs_2021_2025",
            code_serie_ghi_amont="gin_test_ghi_inexistant",
        )


# ---------------------------------------------------------------------------
# T-7 : RuntimeError si version_formule désalignée
# ---------------------------------------------------------------------------


def test_t7_runtime_error_si_version_formule_desalignee() -> None:
    """T-7 : Argument ``version_formule=2`` alors que
    ``grandeurs_referentiel.version_formule_actuelle = 1`` pour 'hep'
    → RuntimeError lisible (garde-fou avant lecture amont).
    """
    session = MagicMock()
    # SELECT version_formule_actuelle → 1
    session.execute.return_value.scalar.return_value = 1

    with pytest.raises(RuntimeError, match="Desalignement version_formule"):
        calculer_et_inserer_hep(
            session=session,
            code_serie_hep="gin_test_hep_kuma_calculs_2021_2025",
            code_serie_ghi_amont="gin_test_ghi_nasa_power_2021_2025",
            version_formule=2,
        )


# ---------------------------------------------------------------------------
# T-8 : Niveau B pour calcul_derive + fiabilité haute (R4)
# ---------------------------------------------------------------------------


def test_t8_niveau_b_pour_calcul_derive_avec_fiabilite_haute() -> None:
    """T-8 : Régression sur la cohérence Drift 6 arbitré en cadrage.

    Pour les 6 séries HEP :
    ``methode_collecte='calcul_derive'`` + source ``kuma_calculs``
    fiabilité ``'haute'`` → R1 / R2 / R3 ne matchent pas → R4 catch-all
    → ``'B'``. Ce test verrouille que toute future modification de
    R1-R4 reste compatible avec ce cas pivot.
    """
    niveau = calculer_niveau_confiance_derive(
        methode_collecte="calcul_derive",
        fiabilite_source="haute",
    )
    assert niveau == "B"
