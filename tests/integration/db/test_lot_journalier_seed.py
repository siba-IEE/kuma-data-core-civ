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
    CONTRATS_NASA_JOURNALIERS_EXTENSION,
    LOT_EXTENSION,
    LOT_JOURNALIER,
    points_journalier,
)
from kuma_data_core.db.seeds.series_csv import ContratSerie, lire_series_journalieres, nb_jours

pytestmark = pytest.mark.integration

_LOCALITES = {code for code, _, _, _ in points_journalier()}
_CONTRATS = list(CONTRATS_NASA_JOURNALIERS.values())


def _extension(contrat: ContratSerie) -> ContratSerie:
    """Contrat 2021-2025 de la même série (prolongée par la migration 0031, ADR-0018)."""
    return CONTRATS_NASA_JOURNALIERS_EXTENSION[contrat.grandeur_code]


def _nb_jours_total(contrat: ContratSerie) -> int:
    return nb_jours(contrat) + nb_jours(_extension(contrat))


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
        assert str(r.periode_fin) == _extension(contrat).periode_fin


@pytest.mark.parametrize("contrat", _CONTRATS, ids=_id)
def test_mesures_fideles_au_csv(db_session: Session, contrat: ContratSerie) -> None:
    """Chaque mesure journalière en base = CSV committés (base + extension 2021-2025)."""
    attendu = {
        (s["code"], jour): v
        for c, lot in ((contrat, LOT_JOURNALIER), (_extension(contrat), LOT_EXTENSION))
        for s in lire_series_journalieres(c, lot)
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
    assert len(rows) == len(attendu) == 34 * _nb_jours_total(contrat)
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
    assert len(rows) == 34 * (_extension(contrat).annee_fin - contrat.annee_debut + 1) * 12
    for r in rows:
        assert abs(r.moyenne - r.mensuel) < 5e-4


def test_dhi_jamais_superieur_au_ghi_journalier(db_session: Session) -> None:
    """Cohérence physique jour par jour : DHI <= GHI (NASA, 2001-2020).

    Un seul regroupement par (localité, jour) plutôt qu'une auto-jointure de
    ``mesures_ressource`` : le plan reste linéaire quelles que soient les
    statistiques du planificateur.
    """
    rows = db_session.execute(
        text(
            """
            SELECT COUNT(*) FILTER (WHERE dhi IS NOT NULL AND ghi IS NOT NULL) AS paires,
                   COUNT(*) FILTER (WHERE dhi > ghi) AS violations
            FROM (
                SELECT s.localite_id, m.instant_mesure,
                       MAX(m.valeur) FILTER (WHERE s.grandeur_code = 'dhi') AS dhi,
                       MAX(m.valeur) FILTER (WHERE s.grandeur_code = 'ghi') AS ghi
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:codes)
                GROUP BY s.localite_id, m.instant_mesure
            ) t
            """
        ),
        {
            "codes": [
                CONTRATS_NASA_JOURNALIERS[g].code_serie(c)
                for g in ("dhi", "ghi")
                for c in _LOCALITES
            ]
        },
    ).one()
    assert rows.paires == 34 * _nb_jours_total(CONTRATS_NASA_JOURNALIERS["dhi"])
    assert rows.violations == 0
