"""Tests d'intégration des PM2.5 et PM10 journalières CAMS EAC4 aux 108 départements.

Migration 0048 (ADR-0031) : lot ``departements`` (``mesures_ressource``),
2003-2025, mêmes contrats que le journalier des 34 localités (migration 0037,
ADR-0022). Vérifie les métadonnées (notes de 0037, lot départements), la
**fidélité exacte** aux CSV gzip committés (agrégats par série calculés en
``numeric`` en base et en ``Decimal`` depuis les chaînes du CSV), les bornes,
PM2.5 <= PM10, la cohérence avec le mensuel EAC4 gravé (mars 2024 excepté,
incohérence de la source), l'**audit par série** (une entrée par série, aucune
ligne à ligne), l'intégrité du journalier des 34 localités et les résolveurs PM
de l'API (proxy de salissure, PR réaliste).
"""

from __future__ import annotations

import csv
import gzip
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds.aerosols_civ import (
    CONTRATS_EAC4_JOURNALIERS,
    LOT_AEROSOLS_JOURNALIER,
)
from kuma_data_core.db.seeds.audit_par_serie import empreinte_fichier
from kuma_data_core.db.seeds.journalier_departements_civ import (
    CONTRATS_PARTICULES_DEPARTEMENTS,
    LOT_JOURNALIER_DEPARTEMENTS,
    points_journalier_departements,
)
from kuma_data_core.db.seeds.lots_civ import points_journalier, points_nationaux
from kuma_data_core.db.seeds.series_csv import (
    COLONNES_JOURNALIERES,
    DOSSIER_DONNEES,
    ContratSerie,
)

pytestmark = pytest.mark.integration

REVISION: str = "0048"
_DEPARTEMENTS = {code for code, _, _, _ in points_journalier_departements()}
_LOCALITES_34 = {code for code, _, _, _ in points_journalier()}
_CONTRATS = list(CONTRATS_PARTICULES_DEPARTEMENTS.values())

# Calendrier recalculé indépendamment des contrats : 2003-01-01 → 2025-12-31.
_DEBUT, _FIN = date(2003, 1, 1), date(2025, 12, 31)
_JOURS = [_DEBUT + timedelta(days=i) for i in range((_FIN - _DEBUT).days + 1)]
_NB_MOIS = 276

# Écart toléré entre le mensuel servi et la moyenne des jours gravés (µg/m³) :
# arrondi à 4 décimales des deux CSV et codage des champs de la source (écart
# mesuré aux 108 départements : 3,3·10⁻⁴ au plus). Seul mars 2024 s'en écarte,
# côté source : le produit mensuel n'y est pas la moyenne des analyses
# 3-horaires servies (ADR-0022). Aux 108 départements, l'écart relatif y atteint
# 6,03 % (PM2.5, Doropo) et 5,75 % (PM10) : borné ici, pas masqué.
_TOLERANCE_MENSUEL_UG = Decimal("0.001")
_MOIS_INCOHERENT_SOURCE: tuple[int, int] = (2024, 3)
_ECART_RELATIF_MAX_MARS_2024 = Decimal("0.065")

Agregats = tuple[int, date, date, Decimal, Decimal]

_SQL_AGREGATS = """
    SELECT s.code, COUNT(*) AS n, COUNT(DISTINCT m.instant_mesure) AS distincts,
           MIN(m.instant_mesure) AS premier, MAX(m.instant_mesure) AS dernier,
           SUM(m.valeur::numeric) AS somme,
           SUM((m.instant_mesure - DATE '2003-01-01' + 1) * m.valeur::numeric) AS somme_rang,
           COUNT(*) FILTER (
               WHERE m.statut <> 'brut' OR m.niveau_confiance_derive <> 'B'
                  OR m.valide_au IS NOT NULL
           ) AS hors_contrat
    FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
    WHERE s.code = ANY(:c)
    GROUP BY s.code
"""


