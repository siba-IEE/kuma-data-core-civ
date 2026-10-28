"""Tests d'intégration du rayonnement journalier CAMS Radiation (migration 0054).

426 séries ``cams_<ghi|dni|dhi>_journalier_<localité>`` dans ``mesures_ressource``,
2005-2025 (7 670 jours), source ``cams_radiation`` (id 13), méthode
``modele_satellitaire``, confiance B : irradiation tous ciels du jour UTC au point
de la localité, telle que servie par CAMS (v4.6), en kWh/m²/jour.

Vérifie les métadonnées, la **fidélité exacte** au CSV gzip committé (agrégats
par série), les **lacunes** (jours non servis par CAMS, jamais gravés), les 126
séries distinctes, la cohérence avec le mensuel CAMS courant (2021-2025 révisé
par la migration 0056, ADR-0037), la comparaison avec NASA POWER, la mise en
garde des 426 séries mensuelles et l'audit par série.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds.audit_par_serie import empreinte_fichier
from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.rayonnement_cams_journalier_civ import (
    CONTRATS_CAMS_JOURNALIERS,
    LOT_CAMS_JOURNALIER,
)
from tests.integration.db.journalier_csv import (
    agregats_base,
    agregats_csv,
    entrees_audit_par_serie,
    lignes_auditees_ligne_a_ligne,
)

pytestmark = pytest.mark.integration

_GRANDEURS = ("ghi", "dni", "dhi")
_LOCALITES = sorted(code for code, _, _, _ in points_nationaux())
_DEBUT, _FIN = date(2005, 1, 1), date(2025, 12, 31)
_NB_JOURS = 7_670
_REVISION = "0054"
_SANS_IMAGES = (date(2005, 1, 11), date(2005, 1, 12), date(2006, 1, 10), date(2006, 1, 11))
_JOUR_PARTIEL = date(2006, 9, 23)
_NB_LOCALITES_JOUR_PARTIEL = 54


def _codes(grandeur: str) -> list[str]:
    contrat = CONTRATS_CAMS_JOURNALIERS[grandeur]
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
                   src.code AS source, loc.code AS localite, loc.nom, u.code AS unite
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
        assert (r.source, r.grandeur_code, r.actif) == ("cams_radiation", grandeur, True)
        assert (r.methode_collecte, r.granularite) == ("modele_satellitaire", "journalier")
        assert (r.periode_debut, r.periode_fin, r.unite) == (_DEBUT, _FIN, "kwh_par_m2_jour")
        assert r.libelle == f"{grandeur.upper()} journalier CAMS Radiation — {r.nom} (2005-2025)"
        for fragment in (
            "service v4.6",
            "jour UTC (jour civil local, UTC+0)",
            "2005-01-11, 2005-01-12, 2006-01-10 et 2006-01-11 partout",
            "2006-09-23 dans 54 localités",
            "2021-2025 compris depuis la révision du mensuel CAMS (migration 0056",
            "ADR-0011, ADR-0035",
        ):
            assert fragment in r.note_publique, fragment
    assert len({r.note_publique for r in rows}) == 1


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_mesures_fideles_au_csv_et_lacunes(db_session: Session, grandeur: str) -> None:
    """Par série : agrégats exacts base = CSV ; jours absents = jours non servis par CAMS."""
    contrat = CONTRATS_CAMS_JOURNALIERS[grandeur]
    attendu, lacunes = agregats_csv(
        contrat.nom_fichier(LOT_CAMS_JOURNALIER), contrat.prefixe_code, _DEBUT
    )
    assert sorted(attendu) == sorted(_codes(grandeur))
    partielles = {c for c, jours in lacunes.items() if _JOUR_PARTIEL in jours}
    assert len(partielles) == _NB_LOCALITES_JOUR_PARTIEL
    for code in _codes(grandeur):
        trous = _SANS_IMAGES + ((_JOUR_PARTIEL,) if code in partielles else ())
        assert lacunes[code] == trous
        assert attendu[code][:3] == (_NB_JOURS - len(trous), _DEBUT, _FIN)
    base = agregats_base(db_session, _codes(grandeur), _DEBUT)
    assert [c for c in _codes(grandeur) if attendu[c] != base.get(c)] == []
    absents = db_session.execute(
        text(
            """
            SELECT COUNT(*) FROM mesures_ressource m JOIN series_metadonnees s
                ON s.id = m.serie_id
            WHERE s.code = ANY(:c) AND m.instant_mesure = ANY(:j)
            """
        ),
        {"c": _codes(grandeur), "j": [*_SANS_IMAGES, _JOUR_PARTIEL]},
    ).scalar_one()
    assert absents == 142 - _NB_LOCALITES_JOUR_PARTIEL
    r = db_session.execute(
        text(
            """
            SELECT COUNT(*) AS n,
                   COUNT(*) FILTER (WHERE m.statut <> 'brut' OR m.niveau_confiance_derive <> 'B'
                                    OR m.valide_au IS NOT NULL) AS hors_contrat,
                   MIN(m.valeur) AS mini, MAX(m.valeur) AS maxi
            FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": _codes(grandeur)},
    ).one()
    assert (r.n, r.hors_contrat) == (1_088_518, 0)
    assert 0.0 <= r.mini <= r.maxi <= contrat.borne_max


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_series_distinctes(db_session: Session, grandeur: str) -> None:
    """126 séries distinctes sur 142 localités (35 pour NASA POWER, maille de 0,5°)."""
    base = agregats_base(db_session, _codes(grandeur), _DEBUT)
    assert len(base) == 142 and len(set(base.values())) == 126


