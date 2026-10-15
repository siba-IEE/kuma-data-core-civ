"""Tests d'intégration de la météo mensuelle NASA POWER (migration 0034, ADR-0019).

Six grandeurs du référentiel — température (``t2m``), humidité relative
(``rh2m``), vent à 2 et 10 m, précipitations, albédo de surface — aux 142
localités (3 pilotes + 31 régions + 108 départements), dans
``mesures_ressource_mensuelles``. Vérifie : unités du référentiel, métadonnées de
série, complétude, **fidélité intégrale** aux CSV gzip committés (relus ici
directement, sans ``lire_series``), bornes du contrat et cohérences physiques :

- humidité relative <= 100 % : imposée (physique) ;
- vent à 10 m >= vent à 2 m et albédo dans [0,1 ; 0,4] : **signalés** par un
  avertissement, pas imposés (ni l'un ni l'autre n'est universel).

Les regroupements se font par ``GROUP BY`` + ``FILTER`` plutôt que par
auto-jointure de ``mesures_ressource_mensuelles``.
"""

from __future__ import annotations

import csv
import gzip
import warnings

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.meteo_civ import (
    BORNE_PRECIPITATION_MENSUELLE,
    CONTRATS_METEO_NASA_MENSUELS,
    LOT_METEO_MENSUEL,
    PARAMETRES_METEO_NASA,
    UNITES_REFERENTIEL,
)
from kuma_data_core.db.seeds.series_csv import DOSSIER_DONNEES, ContratSerie

pytestmark = pytest.mark.integration

_LOCALITES: dict[str, str] = {code: nom for code, nom, _, _ in points_nationaux()}
_CONTRATS: list[ContratSerie] = list(CONTRATS_METEO_NASA_MENSUELS.values())
_SYMBOLES: dict[str, str] = {
    "t2m": "°C",
    "rh2m": "%",
    "vent_2m": "m/s",
    "vent_10m": "m/s",
    "precipitation": "mm/jour",
    "albedo_surface": "1",
}


def _id(contrat: ContratSerie) -> str:
    return contrat.grandeur_code


def _codes(contrat: ContratSerie) -> list[str]:
    return [contrat.code_serie(code) for code in _LOCALITES]


def _csv_brut(contrat: ContratSerie) -> dict[tuple[str, int, int], float]:
    """Lecture directe du CSV gzip committé : ``{(localité, année, mois): valeur}``."""
    chemin = DOSSIER_DONNEES / contrat.nom_fichier(LOT_METEO_MENSUEL)
    with gzip.open(chemin, "rt", encoding="utf-8", newline="") as f:
        lignes = list(csv.DictReader(f))
    valeurs = {
        (r["localite_code"], int(r["annee"]), int(r["mois"])): float(r["valeur"]) for r in lignes
    }
    assert len(valeurs) == len(lignes)  # aucun doublon
    return valeurs


def test_perimetre_et_contrats() -> None:
    """142 localités, 6 grandeurs ; borne des précipitations couvrant septembre 2022."""
    assert len(_LOCALITES) == 142
    assert set(CONTRATS_METEO_NASA_MENSUELS) == set(_SYMBOLES)
    assert CONTRATS_METEO_NASA_MENSUELS["precipitation"].borne_max == BORNE_PRECIPITATION_MENSUELLE
    total = sum(len(_LOCALITES) * c.nb_mois for c in _CONTRATS)
    assert total == 5 * 142 * 420 + 142 * 300
    assert len({code for c in _CONTRATS for code in _codes(c)}) == 852


def test_unites_du_referentiel(db_session: Session) -> None:
    """Unité de chaque grandeur au référentiel = unité servie par NASA (sans conversion)."""
    rows = db_session.execute(
        text(
            "SELECT g.code, u.code AS unite, u.symbole FROM grandeurs_referentiel g "
            "JOIN unites u ON u.id = g.unite_id WHERE g.code = ANY(:g)"
        ),
        {"g": list(CONTRATS_METEO_NASA_MENSUELS)},
    ).all()
    assert {r.code: r.unite for r in rows} == UNITES_REFERENTIEL
    assert {r.code: r.symbole for r in rows} == _SYMBOLES


