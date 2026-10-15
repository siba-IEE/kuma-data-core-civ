"""Tests d'intégration de la grandeur ``variabilite_journaliere`` (migration 0039).

Coefficient de variation annuel du GHI journalier NASA POWER (ADR-0024) aux
**34 localités** du journalier (3 pilotes + 31 régions, ADR-0016), 1991-2025,
matérialisé dans ``grandeurs_metier``. Vérifie le contrat (grandeur ``stockee``
sans dimension, séries ``calcul_derive`` de ``kuma_calculs``, annuel uniquement),
la complétude (35 ans par localité), le domaine et la **fidélité** : chaque
valeur gravée est recalculée indépendamment depuis les CSV journaliers committés
(base 1991-2020 et extension 2021-2025) — écart-type de population divisé par la
moyenne des jours de l'année — et coïncide avec la fonction pure du service
hérité (même définition, ``ddof=0``).
"""

from __future__ import annotations

import calendar
import statistics
from collections import defaultdict
from datetime import date
from functools import cache

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
from kuma_data_core.db.seeds.series_csv import lire_series_journalieres
from kuma_data_core.services.grandeurs.variabilite_journaliere import (
    _agreger_variabilite_journaliere,
)

pytestmark = pytest.mark.integration

GRANDEUR_CODE = "variabilite_journaliere"
_LOCALITES = {code for code, _, _, _ in points_journalier()}
ANNEES = range(1991, 2026)
NB_ANNUEL = len(ANNEES) * len(_LOCALITES)  # 35 ans x 34 localités = 1190
# Tolérance relative : la base calcule en numeric sur les valeurs décimales du CSV,
# le test en flottants ; l'écart reste de l'ordre de 1e-16. Un écart-type
# d'échantillon (N - 1) s'écarterait de 1,4e-3 : la tolérance discrimine.
REL = 1e-12


@cache
def _ghi_journalier() -> dict[str, list[tuple[date, float]]]:
    """``{localité: [(jour, GHI)]}`` 1991-2025 depuis les CSV (base + extension), lus une fois."""
    out: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for contrat, lot in (
        (CONTRATS_NASA_JOURNALIERS["ghi"], LOT_JOURNALIER),
        (CONTRATS_NASA_JOURNALIERS_EXTENSION["ghi"], LOT_EXTENSION),
    ):
        for s in lire_series_journalieres(contrat, lot):
            out[s["localite_code"]].extend(s["mesures"])
    return dict(out)


def _attendu() -> dict[tuple[str, int], float]:
    """Recalcul indépendant : écart-type de population / moyenne, années complètes."""
    attendu: dict[tuple[str, int], float] = {}
    for loc, mesures in _ghi_journalier().items():
        par_annee: dict[int, list[float]] = defaultdict(list)
        for jour, valeur in mesures:
            par_annee[jour.year].append(valeur)
        for annee, valeurs in par_annee.items():
            assert len(valeurs) == (366 if calendar.isleap(annee) else 365), (loc, annee)
            attendu[(loc, annee)] = statistics.pstdev(valeurs) / statistics.fmean(valeurs)
    return attendu


def _gravees(db_session: Session) -> dict[tuple[str, int], float]:
    rows = db_session.execute(
        text(
            """
            SELECT loc.code AS localite, gm.annee_debut AS annee, gm.valeur
            FROM grandeurs_metier gm JOIN localites loc ON loc.id = gm.localite_id
            WHERE gm.grandeur_code = :c
            """
        ),
        {"c": GRANDEUR_CODE},
    ).all()
    return {(r.localite, r.annee): r.valeur for r in rows}


def test_grandeur_referentiel(db_session: Session) -> None:
    """Grandeur seedée en 0002 : id 5, F1, stockee, sans dimension, version 1."""
    row = db_session.execute(
        text(
            """
            SELECT g.id, g.famille, g.strategie_calcul, g.version_formule_actuelle,
                   u.code AS unite
            FROM grandeurs_referentiel g JOIN unites u ON u.id = g.unite_id
            WHERE g.code = :c
            """
        ),
        {"c": GRANDEUR_CODE},
    ).one()
    assert (row.id, row.famille, row.strategie_calcul, row.version_formule_actuelle) == (
        5,
        "F1",
        "stockee",
        1,
    )
    assert row.unite == "sans_unite"


