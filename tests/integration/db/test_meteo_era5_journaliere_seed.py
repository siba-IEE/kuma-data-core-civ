"""Tests d'intégration de la température et du vent journaliers ERA5 (migration 0053).

284 séries ``ecmwf_era5_<t2m|vent_10m>_journalier_<localité>`` dans
``mesures_ressource``, 1991-2025 (12 784 jours), source ``ecmwf_era5`` (id 2),
méthode ``reanalyse``, confiance B : moyenne des 24 valeurs horaires ERA5 du jour
civil UTC au nœud 0,25° le plus proche.

Vérifie les métadonnées, la **fidélité exacte** au CSV gzip committé (agrégats
par série en ``numeric`` et en ``Decimal``), les 110 séries distinctes (une par
nœud), la cohérence avec le mensuel ERA5 (0036) et les chiffres cités par les
notes publiques, l'audit par série et l'absence d'autre série journalière ERA5.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds.audit_par_serie import empreinte_fichier
from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.meteo_era5_civ import maille_era5
from kuma_data_core.db.seeds.meteo_era5_journaliere_civ import (
    CONTRATS_METEO_ERA5_JOURNALIERS,
    LOT_METEO_ERA5_JOURNALIERE,
)
from tests.integration.db.journalier_csv import (
    agregats_base,
    agregats_csv,
    entrees_audit_par_serie,
    lignes_auditees_ligne_a_ligne,
)

pytestmark = pytest.mark.integration

_GRANDEURS = ("t2m", "vent_10m")
_POINTS = points_nationaux()
_LOCALITES = sorted(code for code, _, _, _ in _POINTS)
_DEBUT, _FIN = date(1991, 1, 1), date(2025, 12, 31)
_NB_JOURS = 12_784
_REVISION = "0053"
_UNITES = {"t2m": "degree_celsius", "vent_10m": "metre_par_seconde"}
_LIBELLES = {"t2m": "Température à 2 m", "vent_10m": "Vent à 10 m"}


def _codes(grandeur: str) -> list[str]:
    contrat = CONTRATS_METEO_ERA5_JOURNALIERS[grandeur]
    return [contrat.code_serie(code) for code in _LOCALITES]


def _ids(db_session: Session, grandeur: str) -> dict[str, int]:
    return {
        r.code: r.id
        for r in db_session.execute(
            text("SELECT code, id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": _codes(grandeur)},
        )
    }


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_series_metadonnees(db_session: Session, grandeur: str) -> None:
    """142 séries par grandeur : source, méthode, période, unité, libellé et note."""
    rows = db_session.execute(
        text(
            """
            SELECT s.code, s.libelle, s.grandeur_code, s.methode_collecte, s.granularite,
                   s.periode_debut, s.periode_fin, s.note_publique, s.actif,
                   src.code AS source, src.id AS source_id, loc.code AS localite, loc.nom,
                   u.code AS unite
            FROM series_metadonnees s
            JOIN sources src ON src.id = s.source_id
            JOIN localites loc ON loc.id = s.localite_id
            JOIN grandeurs_referentiel g ON g.code = s.grandeur_code
            JOIN unites u ON u.id = g.unite_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": _codes(grandeur)},
    ).all()
    assert sorted(r.localite for r in rows) == _LOCALITES
    for r in rows:
        assert (r.source, r.source_id, r.grandeur_code, r.actif) == (
            "ecmwf_era5",
            2,
            grandeur,
            True,
        )
        assert (r.methode_collecte, r.granularite) == ("reanalyse", "journalier")
        assert (r.periode_debut, r.periode_fin, r.unite) == (_DEBUT, _FIN, _UNITES[grandeur])
        assert r.libelle == f"{_LIBELLES[grandeur]} journalier ERA5 (CDS) — {r.nom} (1991-2025)"
        assert "00 h à 23 h du jour civil UTC" in r.note_publique
        assert "Point de grille 0,25° le plus proche" in r.note_publique
        assert "Copernicus Climate Change Service" in r.note_publique
        assert "ADR-0021, ADR-0034" in r.note_publique
    assert len({r.note_publique for r in rows}) == 1


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_mesures_fideles_au_csv(db_session: Session, grandeur: str) -> None:
    """Par série : nombre, bornes, Σ valeur et Σ rang * valeur exacts, base = CSV."""
    contrat = CONTRATS_METEO_ERA5_JOURNALIERS[grandeur]
    attendu, lacunes = agregats_csv(
        contrat.nom_fichier(LOT_METEO_ERA5_JOURNALIERE), contrat.prefixe_code, _DEBUT
    )
    assert not lacunes and sorted(attendu) == sorted(_codes(grandeur))
    assert {(n, p, d) for n, p, d, _, _ in attendu.values()} == {(_NB_JOURS, _DEBUT, _FIN)}
    base = agregats_base(db_session, _codes(grandeur), _DEBUT)
    assert [c for c in _codes(grandeur) if attendu[c] != base.get(c)] == []
    r = db_session.execute(
        text(
            """
            SELECT COUNT(*) AS n,
                   COUNT(*) FILTER (WHERE m.statut <> 'brut' OR m.niveau_confiance_derive <> 'B'
                                    OR m.valide_au IS NOT NULL) AS hors_contrat,
                   COUNT(*) FILTER (WHERE m.valeur::numeric <> ROUND(m.valeur::numeric, 4))
                       AS plus_de_4_decimales,
                   MIN(m.valeur) AS mini, MAX(m.valeur) AS maxi
            FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": _codes(grandeur)},
    ).one()
    assert (r.n, r.hors_contrat, r.plus_de_4_decimales) == (142 * _NB_JOURS, 0, 0)
    assert 0.0 <= r.mini <= r.maxi <= contrat.borne_max


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_une_serie_distincte_par_noeud(db_session: Session, grandeur: str) -> None:
    """110 séries distinctes : les localités d'un même nœud 0,25° partagent leurs valeurs."""
    base = agregats_base(db_session, _codes(grandeur), _DEBUT)
    contrat = CONTRATS_METEO_ERA5_JOURNALIERS[grandeur]
    par_noeud: dict[tuple[float, float], set[object]] = {}
    for code, _, lat, lon in _POINTS:
        par_noeud.setdefault(maille_era5(lat, lon), set()).add(base[contrat.code_serie(code)])
    assert len(par_noeud) == 110
    assert all(len(v) == 1 for v in par_noeud.values())
    assert len(set(base.values())) == 110


def _ecarts_au_mensuel(db_session: Session, grandeur: str) -> tuple[Decimal, Decimal, Decimal]:
    """(min, moyenne, max) de moyenne des jours du mois - mensuel ERA5 0036, valeurs gravées."""
    r = db_session.execute(
        text(
            """
            WITH jours AS (
                SELECT s.localite_id, EXTRACT(YEAR FROM m.instant_mesure)::int AS annee,
                       EXTRACT(MONTH FROM m.instant_mesure)::int AS mois,
                       AVG(m.valeur::numeric) AS moy
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:c)
                GROUP BY 1, 2, 3
            ), ecarts AS (
                SELECT j.moy - mm.valeur::numeric AS e
                FROM jours j
                JOIN localites l ON l.id = j.localite_id
                JOIN series_metadonnees sm
                    ON sm.localite_id = j.localite_id AND sm.code = :prefixe || l.code
                JOIN mesures_ressource_mensuelles mm
                    ON mm.serie_id = sm.id AND mm.annee = j.annee AND mm.mois = j.mois
            )
            SELECT MIN(e) AS mini, AVG(e) AS moyen, MAX(e) AS maxi, COUNT(*) AS n FROM ecarts
            """
        ),
        {"c": _codes(grandeur), "prefixe": f"ecmwf_era5_{grandeur}_mensuel_"},
    ).one()
    assert r.n == 142 * 420
    return r.mini, r.moyen, r.maxi


def test_coherence_avec_le_mensuel(db_session: Session) -> None:
    """Moyenne des jours du mois - mensuel 0036 : chiffres cités par les notes publiques.

    Température : 0,002 °C près. Vent : toujours sous le mensuel ``10m_wind_speed``,
    de 0,001 à 0,110 m/s (0,021 en moyenne), vitesse recalculée depuis u et v.
    """
    mini, _, maxi = _ecarts_au_mensuel(db_session, "t2m")
    assert max(abs(mini), abs(maxi)) < Decimal("0.002")
    mini, moyen, maxi = _ecarts_au_mensuel(db_session, "vent_10m")
    assert (round(maxi, 3), round(moyen, 3), round(mini, 3)) == (
        Decimal("-0.001"),
        Decimal("-0.021"),
        Decimal("-0.110"),
    )


@pytest.mark.parametrize(
    ("grandeur", "moyen_era5", "moyen_nasa", "plus_bas", "plus_haut"),
    [
        ("t2m", "26.38", "26.11", ("civ_dep_touba", "-0.49"), ("civ_dep_kouibly", "1.59")),
        ("vent_10m", "2.04", "2.52", ("civ_dep_tiapoum", "-1.68"), ("civ_dep_issia", "0.96")),
    ],
)
def test_comparaison_nasa_citee(
    db_session: Session,
    grandeur: str,
    moyen_era5: str,
    moyen_nasa: str,
    plus_bas: tuple[str, str],
    plus_haut: tuple[str, str],
) -> None:
    """ERA5 - NASA POWER journalier aux 142 localités, 1991-2025 : chiffres des notes."""
    rows = db_session.execute(
        text(
            """
            WITH e AS (
                SELECT s.localite_id, m.instant_mesure AS jour, m.valeur::numeric AS v
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:era5)
            ), n AS (
                SELECT s.localite_id, m.instant_mesure AS jour, m.valeur::numeric AS v
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                JOIN sources src ON src.id = s.source_id AND src.code = 'nasa_power'
                WHERE s.grandeur_code = :g AND s.granularite = 'journalier'
            )
            SELECT l.code, COUNT(*) AS n, AVG(e.v) AS era5, AVG(n.v) AS nasa,
                   AVG(e.v - n.v) AS ecart
            FROM e JOIN n USING (localite_id, jour) JOIN localites l ON l.id = e.localite_id
            GROUP BY l.code
            """
        ),
        {"era5": _codes(grandeur), "g": grandeur},
    ).all()
    assert len(rows) == 142 and {r.n for r in rows} == {_NB_JOURS}
    assert round(sum(r.era5 for r in rows) / 142, 2) == Decimal(moyen_era5)
    assert round(sum(r.nasa for r in rows) / 142, 2) == Decimal(moyen_nasa)
    bas = min(rows, key=lambda r: r.ecart)
    haut = max(rows, key=lambda r: r.ecart)
    assert (bas.code, round(bas.ecart, 2)) == (plus_bas[0], Decimal(plus_bas[1]))
    assert (haut.code, round(haut.ecart, 2)) == (plus_haut[0], Decimal(plus_haut[1]))


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_audit_par_serie(db_session: Session, grandeur: str) -> None:
    """Une entrée d'audit par série (``I``, révision 0053) ; aucune entrée ligne à ligne."""
    contrat = CONTRATS_METEO_ERA5_JOURNALIERS[grandeur]
    ids = _ids(db_session, grandeur)
    assert len(ids) == 142
    entrees = entrees_audit_par_serie(db_session, list(ids.values()))
    fichier = contrat.nom_fichier(LOT_METEO_ERA5_JOURNALIERE)
    empreinte = empreinte_fichier(contrat, LOT_METEO_ERA5_JOURNALIERE)
    for code, sid in ids.items():
        assert entrees[sid] == {
            "audit": "par_serie",
            "revision": _REVISION,
            "serie_code": code,
            "nb_mesures": _NB_JOURS,
            "premier_instant": _DEBUT.isoformat(),
            "dernier_instant": _FIN.isoformat(),
            "fichier": fichier,
            "sha256": empreinte,
        }
    assert lignes_auditees_ligne_a_ligne(db_session, list(ids.values())) == 0


def test_series_journalieres_era5(db_session: Session) -> None:
    """ERA5 journalier : pluie (0050), température et vent (0053), humidité (0057), 142 chacune."""
    rows = db_session.execute(
        text(
            """
            SELECT grandeur_code, COUNT(*) AS n, COUNT(DISTINCT localite_id) AS loc
            FROM series_metadonnees WHERE source_id = 2 AND granularite = 'journalier'
            GROUP BY grandeur_code
            """
        )
    ).all()
    assert {r.grandeur_code: (r.n, r.loc) for r in rows} == {
        "precipitation": (142, 142),
        "rh2m": (142, 142),
        "t2m": (142, 142),
        "vent_10m": (142, 142),
    }