def _id(contrat: ContratSerie) -> str:
    return contrat.prefixe_code


def _codes(contrat: ContratSerie, localites: set[str] = _DEPARTEMENTS) -> list[str]:
    return sorted(contrat.code_serie(code) for code in localites)


def _codes_lot() -> list[str]:
    return [code for contrat in _CONTRATS for code in _codes(contrat)]


def _ids_lot(db_session: Session) -> dict[str, int]:
    return dict(
        db_session.execute(
            text("SELECT code, id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": _codes_lot()},
        ).all()
    )


def _agregats_csv(contrat: ContratSerie, lot: str) -> dict[str, Agregats]:
    """Par série : nombre, premier et dernier jour, Σ valeur, Σ (rang du jour x valeur).

    Calculés en ``Decimal`` depuis les chaînes du CSV gzip committé (valeurs
    telles qu'écrites, 4 décimales) ; rang du jour = 1 au 2003-01-01.
    """
    nb: Counter[str] = Counter()
    premier: dict[str, date] = {}
    dernier: dict[str, date] = {}
    somme: defaultdict[str, Decimal] = defaultdict(Decimal)
    somme_rang: defaultdict[str, Decimal] = defaultdict(Decimal)
    with gzip.open(DOSSIER_DONNEES / contrat.nom_fichier(lot), "rt", encoding="utf-8") as f:
        lecteur = csv.reader(f)
        assert tuple(next(lecteur)) == COLONNES_JOURNALIERES
        for localite, _, _, jour_s, valeur_s in lecteur:
            code = contrat.code_serie(localite)
            jour, valeur = date.fromisoformat(jour_s), Decimal(valeur_s)
            nb[code] += 1
            premier[code] = min(premier.get(code, jour), jour)
            dernier[code] = max(dernier.get(code, jour), jour)
            somme[code] += valeur
            somme_rang[code] += ((jour - _DEBUT).days + 1) * valeur
    return {c: (nb[c], premier[c], dernier[c], somme[c], somme_rang[c]) for c in nb}


def _agregats_base(db_session: Session, codes: list[str]) -> dict[str, Agregats]:
    """Mêmes agrégats, en ``numeric`` en base ; sans doublon ni mesure hors contrat."""
    sortie: dict[str, Agregats] = {}
    for r in db_session.execute(text(_SQL_AGREGATS), {"c": codes}).all():
        assert r.distincts == r.n and r.hors_contrat == 0, r.code
        sortie[r.code] = (r.n, r.premier, r.dernier, r.somme, r.somme_rang)
    return sortie


def test_perimetre() -> None:
    """108 départements, disjoints des 34 localités ; ensemble, les 142 ; 8401 jours."""
    assert len(_DEPARTEMENTS) == 108 and not _DEPARTEMENTS & _LOCALITES_34
    nationaux = {code for code, _, _, _ in points_nationaux()}
    assert nationaux == _DEPARTEMENTS | _LOCALITES_34
    assert len(_JOURS) == 8401
    assert CONTRATS_PARTICULES_DEPARTEMENTS == CONTRATS_EAC4_JOURNALIERS


def test_grandeurs_et_unite(db_session: Session) -> None:
    """PM2.5 et PM10 en µg/m³ au référentiel ; source ``cams_eac4`` (id 15)."""
    assert (
        db_session.execute(text("SELECT code FROM sources WHERE id = 15")).scalar_one()
        == "cams_eac4"
    )
    unites = dict(
        db_session.execute(
            text(
                """
                SELECT g.code, u.code FROM grandeurs_referentiel g
                JOIN unites u ON u.id = g.unite_id WHERE g.code IN ('pm2_5', 'pm10')
                """
            )
        ).all()
    )
    assert unites == dict.fromkeys(("pm2_5", "pm10"), "microgramme_par_metre_cube")


