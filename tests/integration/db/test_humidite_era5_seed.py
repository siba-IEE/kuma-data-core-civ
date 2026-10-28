"""Tests d'intégration de l'humidité relative ERA5, journalière et mensuelle (migration 0057).

284 séries ``ecmwf_era5_rh2m_<journalier|mensuel>_<localité>`` : 142 dans
``mesures_ressource`` (1991-2025, 12 784 jours) et 142 dans
``mesures_ressource_mensuelles`` (420 mois), source ``ecmwf_era5`` (id 2),
méthode ``reanalyse``, confiance B, en % : moyenne des humidités horaires ERA5
calculées depuis la température et le point de rosée au nœud 0,25° le plus proche.

Vérifie les métadonnées, la **fidélité exacte** aux CSV gzip committés, les 110
séries distinctes (une par nœud), la cohérence du mois avec ses jours, les
chiffres de la comparaison avec NASA POWER cités par les notes publiques et
l'audit (par série pour le journalier, ligne à ligne pour le mensuel).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds.audit_par_serie import empreinte_fichier
from kuma_data_core.db.seeds.humidite_era5_civ import (
    CONTRAT_HUMIDITE_ERA5_JOURNALIER,
    CONTRAT_HUMIDITE_ERA5_MENSUEL,
    LOT_HUMIDITE_ERA5,
)
from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.meteo_era5_civ import maille_era5
from kuma_data_core.db.seeds.series_csv import lire_series
from tests.integration.db.journalier_csv import (
    agregats_base,
    agregats_csv,
    entrees_audit_par_serie,
    lignes_auditees_ligne_a_ligne,
)

pytestmark = pytest.mark.integration

_POINTS = points_nationaux()
_LOCALITES = sorted(code for code, _, _, _ in _POINTS)
_DEBUT, _FIN = date(1991, 1, 1), date(2025, 12, 31)
_NB_JOURS = 12_784
_NB_MOIS = 420
_REVISION = "0057"
_CONTRATS = {
    "journalier": CONTRAT_HUMIDITE_ERA5_JOURNALIER,
    "mensuel": CONTRAT_HUMIDITE_ERA5_MENSUEL,
}


def _codes(granularite: str) -> list[str]:
    return [_CONTRATS[granularite].code_serie(code) for code in _LOCALITES]


@pytest.mark.parametrize("granularite", _CONTRATS)
def test_series_metadonnees(db_session: Session, granularite: str) -> None:
    """142 séries par granularité : source, méthode, période, unité, libellé et note."""
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
        {"c": _codes(granularite)},
    ).all()
    assert sorted(r.localite for r in rows) == _LOCALITES
    for r in rows:
        assert (r.source, r.source_id, r.grandeur_code, r.actif) == ("ecmwf_era5", 2, "rh2m", True)
        assert (r.methode_collecte, r.granularite) == ("reanalyse", granularite)
        assert (r.periode_debut, r.periode_fin, r.unite) == (_DEBUT, _FIN, "pourcent")
        assert r.libelle == (
            f"Humidité relative à 2 m {granularite} ERA5 (CDS) — {r.nom} (1991-2025)"
        )
        for fragment in (
            "formule d'ECMWF, pression de vapeur saturante de Tetens sur l'eau",
            "Point de grille 0,25° le plus proche",
            "Copernicus Climate Change Service",
            "ADR-0021, ADR-0038",
        ):
            assert fragment in r.note_publique, fragment
    assert len({r.note_publique for r in rows}) == 1


def test_journalier_fidele_au_csv(db_session: Session) -> None:
    """Par série : nombre, bornes, Σ valeur et Σ rang * valeur exacts, base = CSV."""
    contrat = CONTRAT_HUMIDITE_ERA5_JOURNALIER
    attendu, lacunes = agregats_csv(
        contrat.nom_fichier(LOT_HUMIDITE_ERA5), contrat.prefixe_code, _DEBUT
    )
    assert not lacunes and sorted(attendu) == sorted(_codes("journalier"))
    assert {(n, p, d) for n, p, d, _, _ in attendu.values()} == {(_NB_JOURS, _DEBUT, _FIN)}
    base = agregats_base(db_session, _codes("journalier"), _DEBUT)
    assert [c for c in _codes("journalier") if attendu[c] != base.get(c)] == []
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
        {"c": _codes("journalier")},
    ).one()
    assert (r.n, r.hors_contrat) == (142 * _NB_JOURS, 0)
    assert 0.0 < r.mini <= r.maxi <= 100.0


def test_mensuel_fidele_au_csv(db_session: Session) -> None:
    """Chaque mesure mensuelle = CSV committé ; brut, confiance B, courante."""
    attendu = {
        (s["code"], a, m): v
        for s in lire_series(CONTRAT_HUMIDITE_ERA5_MENSUEL, LOT_HUMIDITE_ERA5)
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
        {"c": _codes("mensuel")},
    ).all()
    assert len(rows) == len(attendu) == 142 * _NB_MOIS
    for r in rows:
        assert r.valeur == attendu[(r.code, r.annee, r.mois)], (r.code, r.annee, r.mois)
        assert (r.statut, r.niveau_confiance_derive, r.valide_au) == ("brut", "B", None)


def test_une_serie_distincte_par_noeud(db_session: Session) -> None:
    """110 séries distinctes : les localités d'un même nœud 0,25° partagent leurs valeurs."""
    base = agregats_base(db_session, _codes("journalier"), _DEBUT)
    par_noeud: dict[tuple[float, float], set[object]] = {}
    for code, _, lat, lon in _POINTS:
        par_noeud.setdefault(maille_era5(lat, lon), set()).add(
            base[CONTRAT_HUMIDITE_ERA5_JOURNALIER.code_serie(code)]
        )
    assert len(par_noeud) == 110
    assert all(len(v) == 1 for v in par_noeud.values())
    assert len(set(base.values())) == 110


