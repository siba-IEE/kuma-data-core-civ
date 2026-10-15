"""Tests d'intégration des grandeurs dérivées du journalier aux 108 départements.

Migration 0049 (ADR-0031) : ``variabilite_journaliere`` (ADR-0024) et
``humidex`` (ADR-0030) aux **108 départements hors pilotes**, depuis le GHI et la
météo journaliers NASA POWER du lot départements (0046, 0047). Vérifie le
contrat des séries, la complétude, le domaine et la **fidélité** : chaque valeur
est recalculée indépendamment depuis les CSV journaliers committés, par les
fonctions pures des services hérités. Vérifie enfin que les 34 séries du lot
pilotes + régions ne sont pas touchées.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from functools import cache

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds.journalier_departements_civ import (
    CONTRATS_METEO_DEPARTEMENTS,
    CONTRATS_RAYONNEMENT_DEPARTEMENTS,
    LOT_JOURNALIER_DEPARTEMENTS,
    points_journalier_departements,
)
from kuma_data_core.db.seeds.lots_civ import points_journalier
from kuma_data_core.db.seeds.series_csv import lire_series_journalieres
from kuma_data_core.services.grandeurs.humidex import _agreger_humidex
from kuma_data_core.services.grandeurs.variabilite_journaliere import (
    _calculer_coefficient_variation,
)

pytestmark = pytest.mark.integration

_POINTS = {code: nom for code, nom, _, _ in points_journalier_departements()}
_LOCS = sorted(_POINTS)
ANNEES = range(1991, 2026)
REL = 1e-12  # la base calcule en numeric, le test en flottants

_Cle = tuple[str, str, int, int | None]  # (localité, periode_type, année, mois)


@cache
def _journalier(grandeur: str) -> dict[str, list[tuple[date, float]]]:
    contrats = {**CONTRATS_RAYONNEMENT_DEPARTEMENTS, **CONTRATS_METEO_DEPARTEMENTS}
    return {
        s["localite_code"]: s["mesures"]
        for s in lire_series_journalieres(contrats[grandeur], LOT_JOURNALIER_DEPARTEMENTS)
    }


def _gravees(db_session: Session, grandeur: str, prefixe: str) -> dict[_Cle, float]:
    rows = db_session.execute(
        text(
            """
            SELECT loc.code AS localite, gm.periode_type, gm.annee_debut AS annee, gm.mois,
                   gm.valeur
            FROM grandeurs_metier gm
            JOIN series_metadonnees s ON s.id = gm.series_metadonnees_id
            JOIN localites loc ON loc.id = gm.localite_id
            WHERE gm.grandeur_code = :g AND s.code = ANY(:c)
            """
        ),
        {"g": grandeur, "c": [f"{prefixe}_{loc}" for loc in _LOCS]},
    ).all()
    return {(r.localite, r.periode_type, r.annee, r.mois): r.valeur for r in rows}


@pytest.mark.parametrize(
    ("grandeur", "prefixe", "libelle", "adr"),
    [
        (
            "variabilite_journaliere",
            "variabilite_journaliere_nasa_power",
            "Variabilité journalière du GHI NASA POWER",
            "ADR-0024",
        ),
        ("humidex", "humidex_nasa_power", "Humidex moyen NASA POWER", "ADR-0030"),
    ],
)
def test_series(db_session: Session, grandeur: str, prefixe: str, libelle: str, adr: str) -> None:
    """108 séries calcul_derive de kuma_calculs, 1991-2025, note du lot départements."""
    rows = db_session.execute(
        text(
            """
            SELECT s.code, loc.code AS localite, s.methode_collecte, s.granularite,
                   src.code AS source, s.periode_debut, s.periode_fin, s.libelle,
                   s.note_publique
            FROM series_metadonnees s
            JOIN sources src ON src.id = s.source_id
            JOIN localites loc ON loc.id = s.localite_id
            WHERE s.grandeur_code = :g AND loc.code = ANY(:locs)
            """
        ),
        {"g": grandeur, "locs": _LOCS},
    ).all()
    assert sorted(r.localite for r in rows) == _LOCS and len(rows) == 108
    for r in rows:
        assert r.code == f"{prefixe}_{r.localite}"
        assert r.source == "kuma_calculs" and r.methode_collecte == "calcul_derive"
        assert r.granularite is None
        assert str(r.periode_debut) == "1991-01-01" and str(r.periode_fin) == "2025-12-31"
        assert r.libelle == f"{libelle} — {_POINTS[r.localite]} (1991-2025)"
        assert "Lot départements (ADR-0031)" in r.note_publique and adr in r.note_publique


def test_variabilite_gravee(db_session: Session) -> None:
    """3 780 lignes annuelles = CoV recalculé depuis le CSV (fonction du service)."""
    gravees = _gravees(db_session, "variabilite_journaliere", "variabilite_journaliere_nasa_power")
    assert len(gravees) == 108 * len(ANNEES)
    ghi = _journalier("ghi")
    for loc in _LOCS:
        par_annee: dict[int, list[float]] = defaultdict(list)
        for jour, v in ghi[loc]:
            par_annee[jour.year].append(v)
        for annee, valeurs in par_annee.items():
            obtenu = gravees[(loc, "annuel", annee, None)]
            attendu = _calculer_coefficient_variation(valeurs)
            assert obtenu == pytest.approx(attendu, rel=REL), (loc, annee)
            assert 0.0 < obtenu < 1.0


def test_humidex_grave(db_session: Session) -> None:
    """45 360 lignes mensuelles et 3 780 annuelles = recalcul depuis T2M et RH2M."""
    gravees = _gravees(db_session, "humidex", "humidex_nasa_power")
    assert sum(k[1] == "mensuel" for k in gravees) == 108 * 420
    assert sum(k[1] == "annuel" for k in gravees) == 108 * len(ANNEES)
    t2m, rh2m = _journalier("t2m"), _journalier("rh2m")
    for loc in _LOCS:
        resultat = _agreger_humidex(t2m[loc], rh2m[loc])
        assert resultat["annees_skip_completude"] == ()
        assert resultat["mois_skip_completude"] == ()
        for ligne in resultat["lignes_mensuelles"] + resultat["lignes_annuelles"]:
            cle = (loc, ligne["periode_type"], ligne["annee_debut"], ligne["mois"])
            assert gravees[cle] == pytest.approx(ligne["valeur"], rel=REL), cle
            assert 10.0 < gravees[cle] < 50.0


def test_lot_pilotes_regions_intact(db_session: Session) -> None:
    """Les séries des 34 localités du lot pilotes + régions gardent leurs volumes."""
    locs_34 = sorted(code for code, _, _, _ in points_journalier())
    row = db_session.execute(
        text(
            """
            SELECT COUNT(*) FILTER (WHERE gm.grandeur_code = 'variabilite_journaliere') AS v,
                   COUNT(*) FILTER (WHERE gm.grandeur_code = 'humidex') AS h
            FROM grandeurs_metier gm JOIN localites loc ON loc.id = gm.localite_id
            WHERE loc.code = ANY(:locs)
              AND gm.grandeur_code IN ('variabilite_journaliere', 'humidex')
            """
        ),
        {"locs": locs_34},
    ).one()
    assert (row.v, row.h) == (34 * 35, 34 * (420 + 35))
