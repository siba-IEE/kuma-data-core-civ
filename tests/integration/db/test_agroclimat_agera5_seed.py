"""Tests d'intégration de l'agroclimat AgERA5 (migration 0059, ADR-0040).

Source ``agera5`` (id 19), 4 grandeurs nouvelles au référentiel (``et0``, ``t2m_min``,
``t2m_max``, ``vpd_tmax``), 1 136 séries ``agera5_<grandeur>_<journalier|mensuel>_<localité>``
aux 142 localités, 1991-2025 : 568 dans ``mesures_ressource`` (12 784 jours) et 568 dans
``mesures_ressource_mensuelles`` (420 mois), méthode ``reanalyse``, confiance B.

Vérifie la source, le référentiel, les métadonnées, la **fidélité exacte** aux CSV gzip
committés, la cohérence du mois avec ses jours, Tmin ≤ Tmax, les chiffres cités par les notes
publiques, l'audit et la dégénérescence de pixel.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds.agroclimat_agera5_civ import (
    CONTRATS_AGERA5_JOURNALIERS,
    CONTRATS_AGERA5_MENSUELS,
    GRANDEURS_AGERA5,
    LOT_AGERA5,
)
from kuma_data_core.db.seeds.audit_par_serie import empreinte_fichier
from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.series_csv import lire_series
from tests.integration.db.journalier_csv import (
    agregats_base,
    agregats_csv,
    entrees_audit_par_serie,
    lignes_auditees_ligne_a_ligne,
)

pytestmark = pytest.mark.integration

_LOCALITES = sorted(code for code, _, _, _ in points_nationaux())
_DEBUT, _FIN = date(1991, 1, 1), date(2025, 12, 31)
_NB_JOURS = 12_784
_NB_MOIS = 420
_REVISION = "0059"
_IDS = {
    "et0": (47, "mm_par_jour"),
    "t2m_min": (48, "degree_celsius"),
    "t2m_max": (49, "degree_celsius"),
    "vpd_tmax": (50, "kilopascal"),
}
_GRANDEURS = tuple(GRANDEURS_AGERA5)
_CONTRATS = {"journalier": CONTRATS_AGERA5_JOURNALIERS, "mensuel": CONTRATS_AGERA5_MENSUELS}
_CAS = [(g, gr) for gr in _CONTRATS for g in _GRANDEURS]


def _codes(grandeur: str, granularite: str) -> list[str]:
    return [_CONTRATS[granularite][grandeur].code_serie(code) for code in _LOCALITES]


def test_source(db_session: Session) -> None:
    """Source ``agera5`` à id figé, DOI du jeu, licence CC BY 4.0."""
    r = db_session.execute(
        text(
            "SELECT code, type_source, doi, fiabilite, url, metadonnees, notes "
            "FROM sources WHERE id = 19"
        )
    ).one()
    assert (r.code, r.type_source, r.doi, r.fiabilite) == (
        "agera5",
        "base_donnees",
        "10.24381/cds.6c68c9bb",
        "haute",
    )
    assert r.url == "https://cds.climate.copernicus.eu/datasets/sis-agrometeorological-indicators"
    assert "CC BY 4.0" in r.metadonnees["licence"]
    assert "doi:10.24381/cds.6c68c9bb" in r.notes


def test_grandeurs_referentiel(db_session: Session) -> None:
    """4 grandeurs F1 stockées, unités, libellés, descriptions citant l'ADR-0040."""
    rows = db_session.execute(
        text(
            """
            SELECT g.id, g.code, g.libelle, u.code AS unite, g.famille, g.strategie_calcul,
                   g.version_formule_actuelle, g.description, g.actif
            FROM grandeurs_referentiel g JOIN unites u ON u.id = g.unite_id
            WHERE g.code = ANY(:c)
            """
        ),
        {"c": list(_IDS)},
    ).all()
    assert {r.code: (r.id, r.unite) for r in rows} == _IDS
    for r in rows:
        assert r.libelle == GRANDEURS_AGERA5[r.code].libelle
        assert (r.famille, r.strategie_calcul, r.version_formule_actuelle, r.actif) == (
            "F1",
            "stockee",
            1,
            True,
        )
        assert "ADR-0040" in r.description


