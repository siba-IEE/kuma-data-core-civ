"""Tests d'intégration des lots nationaux (migrations 0025-0026, ADR-0015).

Lots « régions » (31 localités) et « départements » (108, hors les 3 pilotes),
10 familles (source et grandeur) chacun, aux contrats des séries pilotes.
Vérifie, par lot et par famille : métadonnées de série, complétude, confiance
B / statut brut, et **fidélité intégrale** — chaque mesure en base égale le CSV
gzip committé, relu indépendamment par ``lire_series``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds.lots_civ import CONTRATS_MENSUELS, POINTS_PILOTES, points_lot
from kuma_data_core.db.seeds.series_csv import ContratSerie, lire_series

pytestmark = pytest.mark.integration

LOTS: dict[str, int] = {"regions": 31, "departements": 108}
_CAS = [(lot, contrat) for lot in LOTS for contrat in CONTRATS_MENSUELS]


def _id(cas: tuple[str, ContratSerie]) -> str:
    return f"{cas[0]}:{cas[1].prefixe_code}"


def _localites(lot: str) -> set[str]:
    return {code for code, _, _, _ in points_lot(lot)}


@pytest.mark.parametrize(("lot", "taille"), LOTS.items())
def test_perimetre_des_lots(lot: str, taille: int) -> None:
    """Taille attendue de chaque lot ; les pilotes n'y figurent jamais."""
    assert len(_localites(lot)) == taille
    assert not (_localites(lot) & POINTS_PILOTES)


def test_lots_disjoints_et_couverture_nationale() -> None:
    """Régions et départements sont disjoints ; départements + pilotes = 111."""
    assert not (_localites("regions") & _localites("departements"))
    assert len(_localites("departements") | POINTS_PILOTES) == 111


@pytest.mark.parametrize("cas", _CAS, ids=_id)
def test_series_metadonnees(db_session: Session, cas: tuple[str, ContratSerie]) -> None:
    """Une série par localité du lot, avec source, grandeur, méthode et période du contrat."""
    lot, contrat = cas
    localites = _localites(lot)
    rows = db_session.execute(
        text(
            """
            SELECT s.grandeur_code, s.methode_collecte, s.granularite,
                   s.periode_debut, s.periode_fin, src.code AS source, loc.code AS localite
            FROM series_metadonnees s
            JOIN sources src ON src.id = s.source_id
            JOIN localites loc ON loc.id = s.localite_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": [contrat.code_serie(code) for code in localites]},
    ).all()
    assert {r.localite for r in rows} == localites
    for r in rows:
        assert r.source == contrat.source_code and r.grandeur_code == contrat.grandeur_code
        assert r.methode_collecte == contrat.methode_collecte and r.granularite == "mensuel"
        assert str(r.periode_debut) == contrat.periode_debut
        assert str(r.periode_fin) == contrat.periode_fin


@pytest.mark.parametrize("cas", _CAS, ids=_id)
def test_mesures_fideles_au_csv(db_session: Session, cas: tuple[str, ContratSerie]) -> None:
    """Chaque mesure en base = CSV committé ; confiance B, statut brut, complétude."""
    lot, contrat = cas
    localites = _localites(lot)
    attendu = {(s["code"], a, m): v for s in lire_series(contrat, lot) for a, m, v in s["mesures"]}
    rows = db_session.execute(
        text(
            """
            SELECT s.code, m.annee, m.mois, m.valeur, m.statut, m.niveau_confiance_derive
            FROM mesures_ressource_mensuelles m
            JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": [contrat.code_serie(code) for code in localites]},
    ).all()
    assert len(rows) == len(attendu) == LOTS[lot] * contrat.nb_mois
    for r in rows:
        assert r.valeur == attendu[(r.code, r.annee, r.mois)], (r.code, r.annee, r.mois)
        assert r.statut == "brut" and r.niveau_confiance_derive == "B"
