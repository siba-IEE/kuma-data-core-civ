"""Tests d'intégration du rayonnement journalier aux 108 départements (migration 0046, ADR-0031).

GHI 1991-2025, DNI et DHI 2001-2025 NASA POWER aux **108 départements** hors
pilotes (lot ``departements``), dans ``mesures_ressource`` : 324 séries et
3 352 968 mesures, gravées avec l'**audit par série**.

Volume oblige, la fidélité au CSV ne charge pas les mesures en Python : pour
chaque série, des agrégats **exacts** calculés en SQL ``numeric`` (nombre de
mesures, premier et dernier jour, Σ valeur, Σ rang du jour x valeur) sont
comparés aux mêmes agrégats recalculés en ``Decimal`` depuis les chaînes du CSV
gzip committé (relu ici directement, sans ``series_csv``). Les autres contrôles
sont des agrégats SQL : cohérence avec le mensuel NASA déjà gravé, DHI ≤ GHI
jour par jour, audit par série (une entrée par série, aucune ligne à ligne pour
ces mesures) et intégrité des 102 séries journalières du lot « pilotes +
régions » (34 localités).
"""

from __future__ import annotations

import csv
import gzip
import hashlib
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds.journalier_departements_civ import (
    CONTRATS_RAYONNEMENT_DEPARTEMENTS,
    LOT_JOURNALIER_DEPARTEMENTS,
    points_journalier_departements,
)
from kuma_data_core.db.seeds.lots_civ import (
    CONTRATS_NASA_JOURNALIERS,
    CONTRATS_NASA_JOURNALIERS_EXTENSION,
    LOT_EXTENSION,
    LOT_JOURNALIER,
    points_journalier,
)
from kuma_data_core.db.seeds.series_csv import DOSSIER_DONNEES

pytestmark = pytest.mark.integration

REVISION: str = "0046"
_DEPARTEMENTS = sorted(code for code, _, _, _ in points_journalier_departements())
_NOMS = {code: nom for code, nom, _, _ in points_journalier_departements()}
_LOT_34 = sorted(code for code, _, _, _ in points_journalier())

# Grandeur -> (paramètre NASA POWER, première année) ; dernière année : 2025.
_ATTENDU: dict[str, tuple[str, int]] = {
    "ghi": ("ALLSKY_SFC_SW_DWN", 1991),
    "dni": ("ALLSKY_SFC_SW_DNI", 2001),
    "dhi": ("ALLSKY_SFC_SW_DIFF", 2001),
}
_GRANDEURS = list(_ATTENDU)
_FIN: date = date(2025, 12, 31)


def _debut(grandeur: str) -> date:
    return date(_ATTENDU[grandeur][1], 1, 1)


def _nb_jours(grandeur: str) -> int:
    return (_FIN - _debut(grandeur)).days + 1


def _codes(grandeur: str, localites: list[str] | None = None) -> list[str]:
    return [f"nasa_power_{grandeur}_journalier_{code}" for code in localites or _DEPARTEMENTS]


def _fichier(grandeur: str) -> str:
    return f"nasa_power_{grandeur}_journalier_{LOT_JOURNALIER_DEPARTEMENTS}.csv.gz"


def _note(grandeur: str) -> str:
    parametre, annee = _ATTENDU[grandeur]
    return (
        f"{grandeur.upper()} journalier NASA POWER ({parametre}), kWh/m²/jour, {annee}-2025. "
        "Lot national « départements » (108 départements hors pilotes, ADR-0031), même "
        "contrat que le lot « pilotes + régions » (ADR-0016) ; la moyenne mensuelle des "
        "jours redonne la série mensuelle NASA. Confiance B (satellite)."
    )


@dataclass
class _Agregats:
    """Agrégats exacts d'une série : comparables entre SQL ``numeric`` et ``Decimal``."""

    n: int = 0
    premier: date | None = None
    dernier: date | None = None
    somme: Decimal = field(default_factory=Decimal)
    somme_rang: Decimal = field(default_factory=Decimal)