@pytest.mark.parametrize(("grandeur", "granularite"), _CAS)
def test_series_metadonnees(db_session: Session, grandeur: str, granularite: str) -> None:
    """142 séries : source, méthode, période, libellé et note."""
    rows = db_session.execute(
        text(
            """
            SELECT s.libelle, s.grandeur_code, s.methode_collecte, s.granularite,
                   s.periode_debut, s.periode_fin, s.note_publique, s.actif,
                   src.code AS source, loc.code AS localite, loc.nom
            FROM series_metadonnees s
            JOIN sources src ON src.id = s.source_id
            JOIN localites loc ON loc.id = s.localite_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": _codes(grandeur, granularite)},
    ).all()
    assert sorted(r.localite for r in rows) == _LOCALITES
    for r in rows:
        assert (r.source, r.grandeur_code, r.actif) == ("agera5", grandeur, True)
        assert (r.methode_collecte, r.granularite) == ("reanalyse", granularite)
        assert (r.periode_debut, r.periode_fin) == (_DEBUT, _FIN)
        assert r.libelle == (
            f"{GRANDEURS_AGERA5[grandeur].libelle} {granularite} AgERA5 — {r.nom} (1991-2025)"
        )
        for fragment in ("AgERA5 v2.0", "maille de 0,1°", "Confiance B (ADR-0040)", "(2026)."):
            assert fragment in r.note_publique, fragment
    assert len({r.note_publique for r in rows}) == 1


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_journalier_fidele_au_csv(db_session: Session, grandeur: str) -> None:
    """Par série : nombre, bornes, Σ valeur et Σ rang * valeur exacts ; aucune lacune."""
    contrat = CONTRATS_AGERA5_JOURNALIERS[grandeur]
    codes = _codes(grandeur, "journalier")
    attendu, lacunes = agregats_csv(contrat.nom_fichier(LOT_AGERA5), contrat.prefixe_code, _DEBUT)
    assert not lacunes and sorted(attendu) == sorted(codes)
    assert {(n, p, d) for n, p, d, _, _ in attendu.values()} == {(_NB_JOURS, _DEBUT, _FIN)}
    base = agregats_base(db_session, codes, _DEBUT)
    assert [c for c in codes if attendu[c] != base.get(c)] == []


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_mensuel_fidele_au_csv(db_session: Session, grandeur: str) -> None:
    """Chaque mesure mensuelle = CSV committé ; brut, confiance B, courante."""
    attendu = {
        (s["code"], a, m): v
        for s in lire_series(CONTRATS_AGERA5_MENSUELS[grandeur], LOT_AGERA5)
        for a, m, v in s["mesures"]
    }
    rows = db_session.execute(
        text(
            """
            SELECT s.code, m.annee, m.mois, m.valeur, m.statut, m.niveau_confiance_derive,
                   m.valide_au
            FROM mesures_ressource_mensuelles m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": _codes(grandeur, "mensuel")},
    ).all()
    assert len(rows) == len(attendu) == 142 * _NB_MOIS
    for r in rows:
        assert r.valeur == attendu[(r.code, r.annee, r.mois)], (r.code, r.annee, r.mois)
        assert (r.statut, r.niveau_confiance_derive, r.valide_au) == ("brut", "B", None)


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_mois_et_moyenne_de_ses_jours(db_session: Session, grandeur: str) -> None:
    """Moyenne des jours du mois - mois : à l'arrondi près (0,0001)."""
    r = db_session.execute(
        text(
            """
            WITH jours AS (
                SELECT s.localite_id, EXTRACT(YEAR FROM m.instant_mesure)::int AS annee,
                       EXTRACT(MONTH FROM m.instant_mesure)::int AS mois,
                       AVG(m.valeur::numeric) AS moy
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:j)
                GROUP BY 1, 2, 3
            )
            SELECT COUNT(*) AS n, MAX(ABS(j.moy - mm.valeur::numeric)) AS maxi
            FROM jours j
            JOIN series_metadonnees sm ON sm.localite_id = j.localite_id AND sm.code = ANY(:m)
            JOIN mesures_ressource_mensuelles mm
                ON mm.serie_id = sm.id AND mm.annee = j.annee AND mm.mois = j.mois
            """
        ),
        {"j": _codes(grandeur, "journalier"), "m": _codes(grandeur, "mensuel")},
    ).one()
    assert r.n == 142 * _NB_MOIS
    assert r.maxi <= Decimal("0.0001")


def test_tmin_sous_tmax(db_session: Session) -> None:
    """Chaque jour-localité : Tmin ≤ Tmax ; ET0 et déficit positifs."""
    r = db_session.execute(
        text(
            """
            SELECT COUNT(*) AS n,
                   COUNT(*) FILTER (WHERE mn.valeur > mx.valeur) AS inverses
            FROM mesures_ressource mn
            JOIN series_metadonnees sn ON sn.id = mn.serie_id AND sn.code = ANY(:mn)
            JOIN series_metadonnees sx ON sx.localite_id = sn.localite_id AND sx.code = ANY(:mx)
            JOIN mesures_ressource mx
                ON mx.serie_id = sx.id AND mx.instant_mesure = mn.instant_mesure
            """
        ),
        {"mn": _codes("t2m_min", "journalier"), "mx": _codes("t2m_max", "journalier")},
    ).one()
    assert (r.n, r.inverses) == (142 * _NB_JOURS, 0)


def test_audit(db_session: Session) -> None:
    """Journalier : une entrée par série (``I``, 0059) ; mensuel : ligne à ligne."""
    for grandeur, contrat in CONTRATS_AGERA5_JOURNALIERS.items():
        ids = dict(
            db_session.execute(
                text("SELECT code, id FROM series_metadonnees WHERE code = ANY(:c)"),
                {"c": _codes(grandeur, "journalier")},
            ).all()
        )
        assert len(ids) == 142
        entrees = entrees_audit_par_serie(db_session, list(ids.values()))
        for code, sid in ids.items():
            assert entrees[sid] == {
                "audit": "par_serie",
                "revision": _REVISION,
                "serie_code": code,
                "nb_mesures": _NB_JOURS,
                "premier_instant": _DEBUT.isoformat(),
                "dernier_instant": _FIN.isoformat(),
                "fichier": contrat.nom_fichier(LOT_AGERA5),
                "sha256": empreinte_fichier(contrat, LOT_AGERA5),
            }
        assert lignes_auditees_ligne_a_ligne(db_session, list(ids.values())) == 0
    n = db_session.execute(
        text(
            """
            SELECT COUNT(*) FROM audit_log a
            WHERE a.schema_audite = 'public' AND a.table_auditee = 'mesures_ressource_mensuelles'
              AND a.type_operation = 'I'
              AND (a.valeurs_apres ->> 'serie_id')::bigint IN (
                  SELECT id FROM series_metadonnees WHERE code = ANY(:c))
            """
        ),
        {"c": [c for g in _GRANDEURS for c in _codes(g, "mensuel")]},
    ).scalar_one()
    assert n == len(_GRANDEURS) * 142 * _NB_MOIS


def test_degenerescence_de_pixel(db_session: Session) -> None:
    """Une ligne par série mensuelle (ADR-0027) ; 119 mailles distinctes pour 142 localités."""
    rows = db_session.execute(
        text(
            """
            SELECT s.grandeur_code, COUNT(*) AS n, SUM(1.0 / (gm.valeur + 1)) AS distinctes
            FROM grandeurs_metier gm JOIN series_metadonnees s ON s.id = gm.series_metadonnees_id
            WHERE gm.grandeur_code = 'degenerescence_pixel' AND s.code = ANY(:c)
              AND gm.valide_au IS NULL
            GROUP BY 1
            """
        ),
        {"c": [c for g in _GRANDEURS for c in _codes(g, "mensuel")]},
    ).all()
    assert {r.grandeur_code: (r.n, round(r.distinctes)) for r in rows} == dict.fromkeys(
        _GRANDEURS, (142, 119)
    )
