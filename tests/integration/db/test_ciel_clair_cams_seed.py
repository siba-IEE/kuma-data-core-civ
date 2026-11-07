"""Tests d'intégration du ciel clair, de l'irradiation extraterrestre et de la fiabilité
CAMS Radiation (migration 0058, ADR-0039).

5 grandeurs nouvelles au référentiel, 1 420 séries ``cams_<grandeur>_<journalier|mensuel>_
<localité>`` aux 142 localités, 2005-2025 : 710 dans ``mesures_ressource`` (7 670 jours)
et 710 dans ``mesures_ressource_mensuelles`` (252 mois), source ``cams_radiation`` (id 13),
confiance B.

Vérifie le référentiel, les métadonnées, la **fidélité exacte** aux CSV gzip committés,
l'absence de lacune, la cohérence du mois avec ses jours, les chiffres cités par les notes
publiques (indice de ciel clair, saisons, irradiation extraterrestre, fiabilité), l'audit
et la dégénérescence de pixel.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds.audit_par_serie import empreinte_fichier
from kuma_data_core.db.seeds.ciel_clair_cams_civ import (
    CONTRATS_CIEL_CLAIR_JOURNALIERS,
    CONTRATS_CIEL_CLAIR_MENSUELS,
    GRANDEURS_CIEL_CLAIR,
    LIBELLES,
    LOT_CIEL_CLAIR_CAMS,
)
from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.series_csv import lire_series
from kuma_data_core.services.grandeurs.kt import h0_mensuel
from tests.integration.db.journalier_csv import (
    agregats_base,
    agregats_csv,
    entrees_audit_par_serie,
    lignes_auditees_ligne_a_ligne,
)

pytestmark = pytest.mark.integration

_POINTS = points_nationaux()
_LOCALITES = sorted(code for code, _, _, _ in _POINTS)
_DEBUT, _FIN = date(2005, 1, 1), date(2025, 12, 31)
_NB_JOURS = 7_670
_NB_MOIS = 252
_REVISION = "0058"
_IDS = {
    "ghi_ciel_clair": (42, "kwh_par_m2_jour"),
    "dni_ciel_clair": (43, "kwh_par_m2_jour"),
    "dhi_ciel_clair": (44, "kwh_par_m2_jour"),
    "irradiation_extraterrestre": (45, "kwh_par_m2_jour"),
    "fiabilite_satellite": (46, "sans_unite"),
}
_CONTRATS = {"journalier": CONTRATS_CIEL_CLAIR_JOURNALIERS, "mensuel": CONTRATS_CIEL_CLAIR_MENSUELS}
_CAS = [(g, gr) for gr in _CONTRATS for g in GRANDEURS_CIEL_CLAIR]


def _codes(grandeur: str, granularite: str) -> list[str]:
    return [_CONTRATS[granularite][grandeur].code_serie(code) for code in _LOCALITES]


def _mensuel(db_session: Session, prefixe: str) -> dict[str, dict[tuple[int, int], Decimal]]:
    """Valeurs mensuelles courantes des 142 séries ``<prefixe><localité>``."""
    out: dict[str, dict[tuple[int, int], Decimal]] = defaultdict(dict)
    for r in db_session.execute(
        text(
            """
            SELECT l.code, m.annee, m.mois, m.valeur::numeric AS v
            FROM mesures_ressource_mensuelles m
            JOIN series_metadonnees s ON s.id = m.serie_id
            JOIN localites l ON l.id = s.localite_id
            WHERE s.code = ANY(:c) AND m.valide_au IS NULL
            """
        ),
        {"c": [prefixe + code for code in _LOCALITES]},
    ):
        out[r.code][(r.annee, r.mois)] = r.v
    assert len(out) == 142 and {len(v) for v in out.values()} == {_NB_MOIS}
    return out


def test_grandeurs_referentiel(db_session: Session) -> None:
    """5 grandeurs F1 stockées, unités, libellés, descriptions citant l'ADR-0039."""
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
        assert r.libelle == LIBELLES[r.code]
        assert (r.famille, r.strategie_calcul, r.version_formule_actuelle, r.actif) == (
            "F1",
            "stockee",
            1,
            True,
        )
        assert "ADR-0039" in r.description


