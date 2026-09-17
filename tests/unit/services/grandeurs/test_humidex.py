"""Tests unitaires du module `services.grandeurs.humidex`.

8 tests T-1 à T-8.

T-1 vérifie la référence numérique Masterton & Richardson 1979 :
T = 30 °C, RH = 70 % → H ≈ 40.95 °C apparents.
"""

from __future__ import annotations

import calendar as _calendar
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from kuma_data_core.editorial.niveaux_confiance import (
    calculer_niveau_confiance_derive,
)
from kuma_data_core.services.grandeurs.humidex import (
    _agreger_humidex,
    _calculer_humidex_journalier,
    calculer_et_inserer_humidex,
)

pytestmark = pytest.mark.unit


def _serie_complete_annee(annee: int, valeur: float) -> list[tuple[date, float]]:
    debut = date(annee, 1, 1)
    fin = date(annee, 12, 31)
    return [(debut + timedelta(days=i), valeur) for i in range((fin - debut).days + 1)]


def _serie_complete_mois(annee: int, mois: int, valeur: float) -> list[tuple[date, float]]:
    nb = _calendar.monthrange(annee, mois)[1]
    return [(date(annee, mois, j + 1), valeur) for j in range(nb)]


def test_t1_reference_masterton_richardson_30c_70pct() -> None:
    """T-1 : référence numérique T=30°C, RH=70% → H ≈ 40.95°C apparents.

    Calcul manuel :
        e = 0.7 * 6.112 * exp(17.67 * 30 / (30 + 243.5))
          = 0.7 * 6.112 * exp(530.1/273.5)
          = 0.7 * 6.112 * 6.945 ≈ 29.71 hPa
        H = 30 + (5/9) * (29.71 - 10) = 30 + 10.95 ≈ 40.95°C
    """
    h = _calculer_humidex_journalier(t_celsius=30.0, rh_pourcent=70.0)
    assert h == pytest.approx(40.95, abs=0.05)


def test_t2_completude_annuelle_skip_si_t2m_jour_manquant() -> None:
    """T-2 : T2M manque 1 jour → année et juin skip."""
    t2m = _serie_complete_annee(2025, 28.0)
    rh2m = _serie_complete_annee(2025, 75.0)
    t2m = [(d, v) for (d, v) in t2m if d != date(2025, 6, 15)]
    resultat = _agreger_humidex(t2m, rh2m)

    assert resultat["lignes_annuelles"] == []
    assert resultat["annees_skip_completude"] == (2025,)
    assert (2025, 6) in resultat["mois_skip_completude"]
    assert len(resultat["lignes_mensuelles"]) == 11


def test_t3_completude_mensuelle_skip_si_mois_incomplet() -> None:
    """T-3 : février 27 jours → mois skip."""
    t2m = [(date(2025, 2, j), 28.0) for j in range(1, 28)]
    rh2m = [(date(2025, 2, j), 75.0) for j in range(1, 28)]
    resultat = _agreger_humidex(t2m, rh2m)
    assert resultat["lignes_mensuelles"] == []
    assert (2025, 2) in resultat["mois_skip_completude"]


def test_t4_sanity_nb_jours_inconfort_conakry_tropical() -> None:
    """T-4 : fixture Conakry simulée (T=28°C, RH=80% constant → H ≈ 38°C
    apparents < seuil 40°C, donc nb_jours_inconfort = 0). Avec
    T = 30°C constants → H ≈ 42°C donc nb_jours_inconfort = 365 (tous
    les jours)."""
    # Cas froid (H < 40)
    t2m = _serie_complete_annee(2025, 28.0)
    rh2m = _serie_complete_annee(2025, 80.0)
    res = _agreger_humidex(t2m, rh2m, seuil_inconfort_modere=40.0)
    assert res["nb_jours_inconfort_modere_par_annee"][2025] == 0

    # Cas chaud (H > 40)
    t2m2 = _serie_complete_annee(2025, 30.0)
    rh2m2 = _serie_complete_annee(2025, 80.0)
    res2 = _agreger_humidex(t2m2, rh2m2, seuil_inconfort_modere=40.0)
    assert res2["nb_jours_inconfort_modere_par_annee"][2025] == 365


def test_t5_invariance_humidex_superieur_egal_temperature() -> None:
    """T-5 : H ≥ T quand RH > 0 (e > 10 dès que RH > 0 et T > 0 °C).

    Substitut non-additif au T-5 HEP. Invariance physique de l'indice
    humidex : il ne peut pas être inférieur à la température sèche.

    Note : sous certaines conditions extrêmes (T très bas), e peut < 10
    hPa et H < T. La fixture ici utilise T tropical [25, 32]°C où
    l'invariant tient strictement.
    """
    t2m = _serie_complete_annee(2025, 30.0)
    rh2m = [(d, 50.0 + (i % 30)) for (i, (d, _)) in enumerate(t2m)]
    res = _agreger_humidex(t2m, rh2m)
    assert len(res["lignes_annuelles"]) == 1
    assert len(res["lignes_mensuelles"]) == 12
    # Humidex moyen ≥ T moyen (30°C)
    assert res["lignes_annuelles"][0]["valeur"] >= 30.0


def test_t6_runtime_error_si_serie_t2m_amont_absente() -> None:
    """T-6 : code_serie_t2m_amont inexistant → RuntimeError."""
    session = MagicMock()
    serie_cible_row = MagicMock(
        serie_id=42,
        localite_id=1,
        grandeur_code="humidex",
        methode_collecte="calcul_derive",
        fiabilite_source="haute",
    )
    session.execute.side_effect = [
        MagicMock(scalar=MagicMock(return_value=1)),
        MagicMock(first=MagicMock(return_value=serie_cible_row)),
        MagicMock(first=MagicMock(return_value=None)),
    ]
    with pytest.raises(RuntimeError, match=r"Serie T2M amont .* introuvable"):
        calculer_et_inserer_humidex(
            session=session,
            code_serie_humidex="gin_test_humidex",
            code_serie_t2m_amont="gin_test_t2m_inexistant",
            code_serie_rh2m_amont="gin_test_rh2m",
        )


def test_t7_runtime_error_si_version_formule_desalignee() -> None:
    """T-7 : version_formule=2 mais version_formule_actuelle=1."""
    session = MagicMock()
    session.execute.return_value.scalar.return_value = 1
    with pytest.raises(RuntimeError, match="Desalignement version_formule"):
        calculer_et_inserer_humidex(
            session=session,
            code_serie_humidex="gin_test_humidex",
            code_serie_t2m_amont="gin_test_t2m",
            code_serie_rh2m_amont="gin_test_rh2m",
            version_formule=2,
        )


def test_t8_niveau_b_pour_calcul_derive_avec_fiabilite_haute() -> None:
    """T-8 : régression Drift 6."""
    assert (
        calculer_niveau_confiance_derive(methode_collecte="calcul_derive", fiabilite_source="haute")
        == "B"
    )
