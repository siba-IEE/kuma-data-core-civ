"""Tests d'intégration de la météo journalière NASA POWER aux 108 départements (0047, ADR-0031).

6 grandeurs aux 108 départements hors pilotes du lot ``departements``, dans
``mesures_ressource`` : ``t2m``, ``rh2m``, ``vent_2m``, ``vent_10m`` et
``precipitation`` (MERRA-2, 1991-2025), ``albedo_surface`` (CERES, 2001-2025),
soit 648 séries et 7 889 508 mesures.

Vérifie les métadonnées (source, méthode, granularité, période, unité du
référentiel, libellé, note publique), la **fidélité exacte** aux CSV gzip
committés par agrégats par série — nombre, premier et dernier jour, somme des
valeurs et somme pondérée par le rang du jour, en ``numeric`` côté base et en
``Decimal`` depuis les chaînes du CSV (aucune mesure chargée en Python) —, la
cohérence avec le mensuel météo NASA gravé en 0034, les bornes physiques, les
jours de pluie au-delà de 200 mm cités par la note, l'**audit par série**
(une entrée par série, aucune entrée ligne à ligne pour ces mesures) et
l'intégrité des 204 séries journalières météo des 34 localités (0035).
"""

from __future__ import annotations

import csv
import gzip
import re
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from functools import cache

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds.audit_par_serie import empreinte_fichier
from kuma_data_core.db.seeds.journalier_departements_civ import (
    CONTRATS_METEO_DEPARTEMENTS,
    LOT_JOURNALIER_DEPARTEMENTS,
    points_journalier_departements,
)
from kuma_data_core.db.seeds.lots_civ import points_journalier
from kuma_data_core.db.seeds.meteo_civ import (
    CONTRATS_METEO_NASA_JOURNALIERS,
    CONTRATS_METEO_NASA_MENSUELS,
    LOT_METEO_JOURNALIER,
)
from kuma_data_core.db.seeds.series_csv import DOSSIER_DONNEES

pytestmark = pytest.mark.integration

_LOCALITES = sorted(code for code, _, _, _ in points_journalier_departements())
_LOCALITES_34 = sorted(code for code, _, _, _ in points_journalier())

# Grandeur -> (première année, méthode, unité au référentiel, bornes physiques).
_ATTENDU: dict[str, tuple[int, str, str, float, float]] = {
    "t2m": (1991, "reanalyse", "degree_celsius", 10.0, 45.0),
    "rh2m": (1991, "reanalyse", "pourcent", 0.0, 100.0),
    "vent_2m": (1991, "reanalyse", "metre_par_seconde", 0.0, 20.0),
    "vent_10m": (1991, "reanalyse", "metre_par_seconde", 0.0, 25.0),
    "precipitation": (1991, "reanalyse", "mm_par_jour", 0.0, 1000.0),
    "albedo_surface": (2001, "modele_satellitaire", "sans_unite", 0.0, 1.0),
}
_GRANDEURS = list(_ATTENDU)

# Jour cité par la mise en garde de la pluie : « 726,74 mm à San-Pédro le 2022-09-16 ».
_JOUR_CITE = re.compile(r"(\d+,\d{2}) mm à ([^,;]+?) le (\d{4}-\d{2}-\d{2})")

Agregats = tuple[int, date, date, Decimal, Decimal]


def _codes(grandeur: str, localites: list[str] = _LOCALITES) -> list[str]:
    return [f"nasa_power_{grandeur}_journalier_{code}" for code in localites]


def _nb_jours(grandeur: str) -> int:
    return (date(2025, 12, 31) - date(_ATTENDU[grandeur][0], 1, 1)).days + 1