def _ecarts_au_mensuel(db_session: Session, grandeur: str) -> dict[str, tuple[Decimal, ...]]:
    """Moyenne des jours servis - mensuel CAMS courant, par catégorie de mois."""
    rows = db_session.execute(
        text(
            """
            WITH jours AS (
                SELECT s.localite_id, EXTRACT(YEAR FROM m.instant_mesure)::int AS annee,
                       EXTRACT(MONTH FROM m.instant_mesure)::int AS mois,
                       AVG(m.valeur::numeric) AS moy, COUNT(*) AS n
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:c)
                GROUP BY 1, 2, 3
            ), ecarts AS (
                SELECT j.annee, j.moy - mm.valeur::numeric AS e,
                       j.n < EXTRACT(DAY FROM (make_date(j.annee, j.mois, 1)
                                               + interval '1 month - 1 day')) AS lacune
                FROM jours j
                JOIN localites l ON l.id = j.localite_id
                JOIN series_metadonnees sm ON sm.code = :prefixe || l.code
                JOIN mesures_ressource_mensuelles mm
                    ON mm.serie_id = sm.id AND mm.annee = j.annee AND mm.mois = j.mois
                   AND mm.valide_au IS NULL
            )
            SELECT CASE WHEN lacune THEN 'lacune' WHEN annee >= 2021 THEN 'revision'
                        ELSE 'autres' END AS categorie,
                   COUNT(*) AS n, AVG(e) AS moyen, MAX(ABS(e)) AS maxi
            FROM ecarts GROUP BY 1
            """
        ),
        {"c": _codes(grandeur), "prefixe": f"cams_{grandeur}_mensuel_"},
    ).all()
    return {r.categorie: (r.n, r.moyen, r.maxi) for r in rows}


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_coherence_avec_le_mensuel(db_session: Session, grandeur: str) -> None:
    """Mois complets : mensuel courant redonné à 0,0001 près, 2021-2025 compris (0056).

    Avant la révision gravée par 0056, 2021-2025 s'écartait du mensuel gravé en
    0030 ; l'ampleur de la révision est vérifiée par ``test_revision_cams_mensuel_seed``.
    """
    ecarts = _ecarts_au_mensuel(db_session, grandeur)
    n, _, ecart_max = ecarts["autres"]
    assert n == 26_926 and ecart_max < Decimal("0.0001")
    n, _, ecart_max = ecarts["revision"]
    assert n == 8_520 and ecart_max < Decimal("0.0001")
    assert ecarts["lacune"][0] == 338


