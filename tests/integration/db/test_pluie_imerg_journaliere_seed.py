"""Tests d'intégration de la pluie journalière GPM IMERG aux 142 localités (migration 0052).

Source ``gpm_imerg`` (id 17, créée par 0052) et 142 séries
``gpm_imerg_precipitation_journalier_<localité>`` dans ``mesures_ressource``,
1998-2025 (10 227 jours), méthode ``modele_satellitaire``, confiance B : IMERG
V07 servi par NASA POWER (``IMERG_PRECTOT``), jour UTC, maille 0,1° contenant
la localité, valeurs telles que servies (2 décimales).

Vérifie le contrat, la source et les métadonnées, la **fidélité exacte** au CSV
gzip committé par agrégats par série — nombre, premier et dernier jour, somme
des valeurs et somme pondérée par le rang du jour, en ``numeric`` côté base et
en ``Decimal`` depuis les chaînes du CSV (aucune mesure chargée en Python) —,
les 120 séries distinctes (maille 0,1°), les chiffres du recoupement cités par
la note publique, l'**audit par série** (une entrée par série, aucune entrée
ligne à ligne pour ces mesures) et l'intégrité des séries de pluie
journalières existantes (NASA POWER, ERA5).
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
from kuma_data_core.db.seeds.pluie_era5_journaliere_civ import (
    CONTRAT_PLUIE_ERA5_JOURNALIERE,
    LOT_PLUIE_ERA5_JOURNALIERE,
)
from kuma_data_core.db.seeds.pluie_imerg_civ import (
    CONTRAT_PLUIE_IMERG,
    DEBUT_CALAGE_GPM,
    DECIMALES_SERVIES,
    DERNIER_JOUR_FINAL_RUN,
    LOT_PLUIE_IMERG,
    PARAMETRE_POWER,
    SOURCE_CODE,
    SOURCE_ID,
    STANDARD_TEMPS,
    UNITE_REFERENTIEL,
    UNITE_SERVIE,
)
from kuma_data_core.db.seeds.series_csv import DOSSIER_DONNEES, nb_jours

pytestmark = pytest.mark.integration

_CONTRAT = CONTRAT_PLUIE_IMERG
_LOCALITES = sorted(code for code, _, _, _ in points_nationaux())
_DEBUT, _FIN = date(1998, 1, 1), date(2025, 12, 31)
_NB_JOURS = 10_227
_NB_DISTINCTES = 120
_REVISION = "0052"
_PREFIXE_NASA = "nasa_power_precipitation_journalier"

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
    """Contrat IMERG journalier : source, méthode, période, borne, lot, faits de l'API."""
    c = _CONTRAT
    assert (c.source_code, c.source_id, c.source_libelle) == (
        "gpm_imerg",
        17,
        "GPM IMERG (POWER)",
    )
    assert (SOURCE_CODE, SOURCE_ID) == ("gpm_imerg", 17)
    assert c.prefixe_code == "gpm_imerg_precipitation_journalier"
    assert (c.grandeur_code, c.methode_collecte, c.niveau_confiance) == (
        "precipitation",
        "modele_satellitaire",
        "B",
    )
    assert (c.annee_debut, c.annee_fin, c.granularite) == (1998, 2025, "journalier")
    assert c.borne_max == 1000.0
    assert nb_jours(c) == _NB_JOURS
    assert LOT_PLUIE_IMERG == "civ142"
    assert c.nom_fichier(LOT_PLUIE_IMERG) == "gpm_imerg_precipitation_journalier_civ142.csv.gz"
    assert (PARAMETRE_POWER, STANDARD_TEMPS, UNITE_SERVIE, UNITE_REFERENTIEL) == (
        "IMERG_PRECTOT",
        "UTC",
        "mm/day",
        "mm_par_jour",
    )
    assert DECIMALES_SERVIES == 2
    assert DERNIER_JOUR_FINAL_RUN.isoformat() == "2025-09-30"
    assert DEBUT_CALAGE_GPM.isoformat() == "2014-06-01"
    assert len(_LOCALITES) == 142