def _agreger_csv(fichiers: list[str], debut: date) -> dict[str, _Agregats]:
    """``{localité: agrégats}`` depuis les chaînes des CSV, rang du jour compté depuis ``debut``."""
    out: dict[str, _Agregats] = {}
    for nom in fichiers:
        with gzip.open(DOSSIER_DONNEES / nom, "rt", encoding="utf-8", newline="") as f:
            lecteur = csv.reader(f)
            assert next(lecteur) == ["localite_code", "latitude", "longitude", "date", "valeur"]
            for loc, _, _, jour_s, valeur_s in lecteur:
                jour, valeur = date.fromisoformat(jour_s), Decimal(valeur_s)
                assert valeur.as_tuple().exponent >= -4, (loc, jour_s, valeur_s)  # arrondi
                a = out.setdefault(loc, _Agregats())
                a.n += 1
                a.premier = jour if a.premier is None else min(a.premier, jour)
                a.dernier = jour if a.dernier is None else max(a.dernier, jour)
                a.somme += valeur
                a.somme_rang += ((jour - debut).days + 1) * valeur
    return out


def _agreger_base(session: Session, codes: list[str], debut: date) -> dict[str, _Agregats]:
    """Mêmes agrégats, en SQL ``numeric`` (mesures courantes), par code de série."""
    rows = session.execute(
        text(
            """
            SELECT s.code, COUNT(*) AS n, MIN(m.instant_mesure) AS premier,
                   MAX(m.instant_mesure) AS dernier,
                   SUM(m.valeur::numeric) AS somme,
                   SUM((m.instant_mesure - CAST(:debut AS date) + 1) * m.valeur::numeric)
                       AS somme_rang,
                   COUNT(*) FILTER (WHERE m.statut <> 'brut'
                                       OR m.niveau_confiance_derive <> 'B') AS hors_contrat
            FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c) AND m.valide_au IS NULL
            GROUP BY s.code
            """
        ),
        {"c": codes, "debut": debut},
    ).all()
    assert all(r.hors_contrat == 0 for r in rows)
    return {r.code: _Agregats(r.n, r.premier, r.dernier, r.somme, r.somme_rang) for r in rows}


