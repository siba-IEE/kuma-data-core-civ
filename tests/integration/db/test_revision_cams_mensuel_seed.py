"""Tests d'intégration de la révision du mensuel CAMS 2021-2025 (migration 0056, ADR-0037).

Versionnement temporel non destructif : pour chaque (série, année, mois) des 426
séries mensuelles CAMS dont la valeur servie le 2026-10-28 diffère de la valeur
gravée en 0030, la ligne gravée est close et une ligne courante la remplace,
marquée en commentaire éditorial. Mêmes règles pour les grandeurs dérivées du
mensuel CAMS (écarts CAMS - NASA, fraction diffuse, HEP, productible, kt).

Vérifie : valeurs courantes = CSV de révision, valeurs closes = CSV d'extension,
2005-2020 intact, une seule ligne courante par clé, comptes de lignes
versionnées, enchaînement des périodes de validité, ampleur de la révision
citée par les notes, cohérence retrouvée avec le journalier CAMS, grandeurs
dérivées versionnées seulement en 2021-2025 et sur les séries CAMS, notes
publiques, journal d'audit.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds.lots_civ import (
    CONTRATS_CAMS,
    LOT_EXTENSION,
    LOT_REVISION_CAMS,
    contrat_extension,
    points_nationaux,
)
from kuma_data_core.db.seeds.series_csv import lire_series

pytestmark = pytest.mark.integration

_GRANDEURS = ("ghi", "dni", "dhi")
_LOCALITES = sorted(code for code, _, _, _ in points_nationaux())
_MARQUEUR = "Révision CAMS du 2026-10-28 (migration 0056, ADR-0037)."
_NB_BRUTES = {"ghi": 8_489, "dni": 8_502, "dhi": 8_481}
# Révisé - gravé en 0030 sur les 142 x 60 mois : (moyenne, maximum de l'écart absolu).
_AMPLEUR = {"ghi": ("0.018", "0.118"), "dni": ("0.025", "0.154"), "dhi": ("-0.002", "0.031")}
_NB_DERIVEES = {
    "ecart_relatif_ghi_cams_nasa": 8_489,
    "ecart_relatif_dni_cams_nasa": 8_502,
    "ecart_relatif_dhi_cams_nasa": 8_481,
    "fraction_diffuse": 9_230,  # 8 520 mois + 710 années : DHI ou GHI révisé chaque fois
    "hep": 9_199,  # 8 489 mois au GHI révisé + 710 années
    "productible_specifique_theorique": 9_199,
    "kt": 9_199,
}


def _csv(grandeur: str, lot: str) -> dict[tuple[str, int, int], float]:
    contrat = contrat_extension(CONTRATS_CAMS[grandeur])
    return {(s["code"], a, m): v for s in lire_series(contrat, lot) for a, m, v in s["mesures"]}


def _lignes(db_session: Session, grandeur: str) -> list:
    return db_session.execute(
        text(
            """
            SELECT s.code, m.annee, m.mois, m.valeur, m.valide_du, m.valide_au,
                   m.commentaire_editorial, m.statut, m.niveau_confiance_derive
            FROM mesures_ressource_mensuelles m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code LIKE :p
            """
        ),
        {"p": f"cams_{grandeur}_mensuel_%"},
    ).all()


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_valeurs_courantes_et_closes(db_session: Session, grandeur: str) -> None:
    """Courantes 2021-2025 = révision ; closes = extension ; 2005-2020 intact."""
    revision = _csv(grandeur, LOT_REVISION_CAMS)
    extension = _csv(grandeur, LOT_EXTENSION)
    assert len(revision) == len(extension) == 142 * 60
    changees = {k for k, v in revision.items() if extension[k] != v}
    assert len(changees) == _NB_BRUTES[grandeur]
    lignes = _lignes(db_session, grandeur)
    courantes = {(r.code, r.annee, r.mois): r for r in lignes if r.valide_au is None}
    closes = {(r.code, r.annee, r.mois): r for r in lignes if r.valide_au is not None}
    assert len(courantes) == 142 * 21 * 12  # une seule ligne courante par clé
    assert set(closes) == changees  # rien d'autre n'est clos, 2005-2020 compris
    for cle, nouvelle in revision.items():
        r = courantes[cle]
        assert r.valeur == nouvelle
        if cle in changees:
            ancienne = closes[cle]
            assert ancienne.valeur == extension[cle]
            assert ancienne.valide_au == r.valide_du  # enchaînement sans trou ni chevauchement
            assert ancienne.commentaire_editorial is None
            assert (r.commentaire_editorial, r.statut, r.niveau_confiance_derive) == (
                _MARQUEUR,
                "brut",
                "B",
            )
        else:
            assert r.commentaire_editorial is None
    assert len({r.valide_du for r in courantes.values() if r.commentaire_editorial}) == 1


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_ampleur_de_la_revision(db_session: Session, grandeur: str) -> None:
    """Révisé - gravé, 142 x 60 mois (0 si inchangé) : chiffres de la note mensuelle."""
    row = db_session.execute(
        text(
            """
            SELECT COUNT(*) AS n,
                   AVG(c.valeur::numeric - COALESCE(a.valeur, c.valeur)::numeric) AS moyen,
                   MAX(ABS(c.valeur::numeric - COALESCE(a.valeur, c.valeur)::numeric)) AS maxi
            FROM mesures_ressource_mensuelles c
            JOIN series_metadonnees s ON s.id = c.serie_id
            LEFT JOIN mesures_ressource_mensuelles a
                ON a.serie_id = c.serie_id AND a.annee = c.annee AND a.mois = c.mois
               AND a.valide_au = c.valide_du
            WHERE s.code LIKE :p AND c.annee >= 2021 AND c.valide_au IS NULL
            """
        ),
        {"p": f"cams_{grandeur}_mensuel_%"},
    ).one()
    moyen, maxi = _AMPLEUR[grandeur]
    assert row.n == 142 * 60
    assert (round(row.moyen, 3), round(row.maxi, 3)) == (Decimal(moyen), Decimal(maxi))
    signe = "\u2212" if moyen.startswith("-") else "+"
    cite = f"{signe}{moyen.lstrip('-').replace('.', ',')} kWh/m²/jour en moyenne"
    cite += f" sur les 142 localités (jusqu'à {maxi.replace('.', ',')})"
    notes = db_session.execute(
        text("SELECT note_publique FROM series_metadonnees WHERE code LIKE :p"),
        {"p": f"cams_{grandeur}_mensuel_%"},
    ).scalars()
    assert all(cite in n for n in notes), cite


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_coherence_retrouvee_avec_le_journalier(db_session: Session, grandeur: str) -> None:
    """Moyenne des jours CAMS des mois complets 2021-2025 = mensuel courant à 0,0001 près."""
    ecart = db_session.execute(
        text(
            """
            WITH jours AS (
                SELECT s.localite_id, EXTRACT(YEAR FROM m.instant_mesure)::int AS annee,
                       EXTRACT(MONTH FROM m.instant_mesure)::int AS mois,
                       AVG(m.valeur::numeric) AS moy
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code LIKE :journalier AND m.instant_mesure >= '2021-01-01'
                GROUP BY 1, 2, 3
            )
            SELECT COUNT(*) AS n, MAX(ABS(j.moy - mm.valeur::numeric)) AS maxi
            FROM jours j
            JOIN localites l ON l.id = j.localite_id
            JOIN series_metadonnees sm ON sm.code = :mensuel || l.code
            JOIN mesures_ressource_mensuelles mm
                ON mm.serie_id = sm.id AND mm.annee = j.annee AND mm.mois = j.mois
               AND mm.valide_au IS NULL
            """
        ),
        {"journalier": f"cams_{grandeur}_journalier_%", "mensuel": f"cams_{grandeur}_mensuel_"},
    ).one()
    assert ecart.n == 142 * 60 and ecart.maxi < Decimal("0.0001")


def test_grandeurs_derivees_versionnees(db_session: Session) -> None:
    """Versions dérivées : comptes, seulement 2021-2025 et séries CAMS, enchaînement exact."""
    rows = db_session.execute(
        text(
            """
            SELECT n.grandeur_code, COUNT(*) AS n,
                   COUNT(*) FILTER (WHERE n.annee_debut < 2021) AS avant_2021,
                   COUNT(*) FILTER (WHERE s.code !~ '_cams_') AS hors_cams,
                   COUNT(*) FILTER (WHERE a.id IS NULL) AS sans_ancienne
            FROM grandeurs_metier n
            JOIN series_metadonnees s ON s.id = n.series_metadonnees_id
            LEFT JOIN grandeurs_metier a
                ON a.grandeur_code = n.grandeur_code AND a.localite_id = n.localite_id
               AND a.series_metadonnees_id = n.series_metadonnees_id
               AND a.periode_type = n.periode_type AND a.annee_debut = n.annee_debut
               AND a.mois IS NOT DISTINCT FROM n.mois AND a.version_formule = n.version_formule
               AND a.valide_au = n.valide_du
            WHERE n.commentaire_editorial = :m AND n.valide_au IS NULL
            GROUP BY n.grandeur_code
            """
        ),
        {"m": _MARQUEUR},
    ).all()
    assert {r.grandeur_code: r.n for r in rows} == _NB_DERIVEES
    assert all((r.avant_2021, r.hors_cams, r.sans_ancienne) == (0, 0, 0) for r in rows)
    closes = db_session.execute(
        text(
            "SELECT COUNT(*) FROM grandeurs_metier WHERE valide_au IS NOT NULL "
            "AND grandeur_code = ANY(:g)"
        ),
        {"g": list(_NB_DERIVEES)},
    ).scalar_one()
    assert closes == sum(_NB_DERIVEES.values())


def test_notes_publiques(db_session: Session) -> None:
    """Mise en garde mensuelle de la révision gravée, phrase journalière, séries dérivées."""
    for grandeur in _GRANDEURS:
        notes = db_session.execute(
            text("SELECT code, note_publique FROM series_metadonnees WHERE code LIKE :p"),
            {"p": f"cams_{grandeur}_%"},
        ).all()
        mensuelles = [n for c, n in notes if "_mensuel_" in c]
        journalieres = [n for c, n in notes if "_journalier_" in c]
        assert len(mensuelles) == len(journalieres) == 142
        assert all("Révision de la source (ADR-0037)" in n for n in mensuelles)
        assert all("migration 0056" in n and "(ADR-0035)" not in n for n in mensuelles)
        assert all("2021-2025 compris depuis la révision du mensuel" in n for n in journalieres)
    derivees = db_session.execute(
        text("SELECT COUNT(*) FROM series_metadonnees WHERE strpos(note_publique, :f) > 0"),
        {"f": "Recalculée sur 2021-2025 après la révision du mensuel CAMS"},
    ).scalar_one()
    assert derivees == 994


def test_journal_d_audit(db_session: Session) -> None:
    """Le mensuel est audité ligne à ligne : une entrée U par ligne close, une I par nouvelle.

    Seules les entrées de l'instant de la révision courante comptent : un
    aller-retour ``downgrade``/``upgrade`` laisse au journal celles du précédent.
    """
    rows = db_session.execute(
        text(
            """
            WITH revision AS (
                SELECT DISTINCT valide_du AS instant FROM mesures_ressource_mensuelles
                WHERE commentaire_editorial = :m AND valide_au IS NULL
            )
            SELECT a.type_operation, COUNT(*) AS n
            FROM audit_log a CROSS JOIN revision r
            WHERE a.schema_audite = 'public' AND a.table_auditee = 'mesures_ressource_mensuelles'
              AND CASE a.type_operation
                      WHEN 'I' THEN a.valeurs_apres ->> 'commentaire_editorial' = :m
                                    AND (a.valeurs_apres ->> 'valide_du')::timestamptz = r.instant
                      WHEN 'U' THEN (a.valeurs_apres ->> 'valide_au')::timestamptz = r.instant
                  END
            GROUP BY a.type_operation
            """
        ),
        {"m": _MARQUEUR},
    ).all()
    total = sum(_NB_BRUTES.values())
    assert {r.type_operation: r.n for r in rows} == {"I": total, "U": total}


def test_aucune_mesure_mensuelle_cams_avant_2021_close(db_session: Session) -> None:
    n = db_session.execute(
        text(
            """
            SELECT COUNT(*) FROM mesures_ressource_mensuelles m
            JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code ~ '^cams_(ghi|dni|dhi)_mensuel_' AND m.annee < 2021
              AND (m.valide_au IS NOT NULL OR m.commentaire_editorial IS NOT NULL)
            """
        )
    ).scalar_one()
    assert n == 0