def test_source(db_session: Session) -> None:
    """Source ``gpm_imerg`` à id figé 17 : identité, canal, citation et notes sourcées."""
    r = db_session.execute(
        text(
            """
            SELECT id, code, titre, auteurs, organisation, type_source, annee_publication,
                   date_consultation, url, doi, fiabilite, langue, metadonnees, notes, actif
            FROM sources WHERE code = :c
            """
        ),
        {"c": SOURCE_CODE},
    ).one()
    assert (r.id, r.type_source, r.fiabilite, r.langue, r.actif) == (
        17,
        "base_donnees",
        "haute",
        "en",
        True,
    )
    assert r.auteurs == [
        "Huffman, G.J.",
        "Stocker, E.F.",
        "Bolvin, D.T.",
        "Nelkin, E.J.",
        "Tan, J.",
    ]
    assert (r.annee_publication, r.date_consultation) == (2023, date(2026, 10, 15))
    assert r.doi == "10.5067/GPM/IMERGDF/DAY/07"
    assert r.url == "https://power.larc.nasa.gov/api/temporal/daily/point"
    assert "IMERG V07" in r.titre and "IMERG_PRECTOT" in r.titre and "Late Run" in r.titre
    assert "GES DISC" in r.organisation and "NASA POWER" in r.organisation
    md = r.metadonnees
    assert md["parametre_power"] == "IMERG_PRECTOT"
    assert md["couverture_temporelle_debut"] == "1998-01-01"
    assert md["fin_final_run_v07"] == DERNIER_JOUR_FINAL_RUN.isoformat()
    assert md["debut_documente_power"].startswith("2001-01-01 selon la page des sources")
    assert md["integration_power"].startswith("2025-03-04, version de données POWER 10.0.5")
    assert all(u.startswith("https://") for u in md["documentation"])
    for fragment in (
        "GPCC",
        "0,1°",
        "jour UTC",
        "2025-03-04",
        "10.0.5",
        "2025-09-30",
        "Late Run",
        "TRMM",
        "MERRA-2 Total Precipitation",
        "ADR-0032, ADR-0033",
        "Prediction Of Worldwide Energy Resources",
    ):
        assert fragment in r.notes, fragment
    # Une seule source à cet id ; la séquence d'identité n'est pas touchée.
    assert db_session.execute(text("SELECT COUNT(*) FROM sources WHERE id = 17")).scalar_one() == 1


