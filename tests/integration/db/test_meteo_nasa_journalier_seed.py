"""Tests d'intégration de la météo journalière NASA POWER (migration 0035, ADR-0020).

6 grandeurs aux 34 localités du lot ``pilotes_regions`` (3 pilotes + 31 régions),
dans ``mesures_ressource`` : ``t2m``, ``rh2m``, ``vent_2m``, ``vent_10m`` et
``precipitation`` (MERRA-2, 1991-2025), ``albedo_surface`` (CERES, 2001-2025).

Vérifie les métadonnées (source, méthode, granularité, période, unité du
référentiel, note publique), la complétude (tous les jours civils, sans trou),
la **fidélité intégrale** aux CSV gzip committés (relus ici sans passer par
``series_csv``), des bornes physiques indépendantes des contrats, la cohérence
physique (humidité au plus 100 %, pluie positive ou nulle, vent à 10 m supérieur
au vent à 2 m chaque jour), la cohérence avec le mensuel NASA quand il est gravé,
et la résolution de ces séries comme compagnes par l'API.
"""

from __future__ import annotations

import csv
import gzip
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds.lots_civ import CONTRATS_NASA_JOURNALIERS, points_journalier
from kuma_data_core.db.seeds.meteo_civ import (
    CONTRATS_METEO_NASA_JOURNALIERS,
    CONTRATS_METEO_NASA_MENSUELS,
    LOT_METEO_JOURNALIER,
)
from kuma_data_core.db.seeds.series_csv import DOSSIER_DONNEES

pytestmark = pytest.mark.integration

_LOCALITES = sorted(code for code, _, _, _ in points_journalier())

# Grandeur -> (première année, méthode, unité au référentiel, bornes physiques).
_ATTENDU: dict[str, tuple[int, str, str, float, float]] = {
    "t2m": (1991, "reanalyse", "degree_celsius", 10.0, 45.0),
    "rh2m": (1991, "reanalyse", "pourcent", 0.0, 100.0),
    "vent_2m": (1991, "reanalyse", "metre_par_seconde", 0.0, 20.0),
    "vent_10m": (1991, "reanalyse", "metre_par_seconde", 0.0, 25.0),
    "precipitation": (1991, "reanalyse", "mm_par_jour", 0.0, 1000.0),
    "albedo_surface": (2001, "modele_satellitaire", "sans_unite", 0.0, 1.0),
}
_GRANDEURS = list(_ATTENDU)


def _codes(grandeur: str) -> list[str]:
    return [f"nasa_power_{grandeur}_journalier_{code}" for code in _LOCALITES]


def _nb_jours(grandeur: str) -> int:
    return (date(2025, 12, 31) - date(_ATTENDU[grandeur][0], 1, 1)).days + 1


def _lire_csv(grandeur: str) -> dict[tuple[str, date], float]:
    """CSV gravé, relu directement : ``{(code série, jour): valeur}``."""
    chemin = DOSSIER_DONNEES / f"nasa_power_{grandeur}_journalier_{LOT_METEO_JOURNALIER}.csv.gz"
    with gzip.open(chemin, "rt", encoding="utf-8", newline="") as f:
        lecteur = csv.reader(f)
        assert next(lecteur) == ["localite_code", "latitude", "longitude", "date", "valeur"]
        lignes = {
            (f"nasa_power_{grandeur}_journalier_{loc}", date.fromisoformat(jour)): float(v)
            for loc, _, _, jour, v in lecteur
        }
    return lignes