@pytest.mark.parametrize("contrat", _CONTRATS, ids=_id)
def test_series_metadonnees(db_session: Session, contrat: ContratSerie) -> None:
    """142 séries par grandeur : source, méthode, granularité, période, libellé et note."""
    rows = db_session.execute(
        text(
            """
            SELECT s.code, s.libelle, s.grandeur_code, s.methode_collecte, s.granularite,
                   s.periode_debut, s.periode_fin, s.note_publique, s.actif,
                   src.code AS source, loc.code AS localite, loc.nom
            FROM series_metadonnees s
            JOIN sources src ON src.id = s.source_id
            JOIN localites loc ON loc.id = s.localite_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": _codes(contrat)},
    ).all()
    assert {r.localite for r in rows} == set(_LOCALITES) and len(rows) == 142
    parametre = PARAMETRES_METEO_NASA[contrat.grandeur_code][0]
    for r in rows:
        assert r.code == contrat.code_serie(r.localite)
        assert r.source == "nasa_power" and r.grandeur_code == contrat.grandeur_code
        assert r.methode_collecte == contrat.methode_collecte and r.granularite == "mensuel"
        assert str(r.periode_debut) == contrat.periode_debut
        assert str(r.periode_fin) == contrat.periode_fin == "2025-12-31"
        assert r.libelle == (
            f"{contrat.libelle_grandeur} mensuel NASA POWER — {r.nom} "
            f"({contrat.annee_debut}-{contrat.annee_fin})"
        )
        assert f"paramètre {parametre}" in r.note_publique
        assert "(ADR-0019)" in r.note_publique and "Confiance B." in r.note_publique
        assert r.actif


def test_methodes_par_origine(db_session: Session) -> None:
    """MERRA-2 : réanalyse ; albédo CERES : modèle satellitaire."""
    rows = db_session.execute(
        text(
            "SELECT grandeur_code, methode_collecte, COUNT(*) AS n FROM series_metadonnees "
            "WHERE code = ANY(:c) GROUP BY 1, 2"
        ),
        {"c": [code for c in _CONTRATS for code in _codes(c)]},
    ).all()
    assert {(r.grandeur_code, r.methode_collecte, r.n) for r in rows} == {
        ("t2m", "reanalyse", 142),
        ("rh2m", "reanalyse", 142),
        ("vent_2m", "reanalyse", 142),
        ("vent_10m", "reanalyse", 142),
        ("precipitation", "reanalyse", 142),
        ("albedo_surface", "modele_satellitaire", 142),
    }


@pytest.mark.parametrize("contrat", _CONTRATS, ids=_id)
def test_completude(db_session: Session, contrat: ContratSerie) -> None:
    """Chaque série a tous ses mois, de janvier du début à décembre 2025, sans doublon."""
    rows = db_session.execute(
        text(
            """
            SELECT s.code, COUNT(*) AS n, COUNT(DISTINCT (m.annee, m.mois)) AS distincts,
                   MIN(m.annee) AS debut, MAX(m.annee) AS fin,
                   COUNT(*) FILTER (WHERE m.valide_au IS NOT NULL) AS cloturees
            FROM mesures_ressource_mensuelles m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
            GROUP BY s.code
            """
        ),
        {"c": _codes(contrat)},
    ).all()
    assert len(rows) == 142
    for r in rows:
        assert r.n == r.distincts == contrat.nb_mois, r.code
        assert (r.debut, r.fin) == (contrat.annee_debut, contrat.annee_fin), r.code
        assert r.cloturees == 0


@pytest.mark.parametrize("contrat", _CONTRATS, ids=_id)
def test_mesures_fideles_au_csv(db_session: Session, contrat: ContratSerie) -> None:
    """Chaque mesure en base = valeur du CSV committé ; statut brut, confiance B."""
    attendu = _csv_brut(contrat)
    rows = db_session.execute(
        text(
            """
            SELECT loc.code AS localite, m.annee, m.mois, m.valeur, m.statut,
                   m.niveau_confiance_derive
            FROM mesures_ressource_mensuelles m
            JOIN series_metadonnees s ON s.id = m.serie_id
            JOIN localites loc ON loc.id = s.localite_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": _codes(contrat)},
    ).all()
    assert len(rows) == len(attendu) == 142 * contrat.nb_mois
    for r in rows:
        assert r.valeur == attendu[(r.localite, r.annee, r.mois)], (r.localite, r.annee, r.mois)
        assert r.statut == "brut" and r.niveau_confiance_derive == "B"


@pytest.mark.parametrize("contrat", _CONTRATS, ids=_id)
def test_bornes_du_contrat(db_session: Session, contrat: ContratSerie) -> None:
    """Toutes les valeurs dans [0, borne du contrat] ; deux décimales, comme servies."""
    row = db_session.execute(
        text(
            """
            SELECT MIN(m.valeur) AS vmin, MAX(m.valeur) AS vmax,
                   COUNT(*) FILTER (WHERE m.valeur <> round(m.valeur::numeric, 2)) AS fines
            FROM mesures_ressource_mensuelles m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": _codes(contrat)},
    ).one()
    assert 0.0 <= row.vmin <= row.vmax <= contrat.borne_max
    assert row.fines == 0  # NASA POWER sert le mensuel au centième


def test_humidite_relative_au_plus_100(db_session: Session) -> None:
    """Cohérence physique imposée : 0 < HR <= 100 % partout."""
    row = db_session.execute(
        text(
            "SELECT MIN(m.valeur) AS vmin, MAX(m.valeur) AS vmax, COUNT(*) AS n "
            "FROM mesures_ressource_mensuelles m JOIN series_metadonnees s ON s.id = m.serie_id "
            "WHERE s.code = ANY(:c)"
        ),
        {"c": _codes(CONTRATS_METEO_NASA_MENSUELS["rh2m"])},
    ).one()
    assert row.n == 142 * 420
    assert row.vmin > 0.0 and row.vmax <= 100.0


def test_vent_10m_au_moins_vent_2m(db_session: Session) -> None:
    """Signalé, non imposé : le vent croît en principe avec la hauteur (profil de surface)."""
    row = db_session.execute(
        text(
            """
            SELECT COUNT(*) FILTER (WHERE v2 IS NOT NULL AND v10 IS NOT NULL) AS paires,
                   COUNT(*) FILTER (WHERE v10 < v2) AS inversions,
                   MIN(v2 / v10) AS rapport_min
            FROM (
                SELECT s.localite_id, m.annee, m.mois,
                       MAX(m.valeur) FILTER (WHERE s.grandeur_code = 'vent_2m') AS v2,
                       MAX(m.valeur) FILTER (WHERE s.grandeur_code = 'vent_10m') AS v10
                FROM mesures_ressource_mensuelles m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:c)
                GROUP BY s.localite_id, m.annee, m.mois
            ) t
            """
        ),
        {
            "c": _codes(CONTRATS_METEO_NASA_MENSUELS["vent_2m"])
            + _codes(CONTRATS_METEO_NASA_MENSUELS["vent_10m"])
        },
    ).one()
    assert row.paires == 142 * 420
    if row.inversions:
        warnings.warn(
            f"{row.inversions} mois avec vent à 10 m < vent à 2 m (NASA POWER, MERRA-2).",
            stacklevel=1,
        )
    assert row.rapport_min > 0.0  # vent à 2 m jamais nul : rapport défini partout


def test_albedo_plage_usuelle(db_session: Session) -> None:
    """Signalé, non imposé : albédo de surface usuel entre 0,1 et 0,4 (sol, végétation)."""
    row = db_session.execute(
        text(
            """
            SELECT COUNT(*) AS n,
                   COUNT(*) FILTER (WHERE m.valeur < 0.1 OR m.valeur > 0.4) AS hors_plage,
                   COUNT(DISTINCT s.localite_id)
                       FILTER (WHERE m.valeur < 0.1 OR m.valeur > 0.4) AS localites,
                   MIN(m.valeur) AS vmin, MAX(m.valeur) AS vmax
            FROM mesures_ressource_mensuelles m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": _codes(CONTRATS_METEO_NASA_MENSUELS["albedo_surface"])},
    ).one()
    assert row.n == 142 * 300
    assert row.vmin > 0.0 and row.vmax < 1.0  # plage théorique de l'albédo
    if row.hors_plage:
        warnings.warn(
            f"Albédo NASA POWER hors [0,1 ; 0,4] : {row.hors_plage} mois sur {row.n}, "
            f"{row.localites} localités, de {row.vmin} à {row.vmax} (ADR-0019).",
            stacklevel=1,
        )


def test_mois_aberrant_grave_tel_que_servi(db_session: Session) -> None:
    """Septembre 2022 à San-Pédro : 56,28 mm/jour gravés sans correction, mise en garde portée."""
    row = db_session.execute(
        text(
            "SELECT m.valeur, s.note_publique FROM mesures_ressource_mensuelles m "
            "JOIN series_metadonnees s ON s.id = m.serie_id "
            "WHERE s.code = :c AND m.annee = 2022 AND m.mois = 9"
        ),
        {"c": CONTRATS_METEO_NASA_MENSUELS["precipitation"].code_serie("civ_dep_san_pedro")},
    ).one()
    assert row.valeur == 56.28
    assert "gravés tels que servis, sans correction" in row.note_publique


@pytest.mark.parametrize(
    ("grandeur", "extrait"),
    [
        ("precipitation", "gravés tels que servis, sans correction"),
        ("vent_2m", "effet du couvert dans la réanalyse"),
        ("albedo_surface", "Non servi avant 2001."),
    ],
)
def test_mise_en_garde_voyage_avec_les_donnees(
    db_session: Session, grandeur: str, extrait: str
) -> None:
    """La mise en garde de la grandeur figure dans la note des 142 séries, et d'elles seules."""
    annotees = {
        row.code
        for row in db_session.execute(
            text(
                "SELECT code FROM series_metadonnees "
                "WHERE code LIKE 'nasa_power_%_mensuel_%' AND strpos(note_publique, :e) > 0"
            ),
            {"e": extrait},
        ).all()
    }
    assert annotees == set(_codes(CONTRATS_METEO_NASA_MENSUELS[grandeur]))
