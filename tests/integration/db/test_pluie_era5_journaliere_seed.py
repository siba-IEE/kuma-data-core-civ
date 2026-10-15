"""Tests d'intégration de la pluie journalière ERA5 du CDS aux 142 localités (migration 0050).

142 séries ``ecmwf_era5_precipitation_journalier_<localité>`` dans
``mesures_ressource``, 1991-2025 (12 784 jours), source ``ecmwf_era5`` (id 2),
méthode ``reanalyse``, confiance B : cumul du jour civil UTC
(``derived-era5-single-levels-daily-statistics``, ``daily_sum``), au point de
grille 0,25° le plus proche, comme le mensuel 0036.

Vérifie le contrat et les métadonnées, la **fidélité exacte** au CSV gzip
committé par agrégats par série — nombre, premier et dernier jour, somme des
valeurs et somme pondérée par le rang du jour, en ``numeric`` côté base et en
``Decimal`` depuis les chaînes du CSV (aucune mesure chargée en Python) —, une
série par maille 0,25° (110), la **cohérence avec le mensuel ERA5** de 0036
(moyenne des jours du mois), l'**audit par série** (une entrée par série, aucune
entrée ligne à ligne pour ces mesures) et l'intégrité des séries de pluie
existantes (NASA POWER journalière, ERA5 mensuelle), résolveur de pluie de
l'API compris.
"""

from __future__ import annotations

import csv
import gzip
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from functools import cache

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds.audit_par_serie import empreinte_fichier
from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.meteo_era5_civ import (
    CONTRATS_METEO_ERA5_MENSUELS,
    LOT_METEO_ERA5,
    maille_era5,
)
from kuma_data_core.db.seeds.pluie_era5_journaliere_civ import (
    CONTRAT_PLUIE_ERA5_JOURNALIERE,
    LOT_PLUIE_ERA5_JOURNALIERE,
    MOIS_TRANSITION_ERA5,
    cumul_journalier_mm,
)
from kuma_data_core.db.seeds.series_csv import DOSSIER_DONNEES

pytestmark = pytest.mark.integration

_CONTRAT = CONTRAT_PLUIE_ERA5_JOURNALIERE
_POINTS = {code: (lat, lon) for code, _, lat, lon in points_nationaux()}
_LOCALITES = sorted(_POINTS)
_DEBUT, _FIN = date(1991, 1, 1), date(2025, 12, 31)
_NB_JOURS = 12_784
_REVISION = "0050"

# Moyenne des jours du mois - mensuel ERA5 de 0036 (mm/jour), constats de
# l'ingestion (``scripts/ingest_era5_cds_journalier.py``) :
# - hors mois de raccord entre expériences de production ERA5, au plus 0,00355
#   sur 57 226 mois (arrondi des produits du CDS) ; un calage des cumuls sur
#   00 h → 23 h donnerait jusqu'à 0,48 ;
# - dans 13 des 17 mois de raccord, le mensuel du CDS s'écarte de la somme des
#   cumuls horaires, jusqu'à 0,386 (Tengréla, 1995-09) ; incohérence de la
#   source, constatée aussi sur le jeu horaire sur grille.
_TOLERANCE_MENSUEL = 0.004
_ECART_MAX_RACCORD = 0.4
_RACCORDS_ECARTES: frozenset[tuple[int, int]] = frozenset(
    {
        (1993, 8),
        (1995, 9),
        (2000, 1),
        (2000, 10),
        (2001, 10),
        (2002, 10),
        (2003, 10),
        (2004, 10),
        (2005, 10),
        (2006, 10),
        (2008, 1),
        (2010, 1),
        (2019, 3),
    }
)

Agregats = tuple[int, date, date, Decimal, Decimal]


def _codes(localites: list[str] = _LOCALITES) -> list[str]:
    return [_CONTRAT.code_serie(code) for code in localites]


@cache
def _agregats_csv(fichier: str, prefixe: str, debut: date) -> dict[str, Agregats]:
    """Agrégats exacts par série depuis les chaînes d'un CSV journalier, relu directement.

    ``{code série: (nombre, premier jour, dernier jour, Σ valeur, Σ rang * valeur)}``,
    le rang du jour comptant à partir de 1 à ``debut``.
    """
    nombre: Counter[str] = Counter()
    premier: dict[str, date] = {}
    dernier: dict[str, date] = {}
    somme: defaultdict[str, Decimal] = defaultdict(Decimal)
    somme_rang: defaultdict[str, Decimal] = defaultdict(Decimal)
    with gzip.open(DOSSIER_DONNEES / fichier, "rt", encoding="utf-8", newline="") as f:
        lecteur = csv.reader(f)
        assert next(lecteur) == ["localite_code", "latitude", "longitude", "date", "valeur"]
        for loc, _, _, jour_s, valeur_s in lecteur:
            code, jour, valeur = f"{prefixe}_{loc}", date.fromisoformat(jour_s), Decimal(valeur_s)
            nombre[code] += 1
            premier[code] = min(premier.get(code, jour), jour)
            dernier[code] = max(dernier.get(code, jour), jour)
            somme[code] += valeur
            somme_rang[code] += ((jour - debut).days + 1) * valeur
    return {c: (nombre[c], premier[c], dernier[c], somme[c], somme_rang[c]) for c in nombre}