@pytest.mark.parametrize("contrat", _CONTRATS, ids=_id)
def test_series(db_session: Session, contrat: ContratSerie) -> None:
    """Une série par département ; métadonnées et note de 0037, lot départements."""
    rows = db_session.execute(
        text(
            """
            SELECT s.code, loc.code AS localite, s.grandeur_code, s.granularite,
                   s.methode_collecte, s.periode_debut, s.periode_fin, s.libelle,
                   s.note_publique, s.actif, src.code AS source
            FROM series_metadonnees s
            JOIN sources src ON src.id = s.source_id
            JOIN localites loc ON loc.id = s.localite_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": _codes(contrat)},
    ).all()
    assert sorted(r.code for r in rows) == _codes(contrat)
    assert {r.localite for r in rows} == _DEPARTEMENTS
    # Note de la série homologue du lot « pilotes + régions » (0037).
    note_0037 = db_session.execute(
        text("SELECT note_publique FROM series_metadonnees WHERE code = :c"),
        {"c": contrat.code_serie("civ_dep_abidjan")},
    ).scalar_one()
    note_attendue = note_0037.replace(
        "Lot « pilotes + régions » (34 localités)",
        "Lot « départements » (108 départements hors pilotes)",
    ).replace("(ADR-0022)", "(ADR-0022, ADR-0031)")
    assert note_attendue != note_0037
    libelle = "PM2.5" if contrat.grandeur_code == "pm2_5" else "PM10"
    for r in rows:
        assert r.code == contrat.code_serie(r.localite)
        assert (r.source, r.grandeur_code, r.granularite) == (
            "cams_eac4",
            contrat.grandeur_code,
            "journalier",
        )
        assert r.methode_collecte == "reanalyse" and r.actif
        assert (r.periode_debut, r.periode_fin) == (_DEBUT, _FIN)
        assert r.libelle.startswith(f"{libelle} journalier CAMS EAC4 — ")
        assert r.libelle.endswith(" (2003-2025)")
        assert r.note_publique == note_attendue


@pytest.mark.parametrize("contrat", _CONTRATS, ids=_id)
def test_mesures_fideles_au_csv(db_session: Session, contrat: ContratSerie) -> None:
    """Agrégats exacts par série, base (``numeric``) = CSV committé (``Decimal``).

    Nombre, premier et dernier jour, Σ valeur et Σ (rang du jour x valeur) : la
    seconde somme détecte une valeur déplacée d'un jour à l'autre. Statut brut,
    confiance B, mesures courantes, sans doublon.
    """
    attendu = _agregats_csv(contrat, LOT_JOURNALIER_DEPARTEMENTS)
    obtenu = _agregats_base(db_session, _codes(contrat))
    assert sorted(attendu) == sorted(obtenu) == _codes(contrat)
    for code, (n, premier, dernier, _, _) in attendu.items():
        assert (n, premier, dernier) == (len(_JOURS), _JOURS[0], _JOURS[-1]), code
        assert obtenu[code] == attendu[code], code


@pytest.mark.parametrize("contrat", _CONTRATS, ids=_id)
def test_bornes(db_session: Session, contrat: ContratSerie) -> None:
    """Toute valeur finie dans ]0, borne de sanité du contrat] (aucun jour nul)."""
    row = db_session.execute(
        text(
            """
            SELECT MIN(m.valeur) AS mini, MAX(m.valeur) AS maxi,
                   COUNT(*) FILTER (WHERE m.valeur = 'NaN'::float8) AS nan
            FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": _codes(contrat)},
    ).one()
    assert row.nan == 0
    assert 0.0 < row.mini <= row.maxi <= contrat.borne_max


