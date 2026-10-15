"""Tests d'intégration des mises en garde de la pluie (migration 0051, ADR-0032).

Vérifie que les phrases portent sur les seules séries visées (284 séries de
pluie NASA POWER, 142 séries mensuelles de pluie ERA5), que la citation ERA5
hors CDS de 0034 est remplacée par les valeurs du CDS en base, et **fige les
chiffres cités** en les recalculant en base : jours NASA au-delà de 200 mm,
pluie ERA5 la plus forte à un jour près, rapports de fréquence des jours
> 50 mm, écart des mois de raccord ERA5.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds.lots_civ import points_nationaux

pytestmark = pytest.mark.integration

_LOCS = [code for code, _, _, _ in points_nationaux()]
ORIGINE = "Origine établie (ADR-0032)"
RACCORDS = "Mise en garde (ADR-0032) : dans 13 mois de raccord"


def _portant(db_session: Session, fragment: str) -> set[str]:
    return {
        row.code
        for row in db_session.execute(
            text("SELECT code FROM series_metadonnees WHERE strpos(note_publique, :f) > 0"),
            {"f": fragment},
        )
    }


def test_phrases_sur_les_seules_series_visees(db_session: Session) -> None:
    nasa = {
        f"nasa_power_precipitation_{g}_{loc}" for g in ("mensuel", "journalier") for loc in _LOCS
    }
    era5 = {f"ecmwf_era5_precipitation_mensuel_{loc}" for loc in _LOCS}
    assert _portant(db_session, ORIGINE) == nasa and len(nasa) == 284
    assert _portant(db_session, RACCORDS) == era5 and len(era5) == 142
    mensuel = {f"nasa_power_precipitation_mensuel_{loc}" for loc in _LOCS}
    assert _portant(db_session, "dans ERA5 du CDS aux deux points de San-Pédro") == mensuel
    assert not _portant(db_session, "contre 4,89 mm/jour dans ERA5")


def test_valeurs_era5_citees_pour_san_pedro(db_session: Session) -> None:
    """« 3,73 à 5,64 mm/jour » : pluie ERA5 mensuelle de septembre 2022 (0036)."""
    valeurs = db_session.execute(
        text(
            """
            SELECT m.valeur FROM mesures_ressource_mensuelles m
            JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c) AND m.annee = 2022 AND m.mois = 9
            """
        ),
        {
            "c": [
                "ecmwf_era5_precipitation_mensuel_civ_san_pedro",
                "ecmwf_era5_precipitation_mensuel_civ_dep_san_pedro",
            ]
        },
    ).scalars()
    assert sorted(round(v, 2) for v in valeurs) == [3.73, 5.64]


def test_jours_nasa_extremes_non_confirmes_par_era5(db_session: Session) -> None:
    """25 jours-localités NASA > 200 mm ; ERA5 au plus 19 mm sur J ± 1."""
    row = db_session.execute(
        text(
            """
            WITH extremes AS (
                SELECT s.localite_id, m.instant_mesure AS jour
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code LIKE 'nasa_power_precipitation_journalier_%' AND m.valeur > 200
            )
            SELECT (SELECT COUNT(*) FROM extremes) AS nb,
                   MAX(me.valeur) AS era5_max
            FROM extremes x
            JOIN series_metadonnees se
                ON se.localite_id = x.localite_id
               AND se.code LIKE 'ecmwf_era5_precipitation_journalier_%'
            JOIN mesures_ressource me
                ON me.serie_id = se.id
               AND me.instant_mesure BETWEEN x.jour - 1 AND x.jour + 1
            """
        )
    ).one()
    assert row.nb == 25
    assert 19.0 < row.era5_max < 19.1


def test_rapports_de_frequence_des_fortes_pluies(db_session: Session) -> None:
    """Jours > 50 mm par an, 2017-2025 contre 1991-2015 : NASA multiplié par 12, ERA5 par 1,7."""
    rows = db_session.execute(
        text(
            """
            SELECT CASE WHEN s.code LIKE 'nasa_power%' THEN 'nasa' ELSE 'era5' END AS source,
                   COUNT(*) FILTER (WHERE EXTRACT(YEAR FROM m.instant_mesure) <= 2015)
                       / 25.0 AS avant,
                   COUNT(*) FILTER (WHERE EXTRACT(YEAR FROM m.instant_mesure) >= 2017)
                       / 9.0 AS apres
            FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE (s.code LIKE 'nasa_power_precipitation_journalier_%'
                   OR s.code LIKE 'ecmwf_era5_precipitation_journalier_%')
              AND m.valeur > 50
            GROUP BY 1
            """
        )
    ).all()
    rapports = {r.source: float(r.apres / r.avant) for r in rows}
    assert round(rapports["nasa"]) == 12
    assert round(rapports["era5"], 1) == 1.7


def test_ecart_des_mois_de_raccord_era5(db_session: Session) -> None:
    """Écart maximal mensuel CDS / moyenne des jours : 0,386 mm/jour (Tengréla, 1995-09)."""
    row = db_session.execute(
        text(
            """
            WITH jours AS (
                SELECT s.localite_id, EXTRACT(YEAR FROM m.instant_mesure)::int AS annee,
                       EXTRACT(MONTH FROM m.instant_mesure)::int AS mois, AVG(m.valeur) AS moy
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code LIKE 'ecmwf_era5_precipitation_journalier_%'
                GROUP BY 1, 2, 3
            )
            SELECT loc.code, j.annee, j.mois, ABS(j.moy - mm.valeur) AS ecart
            FROM jours j
            JOIN series_metadonnees sm
                ON sm.localite_id = j.localite_id
               AND sm.code LIKE 'ecmwf_era5_precipitation_mensuel_%'
            JOIN mesures_ressource_mensuelles mm
                ON mm.serie_id = sm.id AND mm.annee = j.annee AND mm.mois = j.mois
            JOIN localites loc ON loc.id = j.localite_id
            ORDER BY ecart DESC LIMIT 1
            """
        )
    ).one()
    assert (row.annee, row.mois) == (1995, 9)
    assert "tengrela" in row.code
    assert round(row.ecart, 3) == 0.386