def _agregats_base(db_session: Session, codes: list[str], debut: date) -> dict[str, Agregats]:
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
            WHERE s.code = ANY(:c) AND m.valide_au IS NULL
            GROUP BY s.code
            """
        ),
        {"c": codes, "debut": debut},
    ).all()
    for r in rows:
        assert r.n == r.distincts, r.code  # un seul jour par date
    return {r.code: (r.n, r.premier, r.dernier, r.somme, r.somme_rang) for r in rows}


def _ids(db_session: Session) -> dict[str, int]:
    return {
        r.code: r.id
        for r in db_session.execute(
            text("SELECT code, id FROM series_metadonnees WHERE code = ANY(:c)"), {"c": _codes()}
        )
    }


def test_contrat() -> None:
    """Contrat ERA5 journalier : source, méthode, période, borne, même lot que le mensuel."""
    c = _CONTRAT
    assert (c.source_code, c.source_id, c.source_libelle) == ("ecmwf_era5", 2, "ERA5 (CDS)")
    assert c.prefixe_code == "ecmwf_era5_precipitation_journalier"
    assert (c.grandeur_code, c.methode_collecte, c.niveau_confiance) == (
        "precipitation",
        "reanalyse",
        "B",
    )
    assert (c.annee_debut, c.annee_fin, c.granularite) == (1991, 2025, "journalier")
    assert c.borne_max == 1000.0
    assert LOT_PLUIE_ERA5_JOURNALIERE == LOT_METEO_ERA5 == "civ142"
    assert c.nom_fichier(LOT_PLUIE_ERA5_JOURNALIERE) == (
        "ecmwf_era5_precipitation_journalier_civ142.csv.gz"
    )
    # 24 cumuls horaires (m) datés 01 h (J) → 00 h (J + 1), somme exacte en mm.
    assert cumul_journalier_mm([0.0005] * 24) == pytest.approx(12.0)
    with pytest.raises(ValueError):
        cumul_journalier_mm([0.0] * 23)
    assert _RACCORDS_ECARTES <= MOIS_TRANSITION_ERA5
    assert len(_LOCALITES) == 142


def test_series_metadonnees(db_session: Session) -> None:
    """142 séries : source, méthode, granularité, période, unité, libellé et note sourcée."""
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
        {"c": _codes()},
    ).all()
    assert sorted(r.localite for r in rows) == _LOCALITES
    for r in rows:
        assert r.code == _CONTRAT.code_serie(r.localite)
        assert r.source == "ecmwf_era5" and r.grandeur_code == "precipitation" and r.actif
        assert r.methode_collecte == "reanalyse" and r.granularite == "journalier"
        assert (r.periode_debut, r.periode_fin) == (_DEBUT, _FIN)
        assert r.unite == "mm_par_jour"
        assert r.libelle == f"Précipitations journalier ERA5 (CDS) — {r.nom} (1991-2025)"
        assert "reanalysis-era5-single-levels" in r.note_publique
        assert "01 h le jour même à 00 h le lendemain" in r.note_publique
        assert "même maille que la série mensuelle ERA5 (0036)" in r.note_publique
        assert "13 mois de raccord entre expériences de production ERA5" in r.note_publique
        assert "ADR-0032" in r.note_publique and "Confiance B" in r.note_publique
        assert "Copernicus Climate Change Service" in r.note_publique  # attribution
    assert len({r.note_publique for r in rows}) == 1


def test_mesures_fideles_au_csv(db_session: Session) -> None:
    """Par série : nombre, bornes, Σ valeur et Σ rang * valeur exacts, base = CSV."""
    attendu = _agregats_csv(
        _CONTRAT.nom_fichier(LOT_PLUIE_ERA5_JOURNALIERE), _CONTRAT.prefixe_code, _DEBUT
    )
    assert sorted(attendu) == sorted(_codes())
    for n, premier, dernier, _, _ in attendu.values():
        assert (n, premier, dernier) == (_NB_JOURS, _DEBUT, _FIN)
    base = _agregats_base(db_session, _codes(), _DEBUT)
    ecarts = [c for c in attendu.keys() | base.keys() if attendu.get(c) != base.get(c)]
    assert not ecarts, sorted(ecarts)[:10]
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
        {"c": _codes()},
    ).one()
    assert (r.n, r.hors_contrat) == (142 * _NB_JOURS, 0)
    assert 0.0 <= r.mini <= r.maxi <= _CONTRAT.borne_max


def test_une_maille_une_serie(db_session: Session) -> None:
    """Deux localités de la même maille 0,25° portent la même série ; 110 séries distinctes."""
    base = _agregats_base(db_session, _codes(), _DEBUT)
    par_maille: defaultdict[tuple[float, float], set[Agregats]] = defaultdict(set)
    for code, (lat, lon) in _POINTS.items():
        par_maille[maille_era5(lat, lon)].add(base[_CONTRAT.code_serie(code)])
    assert all(len(v) == 1 for v in par_maille.values())
    assert len(par_maille) == len({next(iter(v)) for v in par_maille.values()}) == 110


def test_coherence_avec_le_mensuel(db_session: Session) -> None:
    """Moyenne des jours du mois = pluie mensuelle ERA5 de 0036, même maille.

    Agrégé en SQL, par mois : 59 640 paires (142 localités, 420 mois), aucun
    orphelin. Hors mois de raccord entre expériences ERA5, écart sous la
    tolérance et écart moyen quasi nul (pas de décalage horaire des cumuls).
    Les mois au-delà de la tolérance sont exactement les 13 raccords écartés
    constatés, bornés : si le CDS corrige son mensuel, ce test le dira.
    """
    codes_mois = [
        CONTRATS_METEO_ERA5_MENSUELS["precipitation"].code_serie(code) for code in _LOCALITES
    ]
    rows = db_session.execute(
        text(
            """
            WITH jour AS (
                SELECT s.localite_id, EXTRACT(YEAR FROM m.instant_mesure)::int AS annee,
                       EXTRACT(MONTH FROM m.instant_mesure)::int AS mois,
                       AVG(m.valeur::numeric) AS moyenne
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:jour) AND m.valide_au IS NULL
                GROUP BY 1, 2, 3
            ), mensuel AS (
                SELECT sm.localite_id, mm.annee, mm.mois, mm.valeur::numeric AS valeur
                FROM series_metadonnees sm
                JOIN mesures_ressource_mensuelles mm ON mm.serie_id = sm.id
                WHERE sm.code = ANY(:mois) AND mm.valide_au IS NULL
            )
            SELECT COALESCE(j.annee, x.annee) AS annee, COALESCE(j.mois, x.mois) AS mois,
                   COUNT(*) AS paires,
                   COUNT(*) FILTER (WHERE j.moyenne IS NULL OR x.valeur IS NULL) AS orphelins,
                   MAX(ABS(j.moyenne - x.valeur)) AS ecart_max,
                   SUM(j.moyenne - x.valeur) AS ecart_somme
            FROM jour j
            FULL JOIN mensuel x
                ON x.localite_id = j.localite_id AND x.annee = j.annee AND x.mois = j.mois
            GROUP BY 1, 2
            """
        ),
        {"jour": _codes(), "mois": codes_mois},
    ).all()
    assert len(rows) == 420
    assert sum(r.paires for r in rows) == 142 * 420
    assert sum(r.orphelins for r in rows) == 0
    hors_raccord = [r for r in rows if (r.annee, r.mois) not in MOIS_TRANSITION_ERA5]
    assert max(r.ecart_max for r in hors_raccord) <= Decimal(str(_TOLERANCE_MENSUEL))
    moyen = sum(r.ecart_somme for r in hors_raccord) / (142 * len(hors_raccord))
    assert abs(moyen) < Decimal("0.0001"), moyen
    ecartes = {(r.annee, r.mois) for r in rows if r.ecart_max > Decimal(str(_TOLERANCE_MENSUEL))}
    assert ecartes == _RACCORDS_ECARTES
    assert max(r.ecart_max for r in rows) <= Decimal(str(_ECART_MAX_RACCORD))


def test_audit_par_serie(db_session: Session) -> None:
    """Une entrée d'audit par série (``I``, révision 0050) ; aucune entrée ligne à ligne.

    L'absence d'audit ligne à ligne est vérifiée de deux façons : (1) aucune
    entrée ``mesures_ressource`` ordinaire dans la fenêtre de la migration (de
    l'audit des séries insérées à la dernière entrée par série) ; (2) aucune
    entrée pour la première et la dernière mesure de chaque série. Le trigger
    d'audit de ``mesures_ressource`` est réactivé.
    """
    ids = _ids(db_session)
    assert len(ids) == 142
    entrees = db_session.execute(
        text(
            """
            SELECT id_ligne_auditee, type_operation, valeurs_apres, valeurs_avant, horodatage
            FROM audit_log
            WHERE schema_audite = 'public' AND table_auditee = 'mesures_ressource'
              AND type_operation = 'I' AND id_ligne_auditee = ANY(:cles)
            """
        ),
        {"cles": [f"serie:{i}" for i in ids.values()]},
    ).all()
    assert sorted(e.id_ligne_auditee for e in entrees) == sorted(f"serie:{i}" for i in ids.values())
    par_cle = {e.id_ligne_auditee: e for e in entrees}
    fichier = _CONTRAT.nom_fichier(LOT_PLUIE_ERA5_JOURNALIERE)
    empreinte = empreinte_fichier(_CONTRAT, LOT_PLUIE_ERA5_JOURNALIERE)
    for code, sid in ids.items():
        entree = par_cle[f"serie:{sid}"]
        assert entree.valeurs_avant is None
        assert entree.valeurs_apres == {
            "audit": "par_serie",
            "revision": _REVISION,
            "serie_code": code,
            "nb_mesures": _NB_JOURS,
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
    assert debut_fenetre[1] == 142
    lignes_fenetre = db_session.execute(
        text(
            """
            SELECT COUNT(*) FROM audit_log
            WHERE schema_audite = 'public' AND table_auditee = 'mesures_ressource'
              AND horodatage BETWEEN :debut AND :fin AND id_ligne_auditee NOT LIKE 'serie:%'
            """
        ),
        {"debut": debut_fenetre[0], "fin": max(e.horodatage for e in entrees)},
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
    assert len(bornes) == 142
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


def test_series_de_pluie_existantes_intactes(db_session: Session) -> None:
    """Pluie NASA POWER journalière (0035, 0047) et ERA5 mensuelle (0036) inchangées.

    Mêmes agrégats exacts que leurs CSV ; une seule série journalière de pluie par
    source et localité ; le résolveur de pluie de l'API (salissure), épinglé sur
    NASA POWER, continue de la trouver aux 142 localités.
    """
    from kuma_data_core.api.v1.grandeurs import _chercher_serie_pluie_nasa

    prefixe_nasa = "nasa_power_precipitation_journalier"
    attendu_nasa: dict[str, Agregats] = {}
    for lot in ("pilotes_regions", "departements"):
        attendu_nasa |= _agregats_csv(f"{prefixe_nasa}_{lot}.csv.gz", prefixe_nasa, _DEBUT)
    codes_nasa = [f"{prefixe_nasa}_{code}" for code in _LOCALITES]
    assert sorted(attendu_nasa) == sorted(codes_nasa)
    base_nasa = _agregats_base(db_session, codes_nasa, _DEBUT)
    assert [c for c in codes_nasa if attendu_nasa[c] != base_nasa.get(c)] == []

    mensuel = CONTRATS_METEO_ERA5_MENSUELS["precipitation"]
    somme_csv: defaultdict[str, Decimal] = defaultdict(Decimal)
    nb_csv: Counter[str] = Counter()
    chemin = DOSSIER_DONNEES / mensuel.nom_fichier(LOT_METEO_ERA5)
    with gzip.open(chemin, "rt", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            code = mensuel.code_serie(r["localite_code"])
            somme_csv[code] += Decimal(r["valeur"])
            nb_csv[code] += 1
    rows = db_session.execute(
        text(
            """
            SELECT s.code, COUNT(*) AS n, SUM(m.valeur::numeric) AS somme
            FROM mesures_ressource_mensuelles m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c) AND m.valide_au IS NULL
            GROUP BY s.code
            """
        ),
        {"c": [mensuel.code_serie(code) for code in _LOCALITES]},
    ).all()
    assert {r.code: (r.n, r.somme) for r in rows} == {
        c: (nb_csv[c], somme_csv[c]) for c in somme_csv
    }

    par_source = db_session.execute(
        text(
            """
            SELECT src.code AS source, COUNT(*) AS series, COUNT(DISTINCT s.localite_id) AS loc
            FROM series_metadonnees s JOIN sources src ON src.id = s.source_id
            WHERE s.grandeur_code = 'precipitation' AND s.granularite = 'journalier'
            GROUP BY src.code
            """
        )
    ).all()
    assert {r.source: (r.series, r.loc) for r in par_source} == {
        "nasa_power": (142, 142),
        "ecmwf_era5": (142, 142),
    }

    nasa_ids = {
        r.localite_id: r.id
        for r in db_session.execute(
            text("SELECT localite_id, id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": codes_nasa},
        )
    }
    for localite_id, serie_id in nasa_ids.items():
        assert (
            _chercher_serie_pluie_nasa(db_session, localite_id, date(2021, 1, 1), date(2025, 8, 31))
            == serie_id
        )