def test_pm2_5_inferieur_ou_egal_pm10(db_session: Session) -> None:
    """Cohérence physique : PM2.5 <= PM10 pour chaque (département, jour).

    Chaque mesure PM2.5 a sa PM10 (nombre exact de paires) ; les violations
    éventuelles sont listées dans le message d'échec.
    """
    row = db_session.execute(
        text(
            """
            SELECT COUNT(*) FILTER (WHERE pm2_5 IS NOT NULL AND pm10 IS NOT NULL) AS paires,
                   COUNT(*) FILTER (WHERE pm2_5 > pm10) AS violations,
                   (ARRAY_AGG(localite || ' ' || instant_mesure || ' : ' || pm2_5 || ' > ' || pm10
                              ORDER BY localite, instant_mesure)
                        FILTER (WHERE pm2_5 > pm10))[1:20] AS exemples
            FROM (
                SELECT loc.code AS localite, m.instant_mesure,
                       MAX(m.valeur) FILTER (WHERE s.grandeur_code = 'pm2_5') AS pm2_5,
                       MAX(m.valeur) FILTER (WHERE s.grandeur_code = 'pm10') AS pm10
                FROM mesures_ressource m
                JOIN series_metadonnees s ON s.id = m.serie_id
                JOIN localites loc ON loc.id = s.localite_id
                WHERE s.code = ANY(:c)
                GROUP BY loc.code, m.instant_mesure
            ) t
            """
        ),
        {"c": _codes_lot()},
    ).one()
    assert row.paires == len(_DEPARTEMENTS) * len(_JOURS)
    assert row.violations == 0, row.exemples