def test_series_metadonnees(db_session: Session) -> None:
    """142 séries : source, méthode, granularité, période, unité, libellé et note sourcée."""
    rows = db_session.execute(
        text(
            """
            SELECT s.code, s.libelle, s.grandeur_code, s.methode_collecte, s.granularite,
                   s.periode_debut, s.periode_fin, s.note_publique, s.actif, s.source_id,
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
        assert (r.source, r.source_id) == ("gpm_imerg", 17)
        assert r.grandeur_code == "precipitation" and r.actif
        assert r.methode_collecte == "modele_satellitaire" and r.granularite == "journalier"
        assert (r.periode_debut, r.periode_fin) == (_DEBUT, _FIN)
        assert r.unite == "mm_par_jour"
        assert r.libelle == f"Précipitations journalier GPM IMERG (POWER) — {r.nom} (1998-2025)"
        assert "IMERG_PRECTOT" in r.note_publique
        assert "maille 0,1° contenant la localité, jour UTC" in r.note_publique
        assert "Final Run jusqu'au 2025-09-30" in r.note_publique
        assert "du 2025-10-01 au 2025-12-31, Late Run" in r.note_publique
        assert "épisodes de pluie journaliers" in r.note_publique
        assert "ADR-0032, ADR-0033" in r.note_publique and "Confiance B" in r.note_publique
    assert len({r.note_publique for r in rows}) == 1


def test_mesures_fideles_au_csv(db_session: Session) -> None:
    """Par série : nombre, bornes, Σ valeur et Σ rang * valeur exacts, base = CSV.

    Les valeurs sont celles servies, à 2 décimales au plus (aucun arrondi ni
    conversion), sans valeur de remplissage, dans les bornes du contrat.
    """
    attendu = _agregats_csv(_CONTRAT.nom_fichier(LOT_PLUIE_IMERG), _CONTRAT.prefixe_code, _DEBUT)
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
                   COUNT(*) FILTER (WHERE m.valeur::numeric <> ROUND(m.valeur::numeric, 2))
                       AS plus_de_2_decimales,
                   MIN(m.valeur) AS mini, MAX(m.valeur) AS maxi
            FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": _codes()},
    ).one()
    assert (r.n, r.hors_contrat, r.plus_de_2_decimales) == (142 * _NB_JOURS, 0, 0)
    assert 0.0 <= r.mini <= r.maxi <= _CONTRAT.borne_max
    assert r.maxi == 235.02  # Adiaké, 2002-08-06


def test_series_distinctes(db_session: Session) -> None:
    """120 séries distinctes sur 142 localités : POWER sert la maille 0,1° du point."""
    base = _agregats_base(db_session, _codes(), _DEBUT)
    assert len(base) == 142
    assert len(set(base.values())) == _NB_DISTINCTES
    # Une région et le département de son chef-lieu partagent souvent la même maille.
    assert base[_CONTRAT.code_serie("civ_poro")] == base[_CONTRAT.code_serie("civ_dep_korhogo")]


def test_recoupement_cite_par_la_note(db_session: Session) -> None:
    """Chiffres du recoupement IMERG / NASA POWER cités par la note publique.

    Aux 25 jours-localités où NASA dépasse 200 mm, IMERG donne au plus 59,4 mm
    le jour même et 107,93 mm sur trois jours ; jours-localités > 50 mm par an :
    IMERG 325,5 (1998-2015) puis 322,1 (2017-2025), NASA 22,4 puis 247,6.
    """
    codes_nasa = [f"{_PREFIXE_NASA}_{code}" for code in _LOCALITES]
    r = db_session.execute(
        text(
            """
            WITH i AS (
                SELECT s.localite_id, m.instant_mesure AS jour, m.valeur::numeric AS v
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:imerg)
            ), n AS (
                SELECT s.localite_id, m.instant_mesure AS jour, m.valeur::numeric AS v
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:nasa) AND m.instant_mesure >= :debut
            ), extremes AS (
                SELECT n.localite_id, n.jour,
                       MAX(i.v) FILTER (WHERE i.jour = n.jour) AS jour_meme,
                       SUM(i.v) AS trois_jours
                FROM n JOIN i ON i.localite_id = n.localite_id
                             AND i.jour BETWEEN n.jour - 1 AND n.jour + 1
                WHERE n.v > 200
                GROUP BY n.localite_id, n.jour
            )
            SELECT (SELECT COUNT(*) FROM extremes) AS jours,
                   (SELECT MAX(jour_meme) FROM extremes) AS imerg_jour_max,
                   (SELECT MAX(trois_jours) FROM extremes) AS imerg_3j_max,
                   (SELECT COUNT(*) FROM i WHERE v > 50 AND jour < '2016-01-01') AS i_avant,
                   (SELECT COUNT(*) FROM i WHERE v > 50 AND jour >= '2017-01-01') AS i_apres,
                   (SELECT COUNT(*) FROM n WHERE v > 50 AND jour < '2016-01-01') AS n_avant,
                   (SELECT COUNT(*) FROM n WHERE v > 50 AND jour >= '2017-01-01') AS n_apres
            """
        ),
        {"imerg": _codes(), "nasa": codes_nasa, "debut": _DEBUT},
    ).one()
    assert (r.jours, r.imerg_jour_max, r.imerg_3j_max) == (25, Decimal("59.4"), Decimal("107.93"))
    par_an = [round(Decimal(x) / annees, 1) for x, annees in ((r.i_avant, 18), (r.i_apres, 9))]
    assert par_an == [Decimal("325.5"), Decimal("322.1")]
    par_an_nasa = [round(Decimal(x) / annees, 1) for x, annees in ((r.n_avant, 18), (r.n_apres, 9))]
    assert par_an_nasa == [Decimal("22.4"), Decimal("247.6")]


def test_audit_par_serie(db_session: Session) -> None:
    """Une entrée d'audit par série (``I``, révision 0052) ; aucune entrée ligne à ligne.

    L'absence d'audit ligne à ligne est vérifiée de deux façons : (1) aucune
    entrée ``mesures_ressource`` ordinaire dans la fenêtre de la migration (de
    l'audit des séries insérées à la dernière entrée par série) ; (2) aucune
    entrée pour la première et la dernière mesure de chaque série. La source et
    les séries gardent l'audit ligne à ligne ; le trigger d'audit de
    ``mesures_ressource`` est réactivé.
    """
    ids = _ids(db_session)
    assert len(ids) == 142
    entrees = db_session.execute(
        text(
            """
            SELECT DISTINCT ON (id_ligne_auditee)
                   id_ligne_auditee, valeurs_apres, valeurs_avant, horodatage
            FROM audit_log
            WHERE schema_audite = 'public' AND table_auditee = 'mesures_ressource'
              AND type_operation = 'I' AND id_ligne_auditee = ANY(:cles)
            ORDER BY id_ligne_auditee, horodatage DESC
            """
        ),
        {"cles": [f"serie:{i}" for i in ids.values()]},
    ).all()
    assert sorted(e.id_ligne_auditee for e in entrees) == sorted(f"serie:{i}" for i in ids.values())
    par_cle = {e.id_ligne_auditee: e for e in entrees}
    fichier = _CONTRAT.nom_fichier(LOT_PLUIE_IMERG)
    empreinte = empreinte_fichier(_CONTRAT, LOT_PLUIE_IMERG)
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

    # La source est auditée ligne à ligne, comme les séries.
    source_auditee = db_session.execute(
        text(
            """
            SELECT COUNT(*) FROM audit_log
            WHERE schema_audite = 'public' AND table_auditee = 'sources'
              AND type_operation = 'I' AND id_ligne_auditee = '17'
            """
        )
    ).scalar_one()
    assert source_auditee >= 1

    # (1) Fenêtre de la migration : audit (ligne à ligne) des séries insérées → audit par série.
    debut_fenetre = db_session.execute(
        text(
            """
            SELECT MAX(horodatage), COUNT(DISTINCT id_ligne_auditee) FROM audit_log
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
    """Pluie journalière NASA POWER (0035, 0047) et ERA5 (0050) inchangées.

    Mêmes agrégats exacts que leurs CSV ; une seule série journalière de pluie par
    source et localité, pour trois sources ; aucune autre série sur la source 17.
    """
    debut = date(1991, 1, 1)
    attendu_nasa: dict[str, Agregats] = {}
    for lot in ("pilotes_regions", "departements"):
        attendu_nasa |= _agregats_csv(f"{_PREFIXE_NASA}_{lot}.csv.gz", _PREFIXE_NASA, debut)
    codes_nasa = [f"{_PREFIXE_NASA}_{code}" for code in _LOCALITES]
    assert sorted(attendu_nasa) == sorted(codes_nasa)
    base_nasa = _agregats_base(db_session, codes_nasa, debut)
    assert [c for c in codes_nasa if attendu_nasa[c] != base_nasa.get(c)] == []

    era5 = CONTRAT_PLUIE_ERA5_JOURNALIERE
    attendu_era5 = _agregats_csv(
        era5.nom_fichier(LOT_PLUIE_ERA5_JOURNALIERE), era5.prefixe_code, debut
    )
    codes_era5 = [era5.code_serie(code) for code in _LOCALITES]
    assert sorted(attendu_era5) == sorted(codes_era5)
    base_era5 = _agregats_base(db_session, codes_era5, debut)
    assert [c for c in codes_era5 if attendu_era5[c] != base_era5.get(c)] == []

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
        "gpm_imerg": (142, 142),
    }
    sur_source = db_session.execute(
        text("SELECT COUNT(*) FROM series_metadonnees WHERE source_id = :s"), {"s": SOURCE_ID}
    ).scalar_one()
    assert sur_source == 142


def test_identite_des_sources_recalee(db_session: Session) -> None:
    """La prochaine source insérée sans id ne heurte pas les ids figés 16 et 17."""
    row = db_session.execute(
        text("SELECT last_value, (SELECT MAX(id) FROM sources) AS maxi FROM sources_id_seq")
    ).one()
    assert row.last_value >= row.maxi == 17
