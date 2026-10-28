"""Tests d'intégration de la pluie journalière CHIRPS v3.0 aux 142 localités (migration 0055).

Source ``chirps`` (id 18, créée par 0055) et 142 séries
``chirps_precipitation_journalier_<localité>`` dans ``mesures_ressource``,
1991-2025 (12 784 jours), méthode ``modele_satellitaire``, confiance B : CHIRPS
v3.0 final, désagrégation journalière ``rnl`` (ERA5), maille de 0,05° contenant la
localité.

Vérifie la source, les métadonnées, la **fidélité exacte** au CSV gzip committé,
les 121 séries distinctes (mailles de 0,05°), les chiffres du recoupement cités
par la note publique, l'audit par série, les séries de pluie journalières par
source et le recalage de l'identité de ``sources``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds.audit_par_serie import empreinte_fichier
from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.pluie_chirps_civ import (
    CONTRAT_PLUIE_CHIRPS,
    LOT_PLUIE_CHIRPS,
    maille_chirps,
)
from tests.integration.db.journalier_csv import (
    agregats_base,
    agregats_csv,
    entrees_audit_par_serie,
    lignes_auditees_ligne_a_ligne,
)

pytestmark = pytest.mark.integration

_CONTRAT = CONTRAT_PLUIE_CHIRPS
_POINTS = points_nationaux()
_LOCALITES = sorted(code for code, _, _, _ in _POINTS)
_DEBUT, _FIN = date(1991, 1, 1), date(2025, 12, 31)
_NB_JOURS = 12_784
_REVISION = "0055"


def _codes() -> list[str]:
    return [_CONTRAT.code_serie(code) for code in _LOCALITES]


def test_source(db_session: Session) -> None:
    """Source ``chirps`` à id figé 18 : identité, DOI, licence, notes sourcées."""
    r = db_session.execute(
        text(
            """
            SELECT id, code, titre, auteurs, organisation, type_source, annee_publication,
                   date_consultation, url, doi, fiabilite, langue, metadonnees, notes, actif
            FROM sources WHERE code = 'chirps'
            """
        )
    ).one()
    assert (r.id, r.type_source, r.fiabilite, r.langue, r.actif) == (
        18,
        "base_donnees",
        "haute",
        "en",
        True,
    )
    assert (r.doi, r.annee_publication, r.date_consultation) == (
        "10.15780/G2JQ0P",
        2025,
        date(2026, 10, 28),
    )
    assert r.auteurs == ["Funk, C.", "Peterson, P.", "Harrison, L."]
    assert "CHIRPS v3.0" in r.titre and "rnl" in r.titre
    assert r.metadonnees["produit"] == "final (et non préliminaire)"
    assert "domaine public" in r.metadonnees["licence"]
    assert "Attribution 4.0" in r.metadonnees["licence"]
    for fragment in (
        "pas un produit indépendant",
        "proportions journalières d'ERA5",
        "faux épisodes",
        "10.15780/G2JQ0P",
        "10.1038/s41597-026-07096-4",
    ):
        assert fragment in r.notes, fragment


def test_series_metadonnees(db_session: Session) -> None:
    """142 séries : source, méthode, période, unité, libellé et note."""
    rows = db_session.execute(
        text(
            """
            SELECT s.code, s.libelle, s.grandeur_code, s.methode_collecte, s.granularite,
                   s.periode_debut, s.periode_fin, s.note_publique, src.code AS source,
                   loc.code AS localite, loc.nom, u.code AS unite
            FROM series_metadonnees s
            JOIN sources src ON src.id = s.source_id
            JOIN localites loc ON loc.id = s.localite_id
            JOIN grandeurs_referentiel g ON g.code = s.grandeur_code
            JOIN unites u ON u.id = g.unite_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": _codes()},
    ).all()
    assert sorted(r.localite for r in rows) == _LOCALITES
    for r in rows:
        assert (r.source, r.grandeur_code, r.unite) == ("chirps", "precipitation", "mm_par_jour")
        assert (r.methode_collecte, r.granularite) == ("modele_satellitaire", "journalier")
        assert (r.periode_debut, r.periode_fin) == (_DEBUT, _FIN)
        assert r.libelle == f"Précipitations journalier CHIRPS v3 — {r.nom} (1991-2025)"
        assert "maille de 0,05° contenant la localité" in r.note_publique
        assert "désagrégation rnl" in r.note_publique and "ADR-0036" in r.note_publique
        assert "sauf en février 2000 où 5 mailles diffèrent" in r.note_publique
    assert len({r.note_publique for r in rows}) == 1


