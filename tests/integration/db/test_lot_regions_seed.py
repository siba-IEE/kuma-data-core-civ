"""Tests d'intégration du lot national « régions » (migration 0025, ADR-0015).

31 régions, 10 familles (source et grandeur), aux contrats des séries pilotes.
Vérifie, par famille : métadonnées de série, complétude, confiance B / statut
brut, et **fidélité intégrale** — chaque mesure en base égale le CSV gzip
committé, relu indépendamment par ``lire_series``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds.lots_civ import CONTRATS_MENSUELS, points_lot
from kuma_data_core.db.seeds.series_csv import ContratSerie, lire_series

pytestmark = pytest.mark.integration

LOT = "regions"
_REGIONS = {code for code, _, _, _ in points_lot(LOT)}


def _id(contrat: ContratSerie) -> str:
    return contrat.prefixe_code


def test_lot_couvre_les_31_regions() -> None:
    """Le lot est exactement l'ensemble des 31 régions du référentiel."""
    assert len(_REGIONS) == 31
    assert all(code.startswith("civ_") for code in _REGIONS)


@pytest.mark.parametrize("contrat", CONTRATS_MENSUELS, ids=_id)
def test_series_metadonnees(db_session: Session, contrat: ContratSerie) -> None:
    """31 séries par famille, avec source, grandeur, méthode et période du contrat."""
    rows = db_session.execute(
        text(
            """
            SELECT s.code, s.grandeur_code, s.methode_collecte, s.granularite,
                   s.periode_debut, s.periode_fin, src.code AS source, loc.code AS localite
            FROM series_metadonnees s
            JOIN sources src ON src.id = s.source_id
            JOIN localites loc ON loc.id = s.localite_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": [contrat.code_serie(code) for code in _REGIONS]},
    ).all()
    assert {r.localite for r in rows} == _REGIONS
    for r in rows:
        assert r.source == contrat.source_code and r.grandeur_code == contrat.grandeur_code
        assert r.methode_collecte == contrat.methode_collecte and r.granularite == "mensuel"
        assert str(r.periode_debut) == contrat.periode_debut
        assert str(r.periode_fin) == contrat.periode_fin


@pytest.mark.parametrize("contrat", CONTRATS_MENSUELS, ids=_id)
def test_mesures_fideles_au_csv(db_session: Session, contrat: ContratSerie) -> None:
    """Chaque mesure en base = CSV committé ; confiance B, statut brut, complétude."""
    attendu = {(s["code"], a, m): v for s in lire_series(contrat, LOT) for a, m, v in s["mesures"]}
    rows = db_session.execute(
        text(
            """
            SELECT s.code, m.annee, m.mois, m.valeur, m.statut, m.niveau_confiance_derive
            FROM mesures_ressource_mensuelles m
            JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": [contrat.code_serie(code) for code in _REGIONS]},
    ).all()
    assert len(rows) == len(attendu) == 31 * contrat.nb_mois
    for r in rows:
        assert r.valeur == attendu[(r.code, r.annee, r.mois)], (r.code, r.annee, r.mois)
        assert r.statut == "brut" and r.niveau_confiance_derive == "B"