@pytest.mark.parametrize(
    ("grandeur", "cams", "nasa", "plus_bas", "plus_haut"),
    [
        ("ghi", "5.36", "4.84", ("civ_dep_abidjan", "-0.03"), ("civ_dep_fresco", "0.87")),
        ("dni", "3.85", "2.46", ("civ_dep_abidjan", "0.61"), ("civ_dep_fresco", "2.07")),
        ("dhi", "2.61", "2.51", ("civ_dep_kaniasso", "-0.18"), ("civ_dep_divo", "0.27")),
    ],
)
def test_comparaison_nasa_citee(
    db_session: Session,
    grandeur: str,
    cams: str,
    nasa: str,
    plus_bas: tuple[str, str],
    plus_haut: tuple[str, str],
) -> None:
    """CAMS - NASA POWER journalier, mêmes jours servis, 142 localités : chiffres des notes."""
    rows = db_session.execute(
        text(
            """
            WITH c AS (
                SELECT s.localite_id, m.instant_mesure AS jour, m.valeur::numeric AS v
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:cams)
            ), n AS (
                SELECT s.localite_id, m.instant_mesure AS jour, m.valeur::numeric AS v
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                JOIN sources src ON src.id = s.source_id AND src.code = 'nasa_power'
                WHERE s.grandeur_code = :g AND s.granularite = 'journalier'
                  AND m.valide_au IS NULL
            )
            SELECT l.code, COUNT(*) AS n, SUM(c.v) AS sc, SUM(n.v) AS sn, AVG(c.v - n.v) AS ecart
            FROM c JOIN n USING (localite_id, jour) JOIN localites l ON l.id = c.localite_id
            GROUP BY l.code
            """
        ),
        {"cams": _codes(grandeur), "g": grandeur},
    ).all()
    assert len(rows) == 142
    total = sum(r.n for r in rows)
    assert total == 1_088_518
    assert round(sum(r.sc for r in rows) / total, 2) == Decimal(cams)
    assert round(sum(r.sn for r in rows) / total, 2) == Decimal(nasa)
    bas = min(rows, key=lambda r: r.ecart)
    haut = max(rows, key=lambda r: r.ecart)
    assert (bas.code, round(bas.ecart, 2)) == (plus_bas[0], Decimal(plus_bas[1]))
    assert (haut.code, round(haut.ecart, 2)) == (plus_haut[0], Decimal(plus_haut[1]))


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_mise_en_garde_mensuelle(db_session: Session, grandeur: str) -> None:
    """Les 142 séries mensuelles CAMS de la grandeur portent la mise en garde, elles seules.

    Ajoutée par 0054, remplacée par celle de la révision gravée (migration 0056).
    """
    porteuses = {
        r.code
        for r in db_session.execute(
            text(
                "SELECT code FROM series_metadonnees "
                "WHERE strpos(note_publique, :f) > 0 AND grandeur_code = :g"
            ),
            {"f": "Révision de la source (ADR-0037) : CAMS a révisé 2021-2025", "g": grandeur},
        )
    }
    assert porteuses == {f"cams_{grandeur}_mensuel_{code}" for code in _LOCALITES}


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_audit_par_serie(db_session: Session, grandeur: str) -> None:
    """Une entrée d'audit par série (``I``, révision 0054) ; aucune entrée ligne à ligne."""
    contrat = CONTRATS_CAMS_JOURNALIERS[grandeur]
    ids = _ids(db_session, grandeur)
    assert len(ids) == 142
    _, lacunes = agregats_csv(
        contrat.nom_fichier(LOT_CAMS_JOURNALIER), contrat.prefixe_code, _DEBUT
    )
    entrees = entrees_audit_par_serie(db_session, list(ids.values()))
    fichier = contrat.nom_fichier(LOT_CAMS_JOURNALIER)
    empreinte = empreinte_fichier(contrat, LOT_CAMS_JOURNALIER)
    for code, sid in ids.items():
        assert entrees[sid] == {
            "audit": "par_serie",
            "revision": _REVISION,
            "serie_code": code,
            "nb_mesures": _NB_JOURS - len(lacunes[code]),
            "premier_instant": _DEBUT.isoformat(),
            "dernier_instant": _FIN.isoformat(),
            "fichier": fichier,
            "sha256": empreinte,
        }
    assert lignes_auditees_ligne_a_ligne(db_session, list(ids.values())) == 0