def test_mesures_fideles_au_csv(db_session: Session) -> None:
    """Par série : agrégats exacts base = CSV ; aucune lacune ; bornes du contrat."""
    attendu, lacunes = agregats_csv(
        _CONTRAT.nom_fichier(LOT_PLUIE_CHIRPS), _CONTRAT.prefixe_code, _DEBUT
    )
    assert not lacunes and sorted(attendu) == sorted(_codes())
    assert {(n, p, d) for n, p, d, _, _ in attendu.values()} == {(_NB_JOURS, _DEBUT, _FIN)}
    base = agregats_base(db_session, _codes(), _DEBUT)
    assert [c for c in _codes() if attendu[c] != base.get(c)] == []
    r = db_session.execute(
        text(
            """
            SELECT COUNT(*) AS n, MIN(m.valeur) AS mini, MAX(m.valeur) AS maxi
            FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": _codes()},
    ).one()
    assert r.n == 142 * _NB_JOURS
    assert 0.0 <= r.mini <= r.maxi <= _CONTRAT.borne_max


def test_une_serie_par_maille(db_session: Session) -> None:
    """121 séries distinctes : les localités d'une même maille de 0,05° partagent leurs valeurs."""
    base = agregats_base(db_session, _codes(), _DEBUT)
    par_maille: dict[tuple[int, int], set[object]] = {}
    for code, _, lat, lon in _POINTS:
        par_maille.setdefault(maille_chirps(lat, lon), set()).add(base[_CONTRAT.code_serie(code)])
    assert len(par_maille) == 121 and all(len(v) == 1 for v in par_maille.values())
    assert len(set(base.values())) == 121


def test_audit_par_serie(db_session: Session) -> None:
    """Une entrée d'audit par série (``I``, révision 0055) ; aucune entrée ligne à ligne."""
    ids = {
        r.code: r.id
        for r in db_session.execute(
            text("SELECT code, id FROM series_metadonnees WHERE code = ANY(:c)"), {"c": _codes()}
        )
    }
    assert len(ids) == 142
    entrees = entrees_audit_par_serie(db_session, list(ids.values()))
    fichier = _CONTRAT.nom_fichier(LOT_PLUIE_CHIRPS)
    empreinte = empreinte_fichier(_CONTRAT, LOT_PLUIE_CHIRPS)
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


def test_pluies_journalieres_par_source(db_session: Session) -> None:
    """Quatre sources de pluie journalière aux 142 localités ; identité des sources recalée."""
    rows = db_session.execute(
        text(
            """
            SELECT src.code AS source, COUNT(*) AS series, COUNT(DISTINCT s.localite_id) AS loc
            FROM series_metadonnees s JOIN sources src ON src.id = s.source_id
            WHERE s.grandeur_code = 'precipitation' AND s.granularite = 'journalier'
            GROUP BY src.code
            """
        )
    ).all()
    assert {r.source: (r.series, r.loc) for r in rows} == {
        "nasa_power": (142, 142),
        "ecmwf_era5": (142, 142),
        "gpm_imerg": (142, 142),
        "chirps": (142, 142),
    }
    seq = db_session.execute(
        text("SELECT last_value, (SELECT MAX(id) FROM sources) AS maxi FROM sources_id_seq")
    ).one()
    assert seq.last_value >= seq.maxi == 18


def test_recoupement_cite_par_la_note(db_session: Session) -> None:
    """Chiffres du recoupement cités par la note publique, recalculés en base.

    Aux 25 jours-localités où NASA dépasse 200 mm : CHIRPS au plus 21,2 mm le jour
    même et 54,8 mm sur trois jours ; jours-localités > 50 mm par an : 89,8
    (1991-2015) puis 111,0 (2017-2025).
    """
    r = db_session.execute(
        text(
            """
            WITH c AS (
                SELECT s.localite_id, m.instant_mesure AS jour, m.valeur::numeric AS v
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:chirps)
            ), n AS (
                SELECT s.localite_id, m.instant_mesure AS jour, m.valeur::numeric AS v
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code LIKE 'nasa_power_precipitation_journalier_%'
                  AND m.valide_au IS NULL
            ), extremes AS (
                SELECT n.localite_id, n.jour,
                       MAX(c.v) FILTER (WHERE c.jour = n.jour) AS jour_meme,
                       SUM(c.v) AS trois_jours
                FROM n JOIN c ON c.localite_id = n.localite_id
                             AND c.jour BETWEEN n.jour - 1 AND n.jour + 1
                WHERE n.v > 200
                GROUP BY n.localite_id, n.jour
            )
            SELECT (SELECT COUNT(*) FROM extremes) AS jours,
                   (SELECT MAX(jour_meme) FROM extremes) AS jour_max,
                   (SELECT MAX(trois_jours) FROM extremes) AS trois_max,
                   (SELECT COUNT(*) FROM c WHERE v > 50 AND jour < '2016-01-01') AS avant,
                   (SELECT COUNT(*) FROM c WHERE v > 50 AND jour >= '2017-01-01') AS apres
            """
        ),
        {"chirps": _codes()},
    ).one()
    assert r.jours == 25
    assert (round(r.jour_max, 1), round(r.trois_max, 1)) == (Decimal("21.2"), Decimal("54.8"))
    par_an = [round(Decimal(x) / annees, 1) for x, annees in ((r.avant, 25), (r.apres, 9))]
    assert par_an == [Decimal("89.8"), Decimal("111.0")]