@pytest.mark.parametrize(("grandeur", "granularite"), _CAS)
def test_series_metadonnees(db_session: Session, grandeur: str, granularite: str) -> None:
    """142 séries : source, méthode, période, unité, libellé et note."""
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
        assert (r.source, r.grandeur_code, r.actif) == ("cams_radiation", grandeur, True)
        assert (r.methode_collecte, r.granularite) == ("modele_satellitaire", granularite)
        assert (r.periode_debut, r.periode_fin) == (_DEBUT, _FIN)
        assert r.libelle == (
            f"{LIBELLES[grandeur]} {granularite} CAMS Radiation — {r.nom} (2005-2025)"
        )
        for fragment in ("service v4.6", "Confiance B (ADR-0011, ADR-0039)", "(CAMS), 2026."):
            assert fragment in r.note_publique, fragment
    assert len({r.note_publique for r in rows}) == 1


@pytest.mark.parametrize("grandeur", GRANDEURS_CIEL_CLAIR)
def test_journalier_fidele_au_csv(db_session: Session, grandeur: str) -> None:
    """Par série : nombre, bornes, Σ valeur et Σ rang * valeur exacts ; aucune lacune."""
    contrat = CONTRATS_CIEL_CLAIR_JOURNALIERS[grandeur]
    codes = _codes(grandeur, "journalier")
    attendu, lacunes = agregats_csv(
        contrat.nom_fichier(LOT_CIEL_CLAIR_CAMS), contrat.prefixe_code, _DEBUT
    )
    assert not lacunes and sorted(attendu) == sorted(codes)
    assert {(n, p, d) for n, p, d, _, _ in attendu.values()} == {(_NB_JOURS, _DEBUT, _FIN)}
    base = agregats_base(db_session, codes, _DEBUT)
    assert [c for c in codes if attendu[c] != base.get(c)] == []