def test_perimetre_et_contrats() -> None:
    """108 départements disjoints du lot de 34 ; contrats GHI 1991, DNI et DHI 2001, à 2025."""
    assert len(_DEPARTEMENTS) == 108 and not set(_DEPARTEMENTS) & set(_LOT_34)
    assert set(CONTRATS_RAYONNEMENT_DEPARTEMENTS) == set(_ATTENDU)
    for g, c in CONTRATS_RAYONNEMENT_DEPARTEMENTS.items():
        assert (c.annee_debut, c.annee_fin, c.granularite) == (_ATTENDU[g][1], 2025, "journalier")
        assert c.nom_fichier(LOT_JOURNALIER_DEPARTEMENTS) == _fichier(g)


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_series_journalieres(db_session: Session, grandeur: str) -> None:
    """108 séries par grandeur : source, méthode, période, libellé et note du lot."""
    rows = db_session.execute(
        text(
            """
            SELECT s.code, loc.code AS localite, s.libelle, s.note_publique, s.granularite,
                   s.methode_collecte, s.periode_debut, s.periode_fin, s.actif,
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
    assert sorted(r.localite for r in rows) == _DEPARTEMENTS
    annee = _ATTENDU[grandeur][1]
    for r in rows:
        assert r.code == f"nasa_power_{grandeur}_journalier_{r.localite}"
        assert r.libelle == (
            f"{grandeur.upper()} journalier NASA POWER — {_NOMS[r.localite]} ({annee}-2025)"
        )
        assert r.note_publique == _note(grandeur)
        assert (r.source, r.granularite, r.methode_collecte, r.unite, r.actif) == (
            "nasa_power",
            "journalier",
            "modele_satellitaire",
            "kwh_par_m2_jour",
            True,
        )
        assert (r.periode_debut, r.periode_fin) == (_debut(grandeur), _FIN)


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_mesures_fideles_au_csv(db_session: Session, grandeur: str) -> None:
    """Par série : n, premier et dernier jour, Σ valeur, Σ rang x valeur exacts (CSV = base)."""
    debut = _debut(grandeur)
    attendu = _agreger_csv([_fichier(grandeur)], debut)
    assert sorted(attendu) == _DEPARTEMENTS
    base = _agreger_base(db_session, _codes(grandeur), debut)
    assert len(base) == 108
    for loc, a in attendu.items():
        assert (a.n, a.premier, a.dernier) == (_nb_jours(grandeur), debut, _FIN), loc
        assert base[f"nasa_power_{grandeur}_journalier_{loc}"] == a, loc
    assert sum(a.n for a in base.values()) == 108 * _nb_jours(grandeur)


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_coherence_avec_le_mensuel(db_session: Session, grandeur: str) -> None:
    """Moyenne des jours de chaque mois = série mensuelle NASA gravée, à 5·10⁻⁴ près."""
    row = db_session.execute(
        text(
            """
            WITH jour AS (
                SELECT s.localite_id, EXTRACT(YEAR FROM m.instant_mesure)::int AS annee,
                       EXTRACT(MONTH FROM m.instant_mesure)::int AS mois,
                       AVG(m.valeur::numeric) AS moyenne, COUNT(*) AS n
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:c) AND m.valide_au IS NULL
                GROUP BY 1, 2, 3
            )
            SELECT COUNT(*) AS mois,
                   COUNT(*) FILTER (WHERE abs(j.moyenne - mm.valeur::numeric) >= 0.0005)
                       AS ecarts,
                   MAX(abs(j.moyenne - mm.valeur::numeric)) AS ecart_max,
                   COUNT(*) FILTER (
                       WHERE j.n <> EXTRACT(DAY FROM make_date(j.annee, j.mois, 1)
                                                     + INTERVAL '1 month - 1 day')
                   ) AS incomplets
            FROM jour j
            JOIN series_metadonnees sm
                ON sm.localite_id = j.localite_id AND sm.grandeur_code = :g
               AND sm.granularite = 'mensuel'
            JOIN sources src ON src.id = sm.source_id AND src.code = 'nasa_power'
            JOIN mesures_ressource_mensuelles mm
                ON mm.serie_id = sm.id AND mm.annee = j.annee AND mm.mois = j.mois
               AND mm.valide_au IS NULL
            """
        ),
        {"c": _codes(grandeur), "g": grandeur},
    ).one()
    assert row.mois == 108 * (2025 - _ATTENDU[grandeur][1] + 1) * 12
    assert row.incomplets == 0
    assert row.ecarts == 0 and row.ecart_max < Decimal("0.0005")


def test_dhi_jamais_superieur_au_ghi_journalier(db_session: Session) -> None:
    """DHI ≤ GHI jour par jour (2001-2025) : regroupement (localité, jour), sans auto-jointure."""
    row = db_session.execute(
        text(
            """
            SELECT COUNT(*) FILTER (WHERE dhi IS NOT NULL AND ghi IS NOT NULL) AS paires,
                   COUNT(*) FILTER (WHERE dhi > ghi) AS violations
            FROM (
                SELECT s.localite_id, m.instant_mesure,
                       MAX(m.valeur) FILTER (WHERE s.grandeur_code = 'dhi') AS dhi,
                       MAX(m.valeur) FILTER (WHERE s.grandeur_code = 'ghi') AS ghi
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:codes) AND m.valide_au IS NULL
                GROUP BY s.localite_id, m.instant_mesure
            ) t
            """
        ),
        {"codes": _codes("dhi") + _codes("ghi")},
    ).one()
    assert row.paires == 108 * _nb_jours("dhi")
    assert row.violations == 0


def test_audit_par_serie(db_session: Session) -> None:
    """Une entrée d'audit par série (I, révision 0046, comptes, bornes, CSV et SHA-256) ;
    aucune entrée ligne à ligne pour ces mesures ; les séries gardent l'audit par ligne."""
    codes = [c for g in _GRANDEURS for c in _codes(g)]
    empreintes = {
        g: hashlib.sha256((DOSSIER_DONNEES / _fichier(g)).read_bytes()).hexdigest()
        for g in _GRANDEURS
    }
    rows = db_session.execute(
        text(
            """
            SELECT s.code, s.grandeur_code AS g, a.type_operation, a.valeurs_apres,
                   a.valeurs_avant
            FROM series_metadonnees s
            JOIN audit_log a
              ON a.schema_audite = 'public' AND a.table_auditee = 'mesures_ressource'
             AND a.id_ligne_auditee = 'serie:' || s.id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": codes},
    ).all()
    assert sorted(r.code for r in rows) == sorted(codes)  # exactement une entrée par série
    for r in rows:
        assert r.type_operation == "I" and r.valeurs_avant is None
        assert r.valeurs_apres == {
            "audit": "par_serie",
            "revision": REVISION,
            "serie_code": r.code,
            "nb_mesures": _nb_jours(r.g),
            "premier_instant": _debut(r.g).isoformat(),
            "dernier_instant": _FIN.isoformat(),
            "fichier": _fichier(r.g),
            "sha256": empreintes[r.g],
        }

    # Aucune entrée ligne à ligne dont l'identifiant tombe dans la plage de ces mesures
    # (sur-ensemble exact : identifiants ``id`` de ``mesures_ressource``, en texte).
    lignes = db_session.execute(
        text(
            """
            WITH mes AS (
                SELECT MIN(m.id) AS bas, MAX(m.id) AS haut, COUNT(*) AS n
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:c)
            )
            SELECT mes.n,
                   (SELECT COUNT(*) FROM audit_log a
                    WHERE a.schema_audite = 'public' AND a.table_auditee = 'mesures_ressource'
                      AND a.id_ligne_auditee ~ '^[0-9]+$'
                      AND a.id_ligne_auditee::bigint BETWEEN mes.bas AND mes.haut) AS audits
            FROM mes
            """
        ),
        {"c": codes},
    ).one()
    assert lignes.n == 108 * sum(_nb_jours(g) for g in _GRANDEURS) == 3_352_968
    assert lignes.audits == 0

    series = db_session.execute(
        text(
            """
            SELECT COUNT(DISTINCT s.id) AS n
            FROM series_metadonnees s
            JOIN audit_log a
              ON a.schema_audite = 'public' AND a.table_auditee = 'series_metadonnees'
             AND a.id_ligne_auditee = s.id::text AND a.type_operation = 'I'
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": codes},
    ).scalar_one()
    assert series == 324


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_lot_pilotes_regions_intact(db_session: Session, grandeur: str) -> None:
    """Les 34 séries du lot « pilotes + régions » restent intactes, sans doublon de localité."""
    par_localite = db_session.execute(
        text(
            """
            SELECT loc.code AS localite, COUNT(*) AS n
            FROM series_metadonnees s
            JOIN sources src ON src.id = s.source_id AND src.code = 'nasa_power'
            JOIN localites loc ON loc.id = s.localite_id
            WHERE s.granularite = 'journalier' AND s.grandeur_code = :g
            GROUP BY loc.code
            """
        ),
        {"g": grandeur},
    ).all()
    assert sorted(r.localite for r in par_localite) == sorted(_LOT_34 + _DEPARTEMENTS)
    assert all(r.n == 1 for r in par_localite)

    codes = _codes(grandeur, _LOT_34)
    metadonnees = db_session.execute(
        text(
            "SELECT note_publique, periode_debut, periode_fin FROM series_metadonnees "
            "WHERE code = ANY(:c)"
        ),
        {"c": codes},
    ).all()
    assert len(metadonnees) == 34
    for r in metadonnees:
        assert "« pilotes + régions » (ADR-0016)" in r.note_publique
        assert "ADR-0031" not in r.note_publique
        assert (r.periode_debut, r.periode_fin) == (_debut(grandeur), _FIN)

    debut = _debut(grandeur)
    base_csv = CONTRATS_NASA_JOURNALIERS[grandeur].nom_fichier(LOT_JOURNALIER)
    extension = CONTRATS_NASA_JOURNALIERS_EXTENSION[grandeur].nom_fichier(LOT_EXTENSION)
    attendu = _agreger_csv([base_csv, extension], debut)
    assert sorted(attendu) == _LOT_34
    base = _agreger_base(db_session, codes, debut)
    for loc, a in attendu.items():
        assert (a.n, a.premier, a.dernier) == (_nb_jours(grandeur), debut, _FIN), loc
        assert base[f"nasa_power_{grandeur}_journalier_{loc}"] == a, loc
