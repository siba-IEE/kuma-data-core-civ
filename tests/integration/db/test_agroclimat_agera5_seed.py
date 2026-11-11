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
from kuma_data_core.db.seeds.meteo_era5_journaliere_civ import CONTRATS_METEO_ERA5_JOURNALIERS
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


# Chiffres cités par les notes publiques, journalier 1991-2025 : moyenne des 142 localités,
# localités extrêmes (Sassandra et la région du Gbôklé partagent leur maille), mois le plus bas
# et le plus haut (moyenne de tous les jours-localités du mois).
_Extreme = tuple[set[str], str]
_CITES: dict[str, tuple[str, _Extreme, _Extreme, tuple[int, str], tuple[int, str]]] = {
    "et0": (
        "4.02",
        ({"civ_dep_san_pedro"}, "3.38"),
        ({"civ_dep_doropo"}, "5.29"),
        (8, "3.26"),
        (2, "4.85"),
    ),
    "t2m_min": (
        "22.36",
        ({"civ_dep_biankouma"}, "19.93"),
        ({"civ_dep_jacqueville"}, "25.39"),
        (12, "21.28"),
        (4, "23.63"),
    ),
    "t2m_max": (
        "30.67",
        ({"civ_dep_sassandra", "civ_gbokle"}, "26.71"),
        ({"civ_dep_m_bengue"}, "33.17"),
        (8, "27.67"),
        (2, "33.53"),
    ),
    "vpd_tmax": (
        "1.99",
        ({"civ_dep_jacqueville"}, "0.64"),
        ({"civ_dep_tengrela"}, "3.15"),
        (8, "1.25"),
        (2, "3.01"),
    ),
}


_MOIS = {2: "février", 4: "avril", 8: "août", 12: "décembre"}


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_notes_citent_les_chiffres(db_session: Session, grandeur: str) -> None:
    """Les notes journalière et mensuelle citent les chiffres vérifiés plus bas."""
    moyenne, (_, bas), (_, haut), (m_bas, v_bas), (m_haut, v_haut) = _CITES[grandeur]
    notes = (
        db_session.execute(
            text("SELECT DISTINCT note_publique FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": _codes(grandeur, "journalier") + _codes(grandeur, "mensuel")},
        )
        .scalars()
        .all()
    )
    assert len(notes) == 2
    fragments = [
        f"{moyenne.replace('.', ',')} ",
        f"de {bas.replace('.', ',')} à ",
        f"à {haut.replace('.', ',')} à ",
        f"{v_bas.replace('.', ',')} en {_MOIS[m_bas]}",
        f"{v_haut.replace('.', ',')} en {_MOIS[m_haut]}",
    ]
    for note in notes:
        for fragment in fragments:
            assert fragment in note, fragment
        if grandeur in ("t2m_min", "t2m_max"):
            assert "99,82 %" in note and "0,13 °C" in note and "(0,41 " in note
        if grandeur == "et0":
            assert "4,19 mm/jour" in note and "corrélée à 0,75" in note


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_moyennes_et_extremes_cites(db_session: Session, grandeur: str) -> None:
    """Journalier 1991-2025 : moyenne, localités et mois extrêmes cités par les notes."""
    moyenne, plus_basse, plus_haute, mois_bas, mois_haut = _CITES[grandeur]
    par_localite = db_session.execute(
        text(
            """
            SELECT l.code, COUNT(*) AS n, AVG(m.valeur::numeric) AS v
            FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
            JOIN localites l ON l.id = s.localite_id
            WHERE s.code = ANY(:c) GROUP BY l.code
            """
        ),
        {"c": _codes(grandeur, "journalier")},
    ).all()
    assert len(par_localite) == 142 and {r.n for r in par_localite} == {_NB_JOURS}
    assert round(sum(r.v for r in par_localite) / 142, 2) == Decimal(moyenne)
    for extreme, (codes, valeur) in (
        (min(r.v for r in par_localite), plus_basse),
        (max(r.v for r in par_localite), plus_haute),
    ):
        assert {r.code for r in par_localite if r.v == extreme} == codes
        assert round(extreme, 2) == Decimal(valeur)
    par_mois = db_session.execute(
        text(
            """
            SELECT EXTRACT(MONTH FROM m.instant_mesure)::int AS mois, AVG(m.valeur::numeric) AS v
            FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c) GROUP BY 1
            """
        ),
        {"c": _codes(grandeur, "journalier")},
    ).all()
    bas = min(par_mois, key=lambda r: r.v)
    haut = max(par_mois, key=lambda r: r.v)
    assert (bas.mois, round(bas.v, 2)) == (mois_bas[0], Decimal(mois_bas[1]))
    assert (haut.mois, round(haut.v, 2)) == (mois_haut[0], Decimal(mois_haut[1]))