@pytest.mark.parametrize("contrat", _CONTRATS, ids=_id)
def test_coherence_journalier_mensuel(db_session: Session, contrat: ContratSerie) -> None:
    """Moyenne des jours de chaque mois (en ``numeric``) = mensuel EAC4 gravé (0037).

    Le produit ``monthly_mean`` est la moyenne des analyses du mois ; la moyenne
    des moyennes journalières doit le redonner, à l'arrondi près — sauf en mars
    2024, où la source est incohérente (ADR-0022) : l'écart y est exigé, et borné.
    """
    rows = db_session.execute(
        text(
            """
            WITH jour AS (
                SELECT s.localite_id, EXTRACT(YEAR FROM m.instant_mesure)::int AS annee,
                       EXTRACT(MONTH FROM m.instant_mesure)::int AS mois,
                       AVG(m.valeur::numeric) AS moyenne, COUNT(*) AS n
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:c)
                GROUP BY 1, 2, 3
            )
            SELECT loc.code AS localite, j.annee, j.mois, j.n, j.moyenne,
                   mm.valeur::numeric AS mensuel
            FROM jour j
            JOIN localites loc ON loc.id = j.localite_id
            JOIN series_metadonnees sm
                ON sm.localite_id = j.localite_id AND sm.grandeur_code = :g
               AND sm.granularite = 'mensuel'
            JOIN sources src ON src.id = sm.source_id AND src.code = 'cams_eac4'
            JOIN mesures_ressource_mensuelles mm
                ON mm.serie_id = sm.id AND mm.annee = j.annee AND mm.mois = j.mois
               AND mm.valide_au IS NULL
            """
        ),
        {"c": _codes(contrat), "g": contrat.grandeur_code},
    ).all()
    assert len(rows) == len(_DEPARTEMENTS) * _NB_MOIS
    mars_2024 = []
    for r in rows:
        mois_suivant = date(r.annee + r.mois // 12, r.mois % 12 + 1, 1)
        assert r.n == (mois_suivant - date(r.annee, r.mois, 1)).days  # tous les jours du mois
        ecart = abs(r.moyenne - r.mensuel)
        if (r.annee, r.mois) == _MOIS_INCOHERENT_SOURCE:
            mars_2024.append((r.localite, ecart, ecart / r.mensuel))
        else:
            assert ecart <= _TOLERANCE_MENSUEL_UG, (r.localite, r.annee, r.mois, ecart)
    # Mars 2024 : incohérence de la source aux 108 départements, exigée et bornée.
    # Si la source est corrigée, ce test le dira.
    assert {localite for localite, _, _ in mars_2024} == _DEPARTEMENTS
    assert all(e > _TOLERANCE_MENSUEL_UG for _, e, _ in mars_2024)
    assert max(rel for _, _, rel in mars_2024) < _ECART_RELATIF_MAX_MARS_2024


def test_audit_par_serie(db_session: Session) -> None:
    """Une entrée d'audit par série (``I``, révision 0048) ; aucune ligne à ligne.

    L'absence d'audit ligne à ligne est vérifiée de deux façons : (1) aucune
    entrée ``mesures_ressource`` ordinaire dans la fenêtre de la migration (de
    l'audit des séries insérées à la dernière entrée par série) ; (2) aucune
    entrée pour la première et la dernière mesure de chaque série. Le trigger
    d'audit de ``mesures_ressource`` est réactivé.
    """
    ids = _ids_lot(db_session)
    assert len(ids) == 216
    entrees = db_session.execute(
        text(
            """
            SELECT id_ligne_auditee, type_operation, valeurs_apres, valeurs_avant, horodatage
            FROM audit_log
            WHERE schema_audite = 'public' AND table_auditee = 'mesures_ressource'
              AND id_ligne_auditee = ANY(:cles)
            """
        ),
        {"cles": [f"serie:{i}" for i in ids.values()]},
    ).all()
    assert sorted(e.id_ligne_auditee for e in entrees) == sorted(f"serie:{i}" for i in ids.values())
    par_cle = {e.id_ligne_auditee: e for e in entrees}
    for contrat in _CONTRATS:
        fichier = contrat.nom_fichier(LOT_JOURNALIER_DEPARTEMENTS)
        empreinte = empreinte_fichier(contrat, LOT_JOURNALIER_DEPARTEMENTS)
        for code in _codes(contrat):
            entree = par_cle[f"serie:{ids[code]}"]
            assert entree.type_operation == "I" and entree.valeurs_avant is None
            assert entree.valeurs_apres == {
                "audit": "par_serie",
                "revision": REVISION,
                "serie_code": code,
                "nb_mesures": len(_JOURS),
                "premier_instant": _DEBUT.isoformat(),
                "dernier_instant": _FIN.isoformat(),
                "fichier": fichier,
                "sha256": empreinte,
            }

    # (1) Fenêtre de la migration : audit (ligne à ligne) des séries insérées → audit par série.
    debut_fenetre = db_session.execute(
        text(
            """
            SELECT MIN(horodatage), COUNT(*) FROM audit_log
            WHERE schema_audite = 'public' AND table_auditee = 'series_metadonnees'
              AND type_operation = 'I' AND id_ligne_auditee = ANY(:ids)
            """
        ),
        {"ids": [str(i) for i in ids.values()]},
    ).one()
    assert debut_fenetre[1] == 216
    fin_fenetre = max(e.horodatage for e in entrees)
    lignes_fenetre = db_session.execute(
        text(
            """
            SELECT COUNT(*) FROM audit_log
            WHERE schema_audite = 'public' AND table_auditee = 'mesures_ressource'
              AND horodatage BETWEEN :debut AND :fin AND id_ligne_auditee NOT LIKE 'serie:%'
            """
        ),
        {"debut": debut_fenetre[0], "fin": fin_fenetre},
    ).scalar_one()
    assert lignes_fenetre == 0

    # (2) Première et dernière mesure de chaque série : aucune entrée ligne à ligne.
    bornes = db_session.execute(
        text(
            """
            SELECT MIN(id)::text AS premiere, MAX(id)::text AS derniere
            FROM mesures_ressource WHERE serie_id = ANY(:ids) GROUP BY serie_id
            """
        ),
        {"ids": list(ids.values())},
    ).all()
    assert len(bornes) == 216
    lignes = db_session.execute(
        text(
            """
            SELECT COUNT(*) FROM audit_log
            WHERE schema_audite = 'public' AND table_auditee = 'mesures_ressource'
              AND id_ligne_auditee = ANY(:cles)
            """
        ),
        {"cles": [b.premiere for b in bornes] + [b.derniere for b in bornes]},
    ).scalar_one()
    assert lignes == 0

    etat = db_session.execute(
        text("SELECT tgenabled FROM pg_trigger WHERE tgname = 'trg_audit_mesures_ressource'")
    ).scalar_one()
    assert etat == "O"


@pytest.mark.parametrize("contrat", list(CONTRATS_EAC4_JOURNALIERS.values()), ids=_id)
def test_journalier_34_localites_intact(db_session: Session, contrat: ContratSerie) -> None:
    """Le journalier EAC4 des 34 localités (0037) reste fidèle à son CSV, au même titre.

    Et les séries PM EAC4 journalières sont exactement celles des deux lots.
    """
    attendu = _agregats_csv(contrat, LOT_AEROSOLS_JOURNALIER)
    codes = _codes(contrat, _LOCALITES_34)
    assert sorted(attendu) == codes
    assert _agregats_base(db_session, codes) == attendu
    toutes = db_session.execute(
        text(
            """
            SELECT s.code FROM series_metadonnees s JOIN sources src ON src.id = s.source_id
            WHERE src.code = 'cams_eac4' AND s.grandeur_code = :g AND s.granularite = 'journalier'
            """
        ),
        {"g": contrat.grandeur_code},
    ).scalars()
    assert sorted(toutes) == sorted(codes + _codes(contrat))


def test_resolveurs_api(db_session: Session) -> None:
    """Les résolveurs PM de l'API trouvent les séries du lot aux 108 départements.

    - PR réaliste : ``_chercher_serie_pm_cams`` (source ``cams_eac4``, granularité
      journalière ; le mensuel 0037 de la même localité n'est jamais pris).
    - Proxy de salissure : depuis la série PM2.5 résolue par
      ``_resoudre_serie_source``, la compagne PM10 (``_chercher_serie_compagne``).
    - Lecture : index journalier contigu de 2003-01-01 à 2025-12-31 (HSU).
    """
    from kuma_data_core.api.v1.grandeurs import (
        _chercher_serie_compagne,
        _chercher_serie_pm_cams,
        _lire_mesures_par_serie_id,
        _resoudre_serie_source,
    )

    ids = _ids_lot(db_session)
    localite_id = dict(
        db_session.execute(
            text("SELECT code, id FROM localites WHERE code = ANY(:c)"),
            {"c": sorted(_DEPARTEMENTS)},
        ).all()
    )
    pm2_5 = CONTRATS_PARTICULES_DEPARTEMENTS["pm2_5"]
    pm10 = CONTRATS_PARTICULES_DEPARTEMENTS["pm10"]
    for code in sorted(_DEPARTEMENTS):
        for grandeur, contrat in CONTRATS_PARTICULES_DEPARTEMENTS.items():
            trouve = _chercher_serie_pm_cams(db_session, localite_id[code], grandeur)
            assert trouve == ids[contrat.code_serie(code)], (code, grandeur)

        source = _resoudre_serie_source(db_session, pm2_5.code_serie(code))
        assert source.serie_id == ids[pm2_5.code_serie(code)]
        assert (
            source.source_code,
            source.grandeur_code,
            source.granularite,
            source.localite_code,
            source.periode_debut,
            source.periode_fin,
        ) == ("cams_eac4", "pm2_5", "journalier", code, _DEBUT, _FIN)
        compagne = _chercher_serie_compagne(db_session, source, "pm10")
        assert compagne == ids[pm10.code_serie(code)], code

    lues = _lire_mesures_par_serie_id(
        db_session, ids[pm2_5.code_serie("civ_dep_tehini")], date(2000, 1, 1), date(2100, 1, 1)
    )
    assert sorted(lues) == _JOURS