def test_series_calculees(db_session: Session) -> None:
    """34 séries calcul_derive, source kuma_calculs, période 1991-2025."""
    rows = db_session.execute(
        text(
            """
            SELECT s.code, loc.code AS localite, s.methode_collecte, s.granularite,
                   src.code AS source, s.periode_debut, s.periode_fin, s.libelle
            FROM series_metadonnees s
            JOIN sources src ON src.id = s.source_id
            JOIN localites loc ON loc.id = s.localite_id
            WHERE s.grandeur_code = :c
            """
        ),
        {"c": GRANDEUR_CODE},
    ).all()
    assert len(rows) == len(_LOCALITES) == 34
    for r in rows:
        assert r.localite in _LOCALITES
        assert r.code == f"variabilite_journaliere_nasa_power_{r.localite}"
        assert r.source == "kuma_calculs" and r.methode_collecte == "calcul_derive"
        assert r.granularite is None
        assert str(r.periode_debut) == "1991-01-01" and str(r.periode_fin) == "2025-12-31"
        assert r.libelle.endswith("(1991-2025)"), r.libelle


def test_completude_domaine_confiance(db_session: Session) -> None:
    """1190 lignes annuelles (35 ans par localité), aucune mensuelle, dans ]0, 1[."""
    rows = db_session.execute(
        text(
            """
            SELECT localite_id, periode_type, mois, valeur, niveau_confiance_derive, statut,
                   version_formule, annee_debut, annee_fin
            FROM grandeurs_metier WHERE grandeur_code = :c
            """
        ),
        {"c": GRANDEUR_CODE},
    ).all()
    assert len(rows) == NB_ANNUEL
    annees_par_localite: dict[int, set[int]] = defaultdict(set)
    for r in rows:
        assert r.periode_type == "annuel" and r.mois is None
        assert r.annee_debut == r.annee_fin
        assert 0.0 < r.valeur < 1.0
        assert r.niveau_confiance_derive == "B" and r.statut == "brut"
        assert r.version_formule == 1
        annees_par_localite[r.localite_id].add(r.annee_debut)
    assert len(annees_par_localite) == 34
    assert all(a == set(ANNEES) for a in annees_par_localite.values())


def test_valeurs_fideles_au_calcul(db_session: Session) -> None:
    """Chaque valeur gravée = recalcul indépendant depuis les CSV journaliers NASA."""
    attendu = _attendu()
    gravees = _gravees(db_session)
    assert len(attendu) == NB_ANNUEL
    assert set(gravees) == set(attendu)
    for cle, valeur in gravees.items():
        assert valeur == pytest.approx(attendu[cle], rel=REL), cle


def test_definition_heritee_du_service(db_session: Session) -> None:
    """La migration reproduit la fonction pure du service hérité (ddof=0, années complètes).

    Contre-épreuve : l'écart-type d'échantillon (N - 1) ne passerait pas la tolérance.
    """
    gravees = _gravees(db_session)
    for loc, mesures in _ghi_journalier().items():
        resultat = _agreger_variabilite_journaliere(mesures)
        assert resultat["annees_skip_completude"] == ()
        assert len(resultat["lignes_annuelles"]) == len(ANNEES)
        for ligne in resultat["lignes_annuelles"]:
            cle = (loc, ligne["annee_debut"])
            assert gravees[cle] == pytest.approx(ligne["valeur"], rel=REL), cle
    valeurs = [v for jour, v in _ghi_journalier()["civ_dep_abidjan"] if jour.year == 2005]
    echantillon = statistics.stdev(valeurs) / statistics.fmean(valeurs)
    assert gravees[("civ_dep_abidjan", 2005)] != pytest.approx(echantillon, rel=REL)
