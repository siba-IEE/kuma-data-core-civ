"""Tests d'intégration des particules PM2.5 et PM10 CAMS EAC4 (migration 0037, ADR-0022).

Mensuel aux 142 localités (``mesures_ressource_mensuelles``) et journalier aux 34
localités du lot ``pilotes_regions`` (``mesures_ressource``), 2003-2025. Vérifie
les métadonnées et l'unité au référentiel, la complétude (calendrier recalculé
indépendamment), la **fidélité intégrale** aux CSV gzip committés, les bornes,
la cohérence PM2.5 <= PM10, la cohérence journalier <-> mensuel (moyenne des
jours recalculée en base) et la compatibilité avec les résolveurs de séries PM
de l'API (proxy de salissure, PR réaliste).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds.aerosols_civ import (
    CONTRATS_EAC4_JOURNALIERS,
    CONTRATS_EAC4_MENSUELS,
    LOT_AEROSOLS_JOURNALIER,
    LOT_AEROSOLS_MENSUEL,
)
from kuma_data_core.db.seeds.lots_civ import points_journalier, points_nationaux
from kuma_data_core.db.seeds.series_csv import ContratSerie, lire_series, lire_series_journalieres

pytestmark = pytest.mark.integration

_MENSUELLES = {code for code, _, _, _ in points_nationaux()}
_JOURNALIERES = {code for code, _, _, _ in points_journalier()}
_CONTRATS = [*CONTRATS_EAC4_MENSUELS.values(), *CONTRATS_EAC4_JOURNALIERS.values()]

# Calendrier recalculé indépendamment des contrats : 2003-01 → 2025-12.
_MOIS = [(a, m) for a in range(2003, 2026) for m in range(1, 13)]
_JOURS = [
    date(2003, 1, 1) + timedelta(days=i) for i in range((date(2026, 1, 1) - date(2003, 1, 1)).days)
]

# Écart toléré entre le mensuel servi et la moyenne des jours gravés (µg/m³) :
# arrondi à 4 décimales des deux CSV et codage des champs de la source (écart
# mesuré : 3,3·10⁻⁴ au plus). Seul mars 2024 s'en écarte, côté source : le
# produit mensuel n'y est pas la moyenne des analyses 3-horaires servies (ADR-0022).
_TOLERANCE_MENSUEL_UG: float = 1e-3
_MOIS_INCOHERENT_SOURCE: tuple[int, int] = (2024, 3)


def _journalier(contrat: ContratSerie) -> bool:
    return contrat.granularite == "journalier"


def _localites(contrat: ContratSerie) -> set[str]:
    return _JOURNALIERES if _journalier(contrat) else _MENSUELLES


def _codes(contrat: ContratSerie) -> list[str]:
    return sorted(contrat.code_serie(code) for code in _localites(contrat))


def _id(contrat: ContratSerie) -> str:
    return contrat.prefixe_code


def test_perimetres() -> None:
    """142 localités au mensuel, 34 au journalier (incluses) ; 276 mois et 8401 jours."""
    assert len(_MENSUELLES) == 142 and len(_JOURNALIERES) == 34
    assert _JOURNALIERES <= _MENSUELLES
    assert len(_MOIS) == 276 and len(_JOURS) == 8401


def test_source_grandeurs_et_unite(db_session: Session) -> None:
    """Source ``cams_eac4`` (id 15) ; PM2.5 et PM10 en µg/m³ au référentiel."""
    assert (
        db_session.execute(text("SELECT code FROM sources WHERE id = 15")).scalar_one()
        == "cams_eac4"
    )
    rows = db_session.execute(
        text(
            """
            SELECT g.code, u.code AS unite, u.symbole FROM grandeurs_referentiel g
            JOIN unites u ON u.id = g.unite_id WHERE g.code IN ('pm2_5', 'pm10')
            """
        )
    ).all()
    assert {r.code: r.unite for r in rows} == {
        "pm2_5": "microgramme_par_metre_cube",
        "pm10": "microgramme_par_metre_cube",
    }
    assert {r.symbole for r in rows} == {"µg/m³"}


@pytest.mark.parametrize("contrat", _CONTRATS, ids=_id)
def test_series(db_session: Session, contrat: ContratSerie) -> None:
    """Une série par localité du lot, et aucune autre série PM EAC4 de même granularité."""
    rows = db_session.execute(
        text(
            """
            SELECT s.code, loc.code AS localite, s.grandeur_code, s.granularite,
                   s.methode_collecte, s.periode_debut, s.periode_fin, s.libelle,
                   s.note_publique, s.actif, src.code AS source
            FROM series_metadonnees s
            JOIN sources src ON src.id = s.source_id
            JOIN localites loc ON loc.id = s.localite_id
            WHERE src.code = 'cams_eac4' AND s.grandeur_code = :g AND s.granularite = :gr
            """
        ),
        {"g": contrat.grandeur_code, "gr": contrat.granularite},
    ).all()
    assert sorted(r.code for r in rows) == _codes(contrat)
    assert {r.localite for r in rows} == _localites(contrat)
    for r in rows:
        assert r.code == contrat.code_serie(r.localite)
        assert r.methode_collecte == "reanalyse" and r.actif
        assert (r.periode_debut, r.periode_fin) == (date(2003, 1, 1), date(2025, 12, 31))
        assert r.libelle.startswith(
            f"{'PM2.5' if contrat.grandeur_code == 'pm2_5' else 'PM10'} {contrat.granularite} "
            "CAMS EAC4 — "
        )
        assert r.libelle.endswith(" (2003-2025)")
        assert "ADR-0022" in r.note_publique and "µg/m³" in r.note_publique
        assert "Confiance B." in r.note_publique


@pytest.mark.parametrize("contrat", _CONTRATS, ids=_id)
def test_completude(db_session: Session, contrat: ContratSerie) -> None:
    """Chaque série a toute la période, sans doublon (comptes recalculés en base)."""
    if _journalier(contrat):
        requete = """
            SELECT s.code, COUNT(*) AS n, COUNT(DISTINCT m.instant_mesure) AS distincts,
                   MIN(m.instant_mesure) AS premier, MAX(m.instant_mesure) AS dernier
            FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c) AND m.valide_au IS NULL GROUP BY s.code
        """
        attendu = (len(_JOURS), len(_JOURS), _JOURS[0], _JOURS[-1])
    else:
        requete = """
            SELECT s.code, COUNT(*) AS n, COUNT(DISTINCT (m.annee, m.mois)) AS distincts,
                   MIN(m.annee * 100 + m.mois) AS premier, MAX(m.annee * 100 + m.mois) AS dernier
            FROM mesures_ressource_mensuelles m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c) AND m.valide_au IS NULL GROUP BY s.code
        """
        attendu = (len(_MOIS), len(_MOIS), 200301, 202512)
    rows = db_session.execute(text(requete), {"c": _codes(contrat)}).all()
    assert sorted(r.code for r in rows) == _codes(contrat)
    for r in rows:
        assert (r.n, r.distincts, r.premier, r.dernier) == attendu, r.code


@pytest.mark.parametrize("contrat", _CONTRATS, ids=_id)
def test_mesures_fideles_au_csv(db_session: Session, contrat: ContratSerie) -> None:
    """Chaque mesure en base = CSV committé, au bit près ; statut brut, confiance B."""
    if _journalier(contrat):
        attendu = {
            (s["code"], jour): v
            for s in lire_series_journalieres(contrat, LOT_AEROSOLS_JOURNALIER)
            for jour, v in s["mesures"]
        }
        requete = """
            SELECT s.code, m.instant_mesure AS cle, m.valeur, m.statut,
                   m.niveau_confiance_derive
            FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
        """
        nb_periodes = len(_JOURS)
    else:
        attendu = {
            (s["code"], (a, m)): v
            for s in lire_series(contrat, LOT_AEROSOLS_MENSUEL)
            for a, m, v in s["mesures"]
        }
        requete = """
            SELECT s.code, m.annee, m.mois, m.valeur, m.statut, m.niveau_confiance_derive
            FROM mesures_ressource_mensuelles m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
        """
        nb_periodes = len(_MOIS)
    rows = db_session.execute(text(requete), {"c": _codes(contrat)}).all()
    assert len(rows) == len(attendu) == len(_localites(contrat)) * nb_periodes
    for r in rows:
        cle = r.cle if _journalier(contrat) else (r.annee, r.mois)
        assert r.valeur == attendu[(r.code, cle)], (r.code, cle)
        assert r.statut == "brut" and r.niveau_confiance_derive == "B"


@pytest.mark.parametrize("contrat", _CONTRATS, ids=_id)
def test_bornes(db_session: Session, contrat: ContratSerie) -> None:
    """Toute valeur finie dans [0, borne de sanité du contrat]."""
    table = "mesures_ressource" if _journalier(contrat) else "mesures_ressource_mensuelles"
    row = db_session.execute(
        text(
            f"""
            SELECT MIN(m.valeur) AS mini, MAX(m.valeur) AS maxi,
                   COUNT(*) FILTER (WHERE m.valeur = 'NaN'::float8) AS nan
            FROM {table} m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": _codes(contrat)},
    ).one()
    assert row.nan == 0
    assert 0.0 <= row.mini <= row.maxi <= contrat.borne_max