@cache
def _agregats_csv(grandeur: str, lot: str) -> dict[str, Agregats]:
    """Agrégats exacts par série depuis les chaînes du CSV, relu directement.

    ``{code série: (nombre, premier jour, dernier jour, Σ valeur, Σ rang * valeur)}``,
    le rang du jour comptant à partir de 1 au premier jour du contrat.
    """
    debut = date(_ATTENDU[grandeur][0], 1, 1)
    chemin = DOSSIER_DONNEES / f"nasa_power_{grandeur}_journalier_{lot}.csv.gz"
    nombre: Counter[str] = Counter()
    premier: dict[str, date] = {}
    dernier: dict[str, date] = {}
    somme: defaultdict[str, Decimal] = defaultdict(Decimal)
    somme_rang: defaultdict[str, Decimal] = defaultdict(Decimal)
    with gzip.open(chemin, "rt", encoding="utf-8", newline="") as f:
        lecteur = csv.reader(f)
        assert next(lecteur) == ["localite_code", "latitude", "longitude", "date", "valeur"]
        for loc, _, _, jour_s, valeur_s in lecteur:
            code, jour, valeur = (
                f"nasa_power_{grandeur}_journalier_{loc}",
                date.fromisoformat(jour_s),
                Decimal(valeur_s),
            )
            nombre[code] += 1
            premier[code] = min(premier.get(code, jour), jour)
            dernier[code] = max(dernier.get(code, jour), jour)
            somme[code] += valeur
            somme_rang[code] += ((jour - debut).days + 1) * valeur
    return {c: (nombre[c], premier[c], dernier[c], somme[c], somme_rang[c]) for c in nombre}


def _agregats_base(db_session: Session, grandeur: str, codes: list[str]) -> dict[str, Agregats]:
    """Mêmes agrégats en base, en ``numeric`` (le ``float8`` y revient exactement)."""
    rows = db_session.execute(
        text(
            """
            SELECT s.code, COUNT(*) AS n, COUNT(DISTINCT m.instant_mesure) AS distincts,
                   MIN(m.instant_mesure) AS premier, MAX(m.instant_mesure) AS dernier,
                   SUM(m.valeur::numeric) AS somme,
                   SUM((m.instant_mesure - CAST(:debut AS date) + 1) * m.valeur::numeric)
                       AS somme_rang
            FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
            GROUP BY s.code
            """
        ),
        {"c": codes, "debut": date(_ATTENDU[grandeur][0], 1, 1)},
    ).all()
    for r in rows:
        assert r.n == r.distincts, r.code  # un seul jour par date
    return {r.code: (r.n, r.premier, r.dernier, r.somme, r.somme_rang) for r in rows}


