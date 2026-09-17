"""Tests d'intégration de la première série solaire brute (migration 0008).

GHI mensuel NASA POWER, climatologie 1991-2020, 3 points CIV (ADR-0007) :
métadonnées de série, complétude (360 mesures/série), invariants (mois 1-12,
confiance B, statut brut, bornes physiques) et fidélité au seed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds.series_nasa_power_ghi_mensuel_civ import SERIES

pytestmark = pytest.mark.integration

_CODES = [s["code"] for s in SERIES]


def test_trois_series_nasa_power(db_session: Session) -> None:
    """3 séries NASA POWER GHI mensuel, rattachées à leur localité et à la source."""
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
        {"c": _CODES},
    ).all()
    assert {r.code for r in lignes} == set(_CODES)
    localites_attendues = {s["code"]: s["localite_code"] for s in SERIES}
    for r in lignes:
        assert r.grandeur_code == "ghi", r.code
        assert r.granularite == "mensuel", r.code
        assert r.methode_collecte == "modele_satellitaire", r.code
        assert r.source == "nasa_power", r.code
        assert str(r.periode_debut) == "1991-01-01" and str(r.periode_fin) == "2020-12-31"
        assert r.localite == localites_attendues[r.code], r.code


def test_360_mesures_par_serie(db_session: Session) -> None:
    """Chaque série porte 360 mesures (12 mois sur 30 ans), mois 1-12, années 1991-2020."""
    for code in _CODES:
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
        assert len(rows) == 360, code
        assert {r.mois for r in rows} == set(range(1, 13)), code
        assert {r.annee for r in rows} == set(range(1991, 2021)), code


def test_invariants_mesures(db_session: Session) -> None:
    """Toutes les mesures : statut brut, confiance B, GHI dans les bornes physiques."""
    rows = db_session.execute(
        text(
            """
            SELECT m.statut, m.niveau_confiance_derive, m.valeur
            FROM mesures_ressource_mensuelles m
            JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": _CODES},
    ).all()
    assert len(rows) == 360 * len(_CODES)
    for r in rows:
        assert r.statut == "brut"
        assert r.niveau_confiance_derive == "B"
        assert 0.0 <= r.valeur <= 7.0


def test_unite_heritee_de_la_grandeur(db_session: Session) -> None:
    """La grandeur ``ghi`` de la série fixe l'unité kWh/m²/jour (kwh_par_m2_jour)."""
    symbole = db_session.execute(
        text(
            """
            SELECT u.code AS unite_code
            FROM series_metadonnees s
            JOIN grandeurs_referentiel g ON g.code = s.grandeur_code
            JOIN unites u ON u.id = g.unite_id
            WHERE s.code = :c
            """
        ),
        {"c": _CODES[0]},
    ).scalar_one()
    assert symbole == "kwh_par_m2_jour"


def test_valeurs_fideles_au_seed(db_session: Session) -> None:
    """Les valeurs gravées correspondent exactement au seed (échantillon de bornes)."""
    for s in SERIES:
        premier = s["mesures"][0]  # (1991, 1, valeur)
        dernier = s["mesures"][-1]  # (2020, 12, valeur)
        for annee, mois, attendu in (premier, dernier):
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