def test_mois_egal_a_la_moyenne_de_ses_jours(db_session: Session) -> None:
    """Moyenne des jours gravés du mois - mois gravé : arrondi à 4 décimales près."""
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
        {"j": _codes("journalier"), "m": _codes("mensuel")},
    ).one()
    assert r.n == 142 * _NB_MOIS
    assert r.maxi <= Decimal("0.0001")


@pytest.mark.parametrize(
    ("granularite", "moyen_era5", "moyen_nasa", "plus_bas", "plus_haut"),
    [
        ("journalier", "76.42", "74.90", ("civ_dep_duekoue", "-2.85"), ("civ_dep_touba", "5.66")),
        ("mensuel", "76.37", "74.83", ("civ_dep_duekoue", "-2.87"), ("civ_dep_touba", "5.71")),
    ],
)
def test_comparaison_nasa_citee(
    db_session: Session,
    granularite: str,
    moyen_era5: str,
    moyen_nasa: str,
    plus_bas: tuple[str, str],
    plus_haut: tuple[str, str],
) -> None:
    """ERA5 - NASA POWER aux 142 localités, 1991-2025 : chiffres des notes publiques."""
    table, instant = (
        ("mesures_ressource", "m.instant_mesure")
        if granularite == "journalier"
        else ("mesures_ressource_mensuelles", "make_date(m.annee, m.mois, 1)")
    )
    rows = db_session.execute(
        text(
            f"""
            WITH e AS (
                SELECT s.localite_id, {instant} AS t, m.valeur::numeric AS v
                FROM {table} m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:era5) AND m.valide_au IS NULL
            ), n AS (
                SELECT s.localite_id, {instant} AS t, m.valeur::numeric AS v
                FROM {table} m JOIN series_metadonnees s ON s.id = m.serie_id
                JOIN sources src ON src.id = s.source_id AND src.code = 'nasa_power'
                WHERE s.grandeur_code = 'rh2m' AND s.granularite = :g AND m.valide_au IS NULL
            )
            SELECT l.code, COUNT(*) AS n, AVG(e.v) AS era5, AVG(n.v) AS nasa,
                   AVG(e.v - n.v) AS ecart
            FROM e JOIN n USING (localite_id, t) JOIN localites l ON l.id = e.localite_id
            GROUP BY l.code
            """
        ),
        {"era5": _codes(granularite), "g": granularite},
    ).all()
    attendu = _NB_JOURS if granularite == "journalier" else _NB_MOIS
    assert len(rows) == 142 and {r.n for r in rows} == {attendu}
    assert round(sum(r.era5 for r in rows) / 142, 2) == Decimal(moyen_era5)
    assert round(sum(r.nasa for r in rows) / 142, 2) == Decimal(moyen_nasa)
    bas = min(rows, key=lambda r: r.ecart)
    haut = max(rows, key=lambda r: r.ecart)
    assert (bas.code, round(bas.ecart, 2)) == (plus_bas[0], Decimal(plus_bas[1]))
    assert (haut.code, round(haut.ecart, 2)) == (plus_haut[0], Decimal(plus_haut[1]))


