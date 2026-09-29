"""Tests d'intégration du lot journalier NASA POWER (migration 0026, ADR-0016).

34 localités (3 pilotes + 31 régions), GHI 1991-2020, DNI et DHI 2001-2020, dans
``mesures_ressource``. Vérifie les métadonnées, la complétude, la **fidélité
intégrale** au CSV gzip committé, la **cohérence avec le mensuel** déjà gravé
(moyenne des jours du mois = valeur mensuelle NASA, à l'arrondi près) et la
cohérence physique DHI <= GHI jour par jour.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds.lots_civ import (
    CONTRATS_NASA_JOURNALIERS,
    LOT_JOURNALIER,
    points_journalier,
)
from kuma_data_core.db.seeds.series_csv import ContratSerie, lire_series_journalieres, nb_jours

pytestmark = pytest.mark.integration

_LOCALITES = {code for code, _, _, _ in points_journalier()}
_CONTRATS = list(CONTRATS_NASA_JOURNALIERS.values())


def _id(contrat: ContratSerie) -> str:
    return contrat.grandeur_code


@pytest.mark.parametrize("contrat", _CONTRATS, ids=_id)
def test_series_journalieres(db_session: Session, contrat: ContratSerie) -> None:
    """34 séries journalières NASA par grandeur, période du contrat."""
    rows = db_session.execute(
        text(
            """
            SELECT loc.code AS localite, s.granularite, s.methode_collecte,
                   s.periode_debut, s.periode_fin, src.code AS source
            FROM series_metadonnees s
            JOIN sources src ON src.id = s.source_id
            JOIN localites loc ON loc.id = s.localite_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": [contrat.code_serie(code) for code in _LOCALITES]},
    ).all()
    assert {r.localite for r in rows} == _LOCALITES and len(_LOCALITES) == 34
    for r in rows:
        assert r.source == "nasa_power" and r.granularite == "journalier"
        assert r.methode_collecte == "modele_satellitaire"
        assert str(r.periode_debut) == contrat.periode_debut
        assert str(r.periode_fin) == contrat.periode_fin


@pytest.mark.parametrize("contrat", _CONTRATS, ids=_id)
def test_mesures_fideles_au_csv(db_session: Session, contrat: ContratSerie) -> None:
    """Chaque mesure journalière en base = CSV committé ; confiance B, statut brut."""
    attendu = {
        (s["code"], jour): v
        for s in lire_series_journalieres(contrat, LOT_JOURNALIER)
        for jour, v in s["mesures"]
    }
    rows = db_session.execute(
        text(
            """
            SELECT s.code, m.instant_mesure, m.valeur, m.statut, m.niveau_confiance_derive
            FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": [contrat.code_serie(code) for code in _LOCALITES]},
    ).all()
    assert len(rows) == len(attendu) == 34 * nb_jours(contrat)
    for r in rows:
        assert r.valeur == attendu[(r.code, r.instant_mesure)], (r.code, r.instant_mesure)
        assert r.statut == "brut" and r.niveau_confiance_derive == "B"


@pytest.mark.parametrize("contrat", _CONTRATS, ids=_id)
def test_coherence_avec_le_mensuel(db_session: Session, contrat: ContratSerie) -> None:
    """Moyenne des jours de chaque mois = série mensuelle NASA gravée (à 5·10⁻⁴ près)."""
    rows = db_session.execute(
        text(
            """
            WITH jour AS (
                SELECT s.localite_id, EXTRACT(YEAR FROM m.instant_mesure)::int AS annee,
                       EXTRACT(MONTH FROM m.instant_mesure)::int AS mois,
                       AVG(m.valeur) AS moyenne, COUNT(*) AS n
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:c)
                GROUP BY 1, 2, 3
            )
            SELECT j.moyenne, mm.valeur AS mensuel
            FROM jour j
            JOIN series_metadonnees sm
                ON sm.localite_id = j.localite_id AND sm.grandeur_code = :g
               AND sm.granularite = 'mensuel'
            JOIN sources src ON src.id = sm.source_id AND src.code = 'nasa_power'
            JOIN mesures_ressource_mensuelles mm
                ON mm.serie_id = sm.id AND mm.annee = j.annee AND mm.mois = j.mois
            """
        ),
        {
            "c": [contrat.code_serie(code) for code in _LOCALITES],
            "g": contrat.grandeur_code,
        },
    ).all()
    assert len(rows) == 34 * (contrat.annee_fin - contrat.annee_debut + 1) * 12
    for r in rows:
        assert abs(r.moyenne - r.mensuel) < 5e-4


def test_dhi_jamais_superieur_au_ghi_journalier(db_session: Session) -> None:
    """Cohérence physique jour par jour : DHI <= GHI (NASA, 2001-2020)."""
    nb = db_session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM mesures_ressource md
            JOIN series_metadonnees sd ON sd.id = md.serie_id AND sd.code = ANY(:dhi)
            JOIN series_metadonnees sg
                ON sg.localite_id = sd.localite_id AND sg.code = ANY(:ghi)
            JOIN mesures_ressource mg
                ON mg.serie_id = sg.id AND mg.instant_mesure = md.instant_mesure
            WHERE md.valeur > mg.valeur
            """
        ),
        {
            "dhi": [CONTRATS_NASA_JOURNALIERS["dhi"].code_serie(c) for c in _LOCALITES],
            "ghi": [CONTRATS_NASA_JOURNALIERS["ghi"].code_serie(c) for c in _LOCALITES],
        },
    ).scalar_one()
    assert nb == 0