def test_contrats_alignes() -> None:
    """Les contrats de ``meteo_civ`` couvrent les 6 grandeurs aux périodes attendues."""
    assert len(_LOCALITES) == 34
    assert set(CONTRATS_METEO_NASA_JOURNALIERS) == set(_ATTENDU)
    for g, c in CONTRATS_METEO_NASA_JOURNALIERS.items():
        assert (c.annee_debut, c.annee_fin, c.methode_collecte) == (
            _ATTENDU[g][0],
            2025,
            _ATTENDU[g][1],
        )
        assert c.granularite == "journalier" and c.source_code == "nasa_power"


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_series_journalieres(db_session: Session, grandeur: str) -> None:
    """34 séries par grandeur : source, méthode, période, unité, libellé et note."""
    debut, methode, unite, _, _ = _ATTENDU[grandeur]
    rows = db_session.execute(
        text(
            """
            SELECT loc.code AS localite, loc.nom, s.granularite, s.methode_collecte,
                   s.periode_debut, s.periode_fin, s.actif, s.libelle, s.note_publique,
                   src.code AS source, u.code AS unite
            FROM series_metadonnees s
            JOIN sources src ON src.id = s.source_id
            JOIN localites loc ON loc.id = s.localite_id
            JOIN grandeurs_referentiel g ON g.code = s.grandeur_code
            JOIN unites u ON u.id = g.unite_id
            WHERE s.code = ANY(:c) AND s.grandeur_code = :g
            """
        ),
        {"c": _codes(grandeur), "g": grandeur},
    ).all()
    assert sorted(r.localite for r in rows) == _LOCALITES
    for r in rows:
        assert r.source == "nasa_power" and r.granularite == "journalier" and r.actif
        assert r.methode_collecte == methode and r.unite == unite
        assert (r.periode_debut, r.periode_fin) == (date(debut, 1, 1), date(2025, 12, 31))
        assert r.libelle.endswith(f"journalier NASA POWER — {r.nom} ({debut}-2025)")
        assert "(ADR-0020)" in r.note_publique and "Confiance B" in r.note_publique
        assert ("Mise en garde" in r.note_publique) == (grandeur == "precipitation")
        if grandeur == "precipitation":
            assert "aberrantes probables" in r.note_publique and "ERA5" in r.note_publique


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_completude_journaliere(db_session: Session, grandeur: str) -> None:
    """Chaque série a tous les jours civils de sa période, une seule fois, sans trou."""
    rows = db_session.execute(
        text(
            """
            SELECT s.code, COUNT(*) AS n, COUNT(DISTINCT m.instant_mesure) AS distincts,
                   MIN(m.instant_mesure) AS premier, MAX(m.instant_mesure) AS dernier
            FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c) AND m.valide_au IS NULL
            GROUP BY s.code
            """
        ),
        {"c": _codes(grandeur)},
    ).all()
    assert len(rows) == 34
    debut = date(_ATTENDU[grandeur][0], 1, 1)
    for r in rows:
        assert r.n == r.distincts == _nb_jours(grandeur), r.code
        assert (r.premier, r.dernier) == (debut, date(2025, 12, 31)), r.code


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_mesures_fideles_au_csv(db_session: Session, grandeur: str) -> None:
    """Chaque mesure en base = valeur du CSV committé, et réciproquement."""
    attendu = _lire_csv(grandeur)
    assert len(attendu) == 34 * _nb_jours(grandeur)
    base = {
        (r.code, r.instant_mesure): r.valeur
        for r in db_session.execute(
            text(
                """
                SELECT s.code, m.instant_mesure, m.valeur
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:c)
                """
            ),
            {"c": _codes(grandeur)},
        )
    }
    ecarts = [k for k in attendu.keys() | base.keys() if attendu.get(k) != base.get(k)]
    assert not ecarts, sorted(ecarts)[:10]
    statuts = db_session.execute(
        text(
            """
            SELECT COUNT(*) FILTER (WHERE m.statut <> 'brut' OR m.niveau_confiance_derive <> 'B'
                                    OR m.valide_au IS NOT NULL) AS hors_contrat
            FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": _codes(grandeur)},
    ).scalar_one()
    assert statuts == 0


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_bornes_physiques(db_session: Session, grandeur: str) -> None:
    """Valeurs dans des bornes physiques (humidité au plus 100 %, pluie positive ou nulle)."""
    _, _, _, borne_min, borne_max = _ATTENDU[grandeur]
    r = db_session.execute(
        text(
            """
            SELECT MIN(m.valeur) AS mini, MAX(m.valeur) AS maxi
            FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": _codes(grandeur)},
    ).one()
    assert borne_min <= r.mini <= r.maxi <= borne_max, (r.mini, r.maxi)


def test_pluies_extremes_citees_par_la_mise_en_garde(db_session: Session) -> None:
    """Les jours au-delà de 200 mm sont exactement ceux que cite la note publique.

    Valeurs aberrantes probables servies par NASA POWER, gravées sans correction
    (ADR-0020) : toutes dans l'ouest, en septembre 2022.
    """
    rows = db_session.execute(
        text(
            """
            SELECT l.code, m.instant_mesure, m.valeur
            FROM mesures_ressource m
            JOIN series_metadonnees s ON s.id = m.serie_id
            JOIN localites l ON l.id = s.localite_id
            WHERE s.code = ANY(:c) AND m.valeur > 200
            """
        ),
        {"c": _codes("precipitation")},
    ).all()
    assert {(r.code, r.instant_mesure, r.valeur) for r in rows} == {
        ("civ_san_pedro", date(2022, 9, 16), 726.74),
        ("civ_gbokle", date(2022, 9, 16), 710.75),
        ("civ_guemon", date(2022, 9, 23), 329.59),
        ("civ_cavally", date(2022, 9, 23), 329.59),
        ("civ_nawa", date(2022, 9, 23), 248.92),
    }


def test_vent_10m_superieur_au_vent_2m(db_session: Session) -> None:
    """Profil de vent : vent à 10 m strictement supérieur au vent à 2 m, chaque jour.

    Un seul regroupement par (localité, jour), sans auto-jointure de
    ``mesures_ressource``.
    """
    r = db_session.execute(
        text(
            """
            SELECT COUNT(*) FILTER (WHERE v2 IS NOT NULL AND v10 IS NOT NULL) AS paires,
                   COUNT(*) FILTER (WHERE v10 <= v2) AS violations
            FROM (
                SELECT s.localite_id, m.instant_mesure,
                       MAX(m.valeur) FILTER (WHERE s.grandeur_code = 'vent_2m') AS v2,
                       MAX(m.valeur) FILTER (WHERE s.grandeur_code = 'vent_10m') AS v10
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:c)
                GROUP BY s.localite_id, m.instant_mesure
            ) t
            """
        ),
        {"c": _codes("vent_2m") + _codes("vent_10m")},
    ).one()
    assert r.paires == 34 * _nb_jours("vent_2m")
    assert r.violations == 0


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_coherence_avec_le_mensuel(db_session: Session, grandeur: str) -> None:
    """Moyenne des jours du mois = série mensuelle NASA (servie à 2 décimales).

    Saute si les séries mensuelles météo ne sont pas gravées dans la base.
    """
    contrat_mois = CONTRATS_METEO_NASA_MENSUELS[grandeur]
    codes_mois = [contrat_mois.code_serie(code) for code in _LOCALITES]
    nb_mois = db_session.execute(
        text(
            """
            SELECT COUNT(DISTINCT s.id) AS series, COUNT(mm.serie_id) AS mesures
            FROM series_metadonnees s
            LEFT JOIN mesures_ressource_mensuelles mm ON mm.serie_id = s.id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": codes_mois},
    ).one()
    if nb_mois.series == 0:
        pytest.skip(f"séries mensuelles {contrat_mois.prefixe_code}_* absentes de la base")
    assert nb_mois.series == 34
    rows = db_session.execute(
        text(
            """
            WITH jour AS (
                SELECT s.localite_id, EXTRACT(YEAR FROM m.instant_mesure)::int AS annee,
                       EXTRACT(MONTH FROM m.instant_mesure)::int AS mois,
                       AVG(m.valeur) AS moyenne
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:jour)
                GROUP BY 1, 2, 3
            )
            SELECT sm.code, mm.annee, mm.mois, mm.valeur AS mensuel, j.moyenne
            FROM series_metadonnees sm
            JOIN mesures_ressource_mensuelles mm ON mm.serie_id = sm.id
            LEFT JOIN jour j
                ON j.localite_id = sm.localite_id AND j.annee = mm.annee AND j.mois = mm.mois
            WHERE sm.code = ANY(:mois)
            """
        ),
        {"jour": _codes(grandeur), "mois": codes_mois},
    ).all()
    assert len(rows) == nb_mois.mesures > 0
    hors = [
        (r.code, r.annee, r.mois, r.mensuel, r.moyenne)
        for r in rows
        if r.moyenne is None or abs(r.moyenne - r.mensuel) > 0.005 + 1e-9
    ]
    assert not hors, hors[:10]


def test_series_resolues_comme_compagnes_par_l_api(db_session: Session) -> None:
    """Les résolveurs de l'API trouvent ces séries depuis le GHI journalier NASA.

    ``_chercher_serie_compagne`` (même localité, source, ``periode_debut`` et
    granularité que le GHI 1991-2025) pour T2M, humidité, vent et pluie ;
    ``_resoudre_serie_albedo_journalier`` pour l'albédo ; ``_chercher_serie_pluie_nasa``
    (salissure) sur la fenêtre des PM EAC4.
    """
    from kuma_data_core.api.v1.grandeurs import (
        _chercher_serie_compagne,
        _chercher_serie_pluie_nasa,
        _resoudre_serie_albedo_journalier,
        _resoudre_serie_source,
    )

    ghi = db_session.execute(
        text(
            """
            SELECT s.localite_id, s.source_id, s.periode_debut, s.granularite, l.code
            FROM series_metadonnees s JOIN localites l ON l.id = s.localite_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": [CONTRATS_NASA_JOURNALIERS["ghi"].code_serie(c) for c in _LOCALITES]},
    ).all()
    assert len(ghi) == 34
    ids = {
        (r.code, r.grandeur_code): r.id
        for r in db_session.execute(
            text(
                "SELECT s.id, s.code, s.grandeur_code FROM series_metadonnees s "
                "WHERE s.code = ANY(:c)"
            ),
            {"c": [c for g in _GRANDEURS for c in _codes(g)]},
        )
    }
    for r in ghi:
        serie = _resoudre_serie_source(
            db_session, CONTRATS_NASA_JOURNALIERS["ghi"].code_serie(r.code)
        )
        for g in ("t2m", "rh2m", "vent_2m", "vent_10m", "precipitation"):
            trouve = _chercher_serie_compagne(db_session, serie, g)
            assert trouve == ids[(f"nasa_power_{g}_journalier_{r.code}", g)], (r.code, g)
        assert (
            _resoudre_serie_albedo_journalier(db_session, r.localite_id, r.source_id)
            == ids[(f"nasa_power_albedo_surface_journalier_{r.code}", "albedo_surface")]
        )
        assert (
            _chercher_serie_pluie_nasa(
                db_session, r.localite_id, date(2021, 1, 1), date(2025, 8, 31)
            )
            == ids[(f"nasa_power_precipitation_journalier_{r.code}", "precipitation")]
        )
