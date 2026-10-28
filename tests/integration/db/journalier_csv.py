"""Agrégats exacts des séries journalières, depuis les CSV gzip et depuis la base.

Fidélité base = CSV sans charger les mesures en Python : par série, nombre de
jours gravés, premier et dernier jour, Σ valeur et Σ rang * valeur, en
``Decimal`` depuis les chaînes du CSV et en ``numeric`` côté base (le ``float8``
y revient exactement). Les jours sans valeur (lacunes explicites d'un contrat à
``lacunes_admises``) ne sont pas gravés : ils ne comptent pas dans les agrégats
et sont rendus à part.
"""

from __future__ import annotations

import csv
import gzip
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from functools import cache

from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds.series_csv import COLONNES_JOURNALIERES, DOSSIER_DONNEES

Agregats = tuple[int, date, date, Decimal, Decimal]


@cache
def agregats_csv(
    fichier: str, prefixe: str, debut: date
) -> tuple[dict[str, Agregats], dict[str, tuple[date, ...]]]:
    """``({code série: agrégats}, {code série: jours sans valeur})`` d'un CSV journalier.

    Le rang du jour compte à partir de 1 à ``debut``.
    """
    nombre: Counter[str] = Counter()
    premier: dict[str, date] = {}
    dernier: dict[str, date] = {}
    somme: defaultdict[str, Decimal] = defaultdict(Decimal)
    somme_rang: defaultdict[str, Decimal] = defaultdict(Decimal)
    lacunes: defaultdict[str, list[date]] = defaultdict(list)
    with gzip.open(DOSSIER_DONNEES / fichier, "rt", encoding="utf-8", newline="") as f:
        lecteur = csv.reader(f)
        assert tuple(next(lecteur)) == COLONNES_JOURNALIERES
        for loc, _, _, jour_s, valeur_s in lecteur:
            code, jour = f"{prefixe}_{loc}", date.fromisoformat(jour_s)
            if valeur_s == "":
                lacunes[code].append(jour)
                continue
            valeur = Decimal(valeur_s)
            nombre[code] += 1
            premier[code] = min(premier.get(code, jour), jour)
            dernier[code] = max(dernier.get(code, jour), jour)
            somme[code] += valeur
            somme_rang[code] += ((jour - debut).days + 1) * valeur
    agregats = {c: (nombre[c], premier[c], dernier[c], somme[c], somme_rang[c]) for c in nombre}
    return agregats, {c: tuple(j) for c, j in lacunes.items()}


def agregats_base(db_session: Session, codes: list[str], debut: date) -> dict[str, Agregats]:
    """Mêmes agrégats en base, mesures courantes (``valide_au IS NULL``)."""
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


def entrees_audit_par_serie(db_session: Session, ids: list[int]) -> dict[int, dict[str, object]]:
    """Dernière entrée d'audit ``I`` par série (``id_ligne_auditee = 'serie:<id>'``)."""
    rows = db_session.execute(
        text(
            """
            SELECT DISTINCT ON (id_ligne_auditee) id_ligne_auditee, valeurs_apres, valeurs_avant
            FROM audit_log
            WHERE schema_audite = 'public' AND table_auditee = 'mesures_ressource'
              AND type_operation = 'I' AND id_ligne_auditee = ANY(:cles)
            ORDER BY id_ligne_auditee, horodatage DESC
            """
        ),
        {"cles": [f"serie:{i}" for i in ids]},
    ).all()
    sortie: dict[int, dict[str, object]] = {}
    for r in rows:
        assert r.valeurs_avant is None
        sortie[int(r.id_ligne_auditee.removeprefix("serie:"))] = r.valeurs_apres
    return sortie


def lignes_auditees_ligne_a_ligne(db_session: Session, ids: list[int]) -> int:
    """Entrées d'audit ligne à ligne de ``mesures_ressource`` pour la 1ʳᵉ et la dernière mesure."""
    return int(
        db_session.execute(
            text(
                """
                WITH bornes AS (
                    SELECT serie_id, MIN(id) AS premiere, MAX(id) AS derniere
                    FROM mesures_ressource WHERE serie_id = ANY(:ids) GROUP BY serie_id
                )
                SELECT COUNT(*) FROM audit_log a JOIN bornes b
                    ON a.id_ligne_auditee IN (b.premiere::text, b.derniere::text)
                WHERE a.schema_audite = 'public' AND a.table_auditee = 'mesures_ressource'
                """
            ),
            {"ids": ids},
        ).scalar_one()
    )
