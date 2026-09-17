"""Tests d'intégration des séries solaires brutes (migrations 0008-0010).

Irradiation mensuelle aux 3 points CIV, paramétré par seed de série :
- GHI NASA POWER 1991-2020 (360 mesures, ADR-0007) ;
- DNI NASA POWER 2001-2020 (240 mesures — le DNI NASA POWER commence en 2001) ;
- GHI SARAH-3/PVGIS 2005-2020 (192 mesures, ADR-0008).
Métadonnées de série, complétude, invariants (mois 1-12, confiance B, statut
brut, bornes) et fidélité au seed. Chaque seed porte sa source, sa grandeur et
sa période — le test les lit du module, sans littéral en dur.
"""

from __future__ import annotations

from types import ModuleType

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds import series_nasa_power_dni_mensuel_civ as np_dni
from kuma_data_core.db.seeds import series_nasa_power_ghi_mensuel_civ as np_ghi
from kuma_data_core.db.seeds import series_pvgis_sarah3_ghi_mensuel_civ as sarah3_ghi

pytestmark = pytest.mark.integration

_SEEDS = [np_ghi, np_dni, sarah3_ghi]


def _id(seed: ModuleType) -> str:
    return f"{seed.SOURCE_CODE}:{seed.GRANDEUR_CODE}"


def _attendu_mois(seed: ModuleType) -> int:
    return (seed.ANNEE_FIN - seed.ANNEE_DEBUT + 1) * 12


@pytest.mark.parametrize("seed", _SEEDS, ids=_id)
def test_series_metadonnees(db_session: Session, seed: ModuleType) -> None:
    """Chaque série porte les bonnes métadonnées (source, grandeur, période, localité)."""
    codes = [s["code"] for s in seed.SERIES]
    lignes = db_session.execute(
        text(
            """
            SELECT s.code, s.grandeur_code, s.granularite, s.methode_collecte,
                   s.periode_debut, s.periode_fin, src.code AS source, loc.code AS localite
            FROM series_metadonnees s
            JOIN sources src ON src.id = s.source_id
            JOIN localites loc ON loc.id = s.localite_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": codes},
    ).all()
    assert {r.code for r in lignes} == set(codes)
    localites = {s["code"]: s["localite_code"] for s in seed.SERIES}
    for r in lignes:
        assert r.grandeur_code == seed.GRANDEUR_CODE, r.code
        assert r.granularite == "mensuel", r.code
        assert r.methode_collecte == "modele_satellitaire", r.code
        assert r.source == seed.SOURCE_CODE, r.code
        assert str(r.periode_debut) == seed.PERIODE_DEBUT and str(r.periode_fin) == seed.PERIODE_FIN
        assert r.localite == localites[r.code], r.code


@pytest.mark.parametrize("seed", _SEEDS, ids=_id)
def test_completude_mesures(db_session: Session, seed: ModuleType) -> None:
    """Chaque série a le bon nombre de mesures, mois 1-12, années dans la période."""
    for code in (s["code"] for s in seed.SERIES):
        rows = db_session.execute(
            text(
                """
                SELECT m.annee, m.mois FROM mesures_ressource_mensuelles m
                JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = :c
                """
            ),
            {"c": code},
        ).all()
        assert len(rows) == _attendu_mois(seed), code
        assert {r.mois for r in rows} == set(range(1, 13)), code
        assert {r.annee for r in rows} == set(range(seed.ANNEE_DEBUT, seed.ANNEE_FIN + 1)), code


@pytest.mark.parametrize("seed", _SEEDS, ids=_id)
def test_invariants_mesures(db_session: Session, seed: ModuleType) -> None:
    """Toutes les mesures : statut brut, confiance B, valeur positive."""
    codes = [s["code"] for s in seed.SERIES]
    rows = db_session.execute(
        text(
            """
            SELECT m.statut, m.niveau_confiance_derive, m.valeur
            FROM mesures_ressource_mensuelles m
            JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": codes},
    ).all()
    assert len(rows) == _attendu_mois(seed) * len(codes)
    for r in rows:
        assert r.statut == "brut"
        assert r.niveau_confiance_derive == "B"
        assert 0.0 <= r.valeur <= 9.0


@pytest.mark.parametrize("seed", _SEEDS, ids=_id)
def test_unite_heritee_de_la_grandeur(db_session: Session, seed: ModuleType) -> None:
    """La grandeur de la série fixe l'unité kWh/m²/jour (kwh_par_m2_jour)."""
    unite = db_session.execute(
        text(
            """
            SELECT u.code AS unite_code
            FROM series_metadonnees s
            JOIN grandeurs_referentiel g ON g.code = s.grandeur_code
            JOIN unites u ON u.id = g.unite_id
            WHERE s.code = :c
            """
        ),
        {"c": seed.SERIES[0]["code"]},
    ).scalar_one()
    assert unite == "kwh_par_m2_jour"


@pytest.mark.parametrize("seed", _SEEDS, ids=_id)
def test_valeurs_fideles_au_seed(db_session: Session, seed: ModuleType) -> None:
    """Les valeurs gravées correspondent exactement au seed (bornes de chaque série)."""
    for s in seed.SERIES:
        for annee, mois, attendu in (s["mesures"][0], s["mesures"][-1]):
            valeur = db_session.execute(
                text(
                    """
                    SELECT m.valeur FROM mesures_ressource_mensuelles m
                    JOIN series_metadonnees s ON s.id = m.serie_id
                    WHERE s.code = :c AND m.annee = :a AND m.mois = :mo
                    """
                ),
                {"c": s["code"], "a": annee, "mo": mois},
            ).scalar_one()
            assert valeur == pytest.approx(attendu), (s["code"], annee, mois)