def test_temperature_moyenne_era5_entre_tmin_et_tmax(db_session: Session) -> None:
    """La température moyenne journalière ERA5 (0053) face à Tmin et Tmax AgERA5."""
    r = db_session.execute(
        text(
            """
            WITH j AS (
                SELECT s.localite_id, m.instant_mesure AS t, s.grandeur_code AS g,
                       m.valeur::numeric AS v
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:c) AND m.valide_au IS NULL
            ), p AS (
                SELECT localite_id, t,
                       MAX(v) FILTER (WHERE g = 't2m_min') AS tmin,
                       MAX(v) FILTER (WHERE g = 't2m_max') AS tmax,
                       MAX(v) FILTER (WHERE g = 't2m') AS era5
                FROM j GROUP BY 1, 2
            )
            SELECT COUNT(*) AS n,
                   AVG((era5 BETWEEN tmin AND tmax)::int) AS dedans,
                   AVG((tmin + tmax) / 2 - era5) AS biais,
                   AVG(ABS((tmin + tmax) / 2 - era5)) AS absolu
            FROM p
            """
        ),
        {
            "c": _codes("t2m_min", "journalier")
            + _codes("t2m_max", "journalier")
            + [CONTRATS_METEO_ERA5_JOURNALIERS["t2m"].code_serie(c) for c in _LOCALITES]
        },
    ).one()
    assert r.n == 142 * _NB_JOURS
    assert (round(100 * r.dedans, 2), round(r.biais, 2), round(r.absolu, 2)) == (
        Decimal("99.82"),
        Decimal("0.13"),
        Decimal("0.41"),
    )


def test_hargreaves_cite(db_session: Session) -> None:
    """ET0 AgERA5 face à Hargreaves (FAO-56, éq. 52) sur Tmin, Tmax et Ra (éq. 21 à 25)."""
    r = db_session.execute(
        text(
            """
            WITH j AS (
                SELECT s.localite_id, m.instant_mesure AS t, s.grandeur_code AS g,
                       m.valeur::float8 AS v
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:c)
            ), p AS (
                SELECT l.latitude::float8 AS lat, EXTRACT(DOY FROM j.t) AS jour,
                       MAX(v) FILTER (WHERE g = 'et0') AS et0,
                       MAX(v) FILTER (WHERE g = 't2m_min') AS tmin,
                       MAX(v) FILTER (WHERE g = 't2m_max') AS tmax
                FROM j JOIN localites l ON l.id = j.localite_id GROUP BY l.id, j.t
            ), a AS (
                SELECT *, radians(lat) AS phi,
                       1 + 0.033 * cos(2 * pi() * jour / 365) AS dr,
                       0.409 * sin(2 * pi() * jour / 365 - 1.39) AS delta
                FROM p
            ), r AS (
                SELECT *, acos(-tan(phi) * tan(delta)) AS ws FROM a
            ), h AS (
                SELECT et0,
                       0.0023 * 0.408 * (24 * 60 / pi()) * 0.0820 * dr
                       * (ws * sin(phi) * sin(delta) + cos(phi) * cos(delta) * sin(ws))
                       * ((tmin + tmax) / 2 + 17.8) * sqrt(tmax - tmin) AS hg
                FROM r
            )
            SELECT COUNT(*) AS n, AVG(et0) AS et0, AVG(hg) AS hg, CORR(et0, hg) AS r FROM h
            """
        ),
        {"c": [c for g in ("et0", "t2m_min", "t2m_max") for c in _codes(g, "journalier")]},
    ).one()
    assert r.n == 142 * _NB_JOURS
    assert (round(r.et0, 2), round(r.hg, 2), round(r.r, 2)) == (4.02, 4.19, 0.75)


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