def test_saisons_et_ecart_absolu_cites(db_session: Session) -> None:
    """ERA5 - NASA journalier : décembre-février, juin-août et écart absolu moyen des notes."""
    r = db_session.execute(
        text(
            """
            WITH e AS (
                SELECT s.localite_id, m.instant_mesure AS t, m.valeur::numeric AS v
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:era5)
            ), n AS (
                SELECT s.localite_id, m.instant_mesure AS t, m.valeur::numeric AS v
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                JOIN sources src ON src.id = s.source_id AND src.code = 'nasa_power'
                WHERE s.grandeur_code = 'rh2m' AND s.granularite = 'journalier'
                  AND m.valide_au IS NULL
            )
            SELECT AVG(e.v - n.v) FILTER (WHERE EXTRACT(MONTH FROM e.t) IN (12, 1, 2)) AS djf,
                   AVG(e.v - n.v) FILTER (WHERE EXTRACT(MONTH FROM e.t) IN (6, 7, 8)) AS jja,
                   AVG(ABS(e.v - n.v)) AS absolu
            FROM e JOIN n USING (localite_id, t)
            """
        ),
        {"era5": _codes("journalier")},
    ).one()
    assert (round(r.djf, 2), round(r.jja, 2), round(r.absolu, 2)) == (
        Decimal("5.03"),
        Decimal("-0.29"),
        Decimal("6.04"),
    )


def test_audit(db_session: Session) -> None:
    """Journalier : une entrée d'audit par série (``I``, 0057) ; mensuel : ligne à ligne."""
    contrat = CONTRAT_HUMIDITE_ERA5_JOURNALIER
    ids = dict(
        db_session.execute(
            text("SELECT code, id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": _codes("journalier")},
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
            "fichier": contrat.nom_fichier(LOT_HUMIDITE_ERA5),
            "sha256": empreinte_fichier(contrat, LOT_HUMIDITE_ERA5),
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
        {"c": _codes("mensuel")},
    ).scalar_one()
    assert n == 142 * _NB_MOIS


def test_degenerescence_de_pixel(db_session: Session) -> None:
    """Une ligne par série mensuelle (ADR-0027), mêmes jumeaux que la température ERA5."""
    rows = db_session.execute(
        text(
            """
            SELECT l.code, h.valeur AS humidite, t.valeur AS temperature
            FROM grandeurs_metier h
            JOIN series_metadonnees sh ON sh.id = h.series_metadonnees_id
            JOIN localites l ON l.id = sh.localite_id
            JOIN series_metadonnees st ON st.code = 'ecmwf_era5_t2m_mensuel_' || l.code
            JOIN grandeurs_metier t
                ON t.series_metadonnees_id = st.id AND t.grandeur_code = h.grandeur_code
            WHERE h.grandeur_code = 'degenerescence_pixel' AND sh.code = ANY(:c)
              AND h.valide_au IS NULL AND t.valide_au IS NULL
            """
        ),
        {"c": _codes("mensuel")},
    ).all()
    assert len(rows) == 142
    assert all(r.humidite == r.temperature for r in rows)
    comptes = {v: sum(r.humidite == v for r in rows) for v in (0.0, 1.0, 2.0)}
    assert comptes == {0.0: 82, 1.0: 48, 2.0: 12}  # 82 + 48 / 2 + 12 / 3 = 110 nœuds


def test_deux_sources_d_humidite(db_session: Session) -> None:
    """Humidité relative : NASA POWER et ERA5, mensuel et journalier, 142 localités chacune."""
    rows = db_session.execute(
        text(
            """
            SELECT src.code AS source, s.granularite, COUNT(*) AS n,
                   COUNT(DISTINCT s.localite_id) AS loc
            FROM series_metadonnees s JOIN sources src ON src.id = s.source_id
            WHERE s.grandeur_code = 'rh2m'
            GROUP BY 1, 2
            """
        )
    ).all()
    assert {(r.source, r.granularite): (r.n, r.loc) for r in rows} == {
        ("nasa_power", "mensuel"): (142, 142),
        ("nasa_power", "journalier"): (142, 142),
        ("ecmwf_era5", "mensuel"): (142, 142),
        ("ecmwf_era5", "journalier"): (142, 142),
    }