@pytest.mark.parametrize("granularite", ["mensuel", "journalier"])
def test_pm2_5_inferieur_ou_egal_pm10(db_session: Session, granularite: str) -> None:
    """Cohérence physique : PM2.5 <= PM10 pour chaque (localité, période).

    Un seul regroupement par (localité, période), sans auto-jointure ; chaque
    mesure PM2.5 doit avoir sa PM10 (nombre exact de paires).
    """
    if granularite == "journalier":
        table, periode, localites = "mesures_ressource", "m.instant_mesure", _JOURNALIERES
        nb = len(_JOURS)
    else:
        table, periode, localites = "mesures_ressource_mensuelles", "m.annee, m.mois", _MENSUELLES
        nb = len(_MOIS)
    contrats = CONTRATS_EAC4_JOURNALIERS if granularite == "journalier" else CONTRATS_EAC4_MENSUELS
    row = db_session.execute(
        text(
            f"""
            SELECT COUNT(*) FILTER (WHERE pm2_5 IS NOT NULL AND pm10 IS NOT NULL) AS paires,
                   COUNT(*) FILTER (WHERE pm2_5 > pm10) AS violations
            FROM (
                SELECT s.localite_id, {periode},
                       MAX(m.valeur) FILTER (WHERE s.grandeur_code = 'pm2_5') AS pm2_5,
                       MAX(m.valeur) FILTER (WHERE s.grandeur_code = 'pm10') AS pm10
                FROM {table} m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:c)
                GROUP BY s.localite_id, {periode}
            ) t
            """
        ),
        {"c": [c.code_serie(code) for c in contrats.values() for code in localites]},
    ).one()
    assert row.paires == len(localites) * nb
    assert row.violations == 0