@pytest.mark.parametrize("grandeur", GRANDEURS_CIEL_CLAIR)
def test_mensuel_fidele_au_csv(db_session: Session, grandeur: str) -> None:
    """Chaque mesure mensuelle = CSV committé ; brut, confiance B, courante."""
    attendu = {
        (s["code"], a, m): v
        for s in lire_series(CONTRATS_CIEL_CLAIR_MENSUELS[grandeur], LOT_CIEL_CLAIR_CAMS)
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


@pytest.mark.parametrize(
    ("grandeur", "tolerance"),
    [
        ("ghi_ciel_clair", "0.0001"),
        ("dni_ciel_clair", "0.0001"),
        ("dhi_ciel_clair", "0.0001"),
        ("irradiation_extraterrestre", "0.0001"),
        ("fiabilite_satellite", "0.016"),
    ],
)
def test_mois_et_moyenne_de_ses_jours(db_session: Session, grandeur: str, tolerance: str) -> None:
    """Moyenne des jours du mois - mois : arrondi près ; fiabilité calculée autrement par CAMS."""
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
    assert r.maxi <= Decimal(tolerance)


def _rapport(
    tous: dict[str, dict[tuple[int, int], Decimal]],
    clair: dict[str, dict[tuple[int, int], Decimal]],
    garder: Callable[[str, int, int], bool] = lambda code, annee, mois: True,
) -> Decimal:
    num = sum(v for c, d in tous.items() for (a, m), v in d.items() if garder(c, a, m))
    den = sum(v for c, d in clair.items() for (a, m), v in d.items() if garder(c, a, m))
    return num / den


def test_indice_de_ciel_clair_cite(db_session: Session) -> None:
    """Tous ciels / ciel clair (mensuel courant) : chiffres des notes publiques."""
    ghi = _mensuel(db_session, "cams_ghi_mensuel_")
    ghi_cc = _mensuel(db_session, "cams_ghi_ciel_clair_mensuel_")
    assert round(_rapport(ghi, ghi_cc), 3) == Decimal("0.809")
    assert round(_rapport(ghi, ghi_cc, lambda c, a, m: m == 1), 2) == Decimal("0.95")
    assert round(_rapport(ghi, ghi_cc, lambda c, a, m: m == 8), 2) == Decimal("0.64")
    par_localite = {c: _rapport({c: ghi[c]}, {c: ghi_cc[c]}) for c in _LOCALITES}
    bas = min(par_localite, key=par_localite.__getitem__)
    haut = max(par_localite, key=par_localite.__getitem__)
    assert (bas, round(par_localite[bas], 3)) == ("civ_dep_abidjan", Decimal("0.706"))
    assert (haut, round(par_localite[haut], 3)) == ("civ_dep_tengrela", Decimal("0.879"))
    assert all(ghi[c][k] <= ghi_cc[c][k] for c in _LOCALITES for k in ghi[c])

    dni = _mensuel(db_session, "cams_dni_mensuel_")
    dni_cc = _mensuel(db_session, "cams_dni_ciel_clair_mensuel_")
    assert round(_rapport(dni, dni_cc), 3) == Decimal("0.616")
    assert round(_rapport(dni, dni_cc, lambda c, a, m: m == 1), 2) == Decimal("0.88")
    assert round(_rapport(dni, dni_cc, lambda c, a, m: m == 8), 2) == Decimal("0.36")
    saison_seche = [v for d in dni_cc.values() for (a, m), v in d.items() if m in (12, 1, 2)]
    septembre = [v for d in dni_cc.values() for (a, m), v in d.items() if m == 9]
    assert round(sum(saison_seche) / len(saison_seche), 1) == Decimal("5.4")
    assert round(sum(septembre) / len(septembre), 1) == Decimal("7.3")
    toa = _mensuel(db_session, "cams_irradiation_extraterrestre_mensuel_")
    transmission = {
        mois: round(_rapport(dni_cc, toa, lambda c, a, m, mois=mois: m == mois), 2)
        for mois in (2, 3, 9)
    }
    assert transmission == {2: Decimal("0.55"), 3: Decimal("0.53"), 9: Decimal("0.71")}

    dhi = _mensuel(db_session, "cams_dhi_mensuel_")
    dhi_cc = _mensuel(db_session, "cams_dhi_ciel_clair_mensuel_")
    assert round(_rapport(dhi, dhi_cc), 2) == Decimal("1.26")


def test_irradiation_extraterrestre_et_h0_du_kt(db_session: Session) -> None:
    """Irradiation extraterrestre CAMS - H0 de 0041 (Spencer, 1361 W/m²) : 0,44 % au plus."""
    toa = _mensuel(db_session, "cams_irradiation_extraterrestre_mensuel_")
    latitudes = {code: lat for code, _, lat, _ in _POINTS}
    ecarts = [
        (float(v) - h0) / h0 * 100
        for c, d in toa.items()
        for (a, m), v in d.items()
        if (h0 := h0_mensuel(latitudes[c], a, m, constante_solaire=1361.0, modele="spencer"))
    ]
    assert len(ecarts) == 142 * _NB_MOIS
    assert round(sum(ecarts) / len(ecarts), 2) == pytest.approx(0.08)
    assert max(abs(e) for e in ecarts) < 0.44


def test_fiabilite_citee(db_session: Session) -> None:
    """Fiabilité : médiane, jours sous 0,9, jours à images manquantes, bornes mensuelles."""
    r = db_session.execute(
        text(
            """
            SELECT percentile_disc(0.5) WITHIN GROUP (ORDER BY m.valeur) AS mediane,
                   COUNT(*) FILTER (WHERE m.valeur < 0.9) AS sous_09, COUNT(*) AS n
            FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": _codes("fiabilite_satellite", "journalier")},
    ).one()
    assert (round(r.mediane, 3), r.sous_09, r.n) == (0.985, 1_733, 1_089_140)
    lacunes = db_session.execute(
        text(
            """
            SELECT MAX(m.valeur) AS maxi
            FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
              AND m.instant_mesure IN ('2005-01-11', '2005-01-12', '2006-01-10', '2006-01-11')
            """
        ),
        {"c": _codes("fiabilite_satellite", "journalier")},
    ).scalar_one()
    assert round(lacunes, 2) == 0.52
    mois = _mensuel(db_session, "cams_fiabilite_satellite_mensuel_")
    valeurs = sorted((v, c, a, m) for c, d in mois.items() for (a, m), v in d.items())
    assert valeurs[0] == (Decimal("0.9588"), "civ_dep_bangolo", 2006, 1)
    assert round(valeurs[-1][0], 3) == Decimal("0.989")


def test_audit(db_session: Session) -> None:
    """Journalier : une entrée par série (``I``, 0058) ; mensuel : ligne à ligne."""
    for grandeur, contrat in CONTRATS_CIEL_CLAIR_JOURNALIERS.items():
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
                "fichier": contrat.nom_fichier(LOT_CIEL_CLAIR_CAMS),
                "sha256": empreinte_fichier(contrat, LOT_CIEL_CLAIR_CAMS),
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
        {"c": [c for g in GRANDEURS_CIEL_CLAIR for c in _codes(g, "mensuel")]},
    ).scalar_one()
    assert n == len(GRANDEURS_CIEL_CLAIR) * 142 * _NB_MOIS


def test_degenerescence_de_pixel(db_session: Session) -> None:
    """Une ligne par série mensuelle (ADR-0027) ; 126 points distincts, comme le tous ciels."""
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
        {"c": [c for g in GRANDEURS_CIEL_CLAIR for c in _codes(g, "mensuel")]},
    ).all()
    assert {r.grandeur_code: (r.n, round(r.distinctes)) for r in rows} == dict.fromkeys(
        GRANDEURS_CIEL_CLAIR, (142, 126)
    )