def test_contrats_alignes() -> None:
    """Contrats du lot = contrats de 0035 ; 108 départements disjoints des 34 localités."""
    assert len(_LOCALITES) == 108
    assert not set(_LOCALITES) & set(_LOCALITES_34)
    assert CONTRATS_METEO_DEPARTEMENTS == CONTRATS_METEO_NASA_JOURNALIERS
    for g, c in CONTRATS_METEO_DEPARTEMENTS.items():
        assert (c.annee_debut, c.annee_fin, c.methode_collecte) == (
            _ATTENDU[g][0],
            2025,
            _ATTENDU[g][1],
        )
        assert c.granularite == "journalier" and c.source_code == "nasa_power"


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_series_journalieres(db_session: Session, grandeur: str) -> None:
    """108 séries par grandeur : source, méthode, période, unité, libellé et note."""
    debut, methode, unite, _, _ = _ATTENDU[grandeur]
    rows = db_session.execute(
        text(
            """
            SELECT loc.code AS localite, loc.nom, s.granularite, s.methode_collecte,
                   s.periode_debut, s.periode_fin, s.actif, s.libelle, s.note_publique,
                   src.code AS source, u.code AS unite
            FROM series_metadonnees s
            JOIN sources src ON src.id = s.source_id
            JOIN localites loc ON loc.id = s.localite_id
            JOIN grandeurs_referentiel g ON g.code = s.grandeur_code
            JOIN unites u ON u.id = g.unite_id
            WHERE s.code = ANY(:c) AND s.grandeur_code = :g
            """
        ),
        {"c": _codes(grandeur), "g": grandeur},
    ).all()
    assert sorted(r.localite for r in rows) == _LOCALITES
    for r in rows:
        assert r.source == "nasa_power" and r.granularite == "journalier" and r.actif
        assert r.methode_collecte == methode and r.unite == unite
        assert (r.periode_debut, r.periode_fin) == (date(debut, 1, 1), date(2025, 12, 31))
        assert r.libelle.endswith(f"journalier NASA POWER — {r.nom} ({debut}-2025)")
        assert "« départements »" in r.note_publique and "ADR-0031" in r.note_publique
        assert "Confiance B" in r.note_publique
        assert ("Mise en garde" in r.note_publique) == (grandeur == "precipitation")
        if grandeur == "precipitation":
            assert "aberrantes probables" in r.note_publique
            assert "à recouper avec ERA5" in r.note_publique


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_mesures_fideles_au_csv(db_session: Session, grandeur: str) -> None:
    """Par série : nombre, bornes, Σ valeur et Σ rang * valeur exacts, base = CSV."""
    attendu = _agregats_csv(grandeur, LOT_JOURNALIER_DEPARTEMENTS)
    assert sorted(attendu) == sorted(_codes(grandeur))
    debut = date(_ATTENDU[grandeur][0], 1, 1)
    for n, premier, dernier, _, _ in attendu.values():
        assert (n, premier, dernier) == (_nb_jours(grandeur), debut, date(2025, 12, 31))
    base = _agregats_base(db_session, grandeur, _codes(grandeur))
    ecarts = [c for c in attendu.keys() | base.keys() if attendu.get(c) != base.get(c)]
    assert not ecarts, sorted(ecarts)[:10]
    hors_contrat = db_session.execute(
        text(
            """
            SELECT COUNT(*) FILTER (WHERE m.statut <> 'brut' OR m.niveau_confiance_derive <> 'B'
                                    OR m.valide_au IS NOT NULL)
            FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": _codes(grandeur)},
    ).scalar_one()
    assert hors_contrat == 0


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_bornes_physiques(db_session: Session, grandeur: str) -> None:
    """Valeurs dans des bornes physiques : humidité au plus 100 %, pluie positive ou nulle."""
    _, _, _, borne_min, borne_max = _ATTENDU[grandeur]
    r = db_session.execute(
        text(
            """
            SELECT MIN(m.valeur) AS mini, MAX(m.valeur) AS maxi
            FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": _codes(grandeur)},
    ).one()
    assert borne_min <= r.mini <= r.maxi <= borne_max, (r.mini, r.maxi)


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_coherence_avec_le_mensuel(db_session: Session, grandeur: str) -> None:
    """Moyenne des jours du mois = série mensuelle NASA de 0034 (servie à 2 décimales).

    Agrégé en SQL : nombre de mois appariés et écart maximal, à 5·10⁻³ près.
    """
    contrat_mois = CONTRATS_METEO_NASA_MENSUELS[grandeur]
    codes_mois = [contrat_mois.code_serie(code) for code in _LOCALITES]
    r = db_session.execute(
        text(
            """
            WITH jour AS (
                SELECT s.localite_id, EXTRACT(YEAR FROM m.instant_mesure)::int AS annee,
                       EXTRACT(MONTH FROM m.instant_mesure)::int AS mois,
                       AVG(m.valeur) AS moyenne
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:jour)
                GROUP BY 1, 2, 3
            ), mensuel AS (
                SELECT sm.localite_id, mm.annee, mm.mois, mm.valeur
                FROM series_metadonnees sm
                JOIN mesures_ressource_mensuelles mm ON mm.serie_id = sm.id
                WHERE sm.code = ANY(:mois) AND mm.valide_au IS NULL
            )
            SELECT COUNT(*) AS paires,
                   COUNT(*) FILTER (WHERE j.moyenne IS NULL OR x.valeur IS NULL) AS orphelins,
                   MAX(ABS(j.moyenne - x.valeur)) AS ecart_max
            FROM jour j
            FULL JOIN mensuel x
                ON x.localite_id = j.localite_id AND x.annee = j.annee AND x.mois = j.mois
            """
        ),
        {"jour": _codes(grandeur), "mois": codes_mois},
    ).one()
    assert r.paires == 108 * contrat_mois.nb_mois
    assert r.orphelins == 0
    assert r.ecart_max <= 0.005 + 1e-9, r.ecart_max


def test_pluies_extremes_citees_par_la_mise_en_garde(db_session: Session) -> None:
    """Les jours au-delà de 200 mm en base sont exactement ceux que cite la note publique.

    Valeurs aberrantes probables servies par NASA POWER, gravées sans correction
    (ADR-0031) ; la note est la même pour les 108 séries de pluie.
    """
    notes = db_session.execute(
        text("SELECT DISTINCT note_publique FROM series_metadonnees WHERE code = ANY(:c)"),
        {"c": _codes("precipitation")},
    ).all()
    assert len(notes) == 1
    cites = {(nom, jour, mm.replace(",", ".")) for mm, nom, jour in _JOUR_CITE.findall(notes[0][0])}
    rows = db_session.execute(
        text(
            """
            SELECT l.nom, m.instant_mesure, m.valeur
            FROM mesures_ressource m
            JOIN series_metadonnees s ON s.id = m.serie_id
            JOIN localites l ON l.id = s.localite_id
            WHERE s.code = ANY(:c) AND m.valeur > 200
            """
        ),
        {"c": _codes("precipitation")},
    ).all()
    en_base = {(r.nom, r.instant_mesure.isoformat(), f"{r.valeur:.2f}") for r in rows}
    assert len(rows) == len(en_base) == 20
    assert en_base == cites
    assert "Les 20 seuls jours au-delà de 200 mm" in notes[0][0]


def test_audit_par_serie(db_session: Session) -> None:
    """Une entrée d'audit par série (0047), aucune entrée ligne à ligne pour ces mesures.

    Les entrées par série portent le code, le nombre de mesures, les bornes, le
    fichier et son empreinte. Absence d'audit ligne à ligne : aucune entrée de
    ``mesures_ressource`` hors ``serie:*`` entre l'audit de la création des
    séries (``series_metadonnees``, ligne à ligne) et la dernière entrée par
    série, ni pour les mesures du premier et du dernier jour de chaque série.
    """
    series = {
        r.code: (r.id, r.grandeur_code)
        for r in db_session.execute(
            text("SELECT code, id, grandeur_code FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": [c for g in _GRANDEURS for c in _codes(g)]},
        )
    }
    assert len(series) == 648
    entrees = db_session.execute(
        text(
            """
            SELECT id_ligne_auditee, valeurs_apres, horodatage FROM audit_log
            WHERE schema_audite = 'public' AND table_auditee = 'mesures_ressource'
              AND type_operation = 'I' AND id_ligne_auditee = ANY(:lignes)
            """
        ),
        {"lignes": [f"serie:{sid}" for sid, _ in series.values()]},
    ).all()
    assert len(entrees) == 648
    par_code = {e.valeurs_apres["serie_code"]: e for e in entrees}
    assert sorted(par_code) == sorted(series)
    empreintes = {
        g: empreinte_fichier(c, LOT_JOURNALIER_DEPARTEMENTS)
        for g, c in CONTRATS_METEO_DEPARTEMENTS.items()
    }
    for code, (sid, grandeur) in series.items():
        v = par_code[code].valeurs_apres
        assert par_code[code].id_ligne_auditee == f"serie:{sid}"
        assert (v["audit"], v["revision"], v["nb_mesures"]) == (
            "par_serie",
            "0047",
            _nb_jours(grandeur),
        )
        assert (v["premier_instant"], v["dernier_instant"]) == (
            f"{_ATTENDU[grandeur][0]}-01-01",
            "2025-12-31",
        )
        assert v["fichier"] == f"nasa_power_{grandeur}_journalier_departements.csv.gz"
        assert v["sha256"] == empreintes[grandeur]

    fenetre = db_session.execute(
        text(
            """
            SELECT MIN(horodatage) AS debut FROM audit_log
            WHERE schema_audite = 'public' AND table_auditee = 'series_metadonnees'
              AND type_operation = 'I' AND id_ligne_auditee = ANY(:ids)
            """
        ),
        {"ids": [str(sid) for sid, _ in series.values()]},
    ).one()
    assert fenetre.debut is not None
    ligne_a_ligne = db_session.execute(
        text(
            """
            SELECT COUNT(*) FROM audit_log
            WHERE schema_audite = 'public' AND table_auditee = 'mesures_ressource'
              AND horodatage BETWEEN :debut AND :fin
              AND id_ligne_auditee NOT LIKE 'serie:%'
            """
        ),
        {"debut": fenetre.debut, "fin": max(e.horodatage for e in entrees)},
    ).scalar_one()
    assert ligne_a_ligne == 0
    extremites = (
        db_session.execute(
            text(
                """
            SELECT m.id::text FROM mesures_ressource m
            WHERE m.serie_id = ANY(:ids) AND m.valide_au IS NULL
              AND m.instant_mesure IN (DATE '1991-01-01', DATE '2001-01-01', DATE '2025-12-31')
            """
            ),
            {"ids": [sid for sid, _ in series.values()]},
        )
        .scalars()
        .all()
    )
    assert len(extremites) == 5 * 108 * 3 + 108 * 2  # 2001-01-01 est aussi un jour MERRA-2
    sans_audit = db_session.execute(
        text(
            """
            SELECT COUNT(*) FROM audit_log
            WHERE schema_audite = 'public' AND table_auditee = 'mesures_ressource'
              AND id_ligne_auditee = ANY(:lignes)
            """
        ),
        {"lignes": list(extremites)},
    ).scalar_one()
    assert sans_audit == 0


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_series_des_34_localites_intactes(db_session: Session, grandeur: str) -> None:
    """Les 204 séries journalières météo de 0035 restent fidèles à leur CSV.

    34 séries par grandeur, note du lot « pilotes + régions » inchangée, mêmes
    agrégats exacts que le CSV ``pilotes_regions`` ; une seule série journalière
    NASA par (grandeur, localité) sur les 142 localités.
    """
    codes = _codes(grandeur, _LOCALITES_34)
    notes = db_session.execute(
        text("SELECT code, note_publique FROM series_metadonnees WHERE code = ANY(:c)"),
        {"c": codes},
    ).all()
    assert len(notes) == 34
    assert all("(ADR-0020)" in r.note_publique for r in notes)
    assert not any("ADR-0031" in r.note_publique for r in notes)
    attendu = _agregats_csv(grandeur, LOT_METEO_JOURNALIER)
    base = _agregats_base(db_session, grandeur, codes)
    assert sorted(attendu) == sorted(base) == sorted(codes)
    ecarts = [c for c in codes if attendu[c] != base[c]]
    assert not ecarts, ecarts
    r = db_session.execute(
        text(
            """
            SELECT COUNT(*) AS series, COUNT(DISTINCT localite_id) AS localites
            FROM series_metadonnees
            WHERE source_id = 1 AND granularite = 'journalier' AND grandeur_code = :g
            """
        ),
        {"g": grandeur},
    ).one()
    assert r.series == r.localites == 142


def test_series_resolues_par_l_api(db_session: Session) -> None:
    """Les résolveurs de l'API trouvent ces séries aux 108 départements.

    ``_resoudre_serie_albedo_journalier`` (POA bifacial) et ``_chercher_serie_pluie_nasa``
    (salissure, fenêtre des PM EAC4) ; ``_chercher_serie_compagne`` depuis le GHI
    journalier NASA des départements quand il est gravé.
    """
    from kuma_data_core.api.v1.grandeurs import (
        _chercher_serie_compagne,
        _chercher_serie_pluie_salissure,
        _resoudre_serie_albedo_journalier,
        _resoudre_serie_source,
    )

    ids = {
        r.code: r.id
        for r in db_session.execute(
            text("SELECT code, id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": [c for g in _GRANDEURS for c in _codes(g)]},
        )
    }
    localites = {
        r.code: r.id
        for r in db_session.execute(
            text("SELECT code, id FROM localites WHERE code = ANY(:c)"), {"c": _LOCALITES}
        )
    }
    codes_ghi = [f"nasa_power_ghi_journalier_{code}" for code in _LOCALITES]
    ghi_presents = db_session.execute(
        text("SELECT COUNT(*) FROM series_metadonnees WHERE code = ANY(:c)"), {"c": codes_ghi}
    ).scalar_one()
    for code, localite_id in localites.items():
        assert (
            _resoudre_serie_albedo_journalier(db_session, localite_id, 1)
            == ids[f"nasa_power_albedo_surface_journalier_{code}"]
        )
        # La salissure ne prend jamais la pluie NASA (ADR-0032, ADR-0033).
        assert (
            _chercher_serie_pluie_salissure(
                db_session, localite_id, date(2021, 1, 1), date(2025, 8, 31)
            )
            != ids[f"nasa_power_precipitation_journalier_{code}"]
        )
        if ghi_presents:
            serie = _resoudre_serie_source(db_session, f"nasa_power_ghi_journalier_{code}")
            for g in ("t2m", "rh2m", "vent_2m", "vent_10m", "precipitation"):
                trouve = _chercher_serie_compagne(db_session, serie, g)
                assert trouve == ids[f"nasa_power_{g}_journalier_{code}"], (code, g)