@pytest.mark.parametrize("contrat", list(CONTRATS_EAC4_JOURNALIERS.values()), ids=_id)
def test_coherence_journalier_mensuel(db_session: Session, contrat: ContratSerie) -> None:
    """Moyenne des jours de chaque mois (recalculée en base) = mensuel EAC4 servi.

    Le produit ``monthly_mean`` est la moyenne des analyses du mois ; la moyenne
    des moyennes journalières (8 analyses par jour) doit le redonner, à
    l'arrondi et à la précision du codage de la source près (ADR-0022).
    """
    rows = db_session.execute(
        text(
            """
            WITH jour AS (
                SELECT s.localite_id, EXTRACT(YEAR FROM m.instant_mesure)::int AS annee,
                       EXTRACT(MONTH FROM m.instant_mesure)::int AS mois,
                       AVG(m.valeur) AS moyenne, COUNT(*) AS n
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:c)
                GROUP BY 1, 2, 3
            )
            SELECT j.moyenne, j.n, mm.valeur AS mensuel, j.annee, j.mois
            FROM jour j
            JOIN series_metadonnees sm
                ON sm.localite_id = j.localite_id AND sm.grandeur_code = :g
               AND sm.granularite = 'mensuel'
            JOIN sources src ON src.id = sm.source_id AND src.code = 'cams_eac4'
            JOIN mesures_ressource_mensuelles mm
                ON mm.serie_id = sm.id AND mm.annee = j.annee AND mm.mois = j.mois
            """
        ),
        {"c": _codes(contrat), "g": contrat.grandeur_code},
    ).all()
    assert len(rows) == 34 * len(_MOIS)
    ecarts_mois_incoherent = []
    for r in rows:
        mois_suivant = date(r.annee + r.mois // 12, r.mois % 12 + 1, 1)
        assert r.n == (mois_suivant - date(r.annee, r.mois, 1)).days  # tous les jours du mois
        ecart = abs(r.moyenne - r.mensuel)
        if (r.annee, r.mois) == _MOIS_INCOHERENT_SOURCE:
            ecarts_mois_incoherent.append((ecart, ecart / r.mensuel))
        else:
            assert ecart <= _TOLERANCE_MENSUEL_UG, (r.annee, r.mois, r.moyenne, r.mensuel)
    # Mars 2024 : incohérence de la source aux 34 localités, signalée et bornée (< 6 %),
    # pas masquée (ADR-0022). Si la source est corrigée, ce test le dira.
    assert len(ecarts_mois_incoherent) == 34
    assert all(e > _TOLERANCE_MENSUEL_UG and rel < 0.06 for e, rel in ecarts_mois_incoherent)


def test_resolveurs_api(db_session: Session) -> None:
    """Les résolveurs PM de l'API trouvent les séries journalières, et elles seules.

    - PR réaliste : ``_chercher_serie_pm_cams`` (source ``cams_eac4``, granularité
      journalière) aux 34 localités du lot ; rien ailleurs (le mensuel est ignoré).
    - Proxy de salissure : depuis la série PM2.5 journalière, la compagne PM10
      (``_chercher_serie_compagne`` : même source, même granularité, période recouvrante).
    - Lecture : index journalier contigu de 2003-01-01 à 2025-12-31 (HSU).
    """
    from kuma_data_core.api.v1.grandeurs import (
        _chercher_serie_compagne,
        _chercher_serie_pm_cams,
        _lire_mesures_par_serie_id,
        _resoudre_serie_source,
    )

    ids = {
        (r.localite, r.code): r.id
        for r in db_session.execute(
            text(
                """
                SELECT loc.code AS localite, s.code, s.id FROM series_metadonnees s
                JOIN localites loc ON loc.id = s.localite_id WHERE s.code = ANY(:c)
                """
            ),
            {"c": [c for contrat in _CONTRATS for c in _codes(contrat)]},
        ).all()
    }
    localite_id = dict(
        db_session.execute(
            text("SELECT code, id FROM localites WHERE code = ANY(:c)"), {"c": sorted(_MENSUELLES)}
        ).all()
    )
    for code in sorted(_MENSUELLES):
        for grandeur, contrat in CONTRATS_EAC4_JOURNALIERS.items():
            trouve = _chercher_serie_pm_cams(db_session, localite_id[code], grandeur)
            if code in _JOURNALIERES:
                assert trouve == ids[(code, contrat.code_serie(code))], (code, grandeur)
            else:
                assert trouve is None, (code, grandeur)

    for code in sorted(_JOURNALIERES):
        source = _resoudre_serie_source(
            db_session, CONTRATS_EAC4_JOURNALIERS["pm2_5"].code_serie(code)
        )
        assert (source.source_code, source.grandeur_code, source.granularite) == (
            "cams_eac4",
            "pm2_5",
            "journalier",
        )
        compagne = _chercher_serie_compagne(db_session, source, "pm10")
        assert compagne == ids[(code, CONTRATS_EAC4_JOURNALIERS["pm10"].code_serie(code))]

    lues = _lire_mesures_par_serie_id(
        db_session,
        ids[("civ_dep_abidjan", CONTRATS_EAC4_JOURNALIERS["pm2_5"].code_serie("civ_dep_abidjan"))],
        date(2000, 1, 1),
        date(2100, 1, 1),
    )
    assert sorted(lues) == _JOURS
