"""derivees_journalieres_departements

Revision ID: 0049
Revises: 0048
Create Date: 2026-10-15

**Grandeurs dérivées du journalier aux 108 départements** (ADR-0031), depuis le
GHI journalier (0046) et la météo journalière (0047) NASA POWER du lot
départements. Mêmes définitions, versions de formule et politiques de
complétude que pour les 34 localités du lot « pilotes + régions » :

- ``variabilite_journaliere`` (ADR-0024, migration 0039) : coefficient de
  variation **annuel** du GHI journalier (écart-type de population / moyenne),
  années civiles complètes, 1991-2025 → **108 séries, 3 780 lignes** ;
- ``humidex`` (ADR-0030, migration 0045) : moyenne des humidex journaliers
  (Masterton & Richardson 1979, constantes de Magnus 6,112 / 17,67 / 243,5),
  **mensuel et annuel**, périodes complètes sur l'intersection T2M ∩ RH2M,
  1991-2025 → **108 séries, 45 360 lignes mensuelles et 3 780 annuelles**.

Calcul en SQL hors-ligne, agrégats en ``numeric`` (reproductibles au bit près).
Garde-fous limités aux séries du lot : séries amont présentes et conformes,
aucune série cible préexistante, comptes exacts, domaines de sanité. Les lignes
de ``grandeurs_metier`` gardent l'audit ligne à ligne (volume modeste).
``ANALYZE`` en fin de migration ; ``downgrade`` supprime lignes puis séries.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.journalier_departements_civ import (
    CONTRATS_METEO_DEPARTEMENTS,
    CONTRATS_RAYONNEMENT_DEPARTEMENTS,
    NB_DEPARTEMENTS,
    points_journalier_departements,
)

# revision identifiers, used by Alembic.
revision: str = "0049"
down_revision: str | Sequence[str] | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ANNEE_DEBUT: int = 1991
ANNEE_FIN: int = 2025
NB_ANNEES: int = 35
NB_MOIS: int = 420
SOURCE_CALCUL: str = "kuma_calculs"

# Même mise en garde que les séries humidex du lot pilotes + régions (0045).
MISE_EN_GARDE_HUMIDEX: str = (
    " Mise en garde : l'humidex 2024-2025 dépasse de 0,81 °C la moyenne 2016-2023 "
    "(34 localités), sous l'effet de la T2M NASA (+0,87 °C), dont la hausse n'est pas "
    "confirmée par ERA5 (+0,21 °C contre +0,85 °C pour NASA sur 142 localités, "
    "ADR-0021) ; NASA POWER signale un changement de source de sa météo (MERRA-2, "
    "GEOS-IT). Aucune tendance à en tirer sans recoupement."
)

# grandeur -> (id, unité, préfixe de code, libellé, note publique)
GRANDEURS: dict[str, tuple[int, str, str, str, str]] = {
    "variabilite_journaliere": (
        5,
        "sans_unite",
        "variabilite_journaliere_nasa_power",
        "Variabilité journalière du GHI NASA POWER",
        "Coefficient de variation annuel du GHI journalier NASA POWER (écart-type de "
        f"population / moyenne des jours de l'année), sans dimension, {ANNEE_DEBUT}-"
        f"{ANNEE_FIN}. Année gravée seulement si tous ses jours civils sont présents. "
        "Annuel uniquement : un mois est trop court pour un coefficient de variation "
        "robuste. Lot départements (ADR-0031). Confiance B (entrée satellite B). ADR-0024.",
    ),
    "humidex": (
        15,
        "degree_celsius",
        "humidex_nasa_power",
        "Humidex moyen NASA POWER",
        "Humidex moyen NASA POWER, en °C apparents, mensuel et annuel "
        f"{ANNEE_DEBUT}-{ANNEE_FIN} : moyenne arithmétique des humidex journaliers "
        "(Masterton & Richardson 1979, constantes de Magnus 6,112 / 17,67 / 243,5), "
        "calculés depuis la température (T2M) et l'humidité relative (RH2M) moyennes "
        "du jour NASA POWER (réanalyse MERRA-2). Mois et année gravés seulement si "
        "tous leurs jours civils ont T2M et RH2M. Indice de la journée moyenne, pas "
        "du pic de l'après-midi. Lot départements (ADR-0031). Confiance B (réanalyse). "
        "ADR-0030." + MISE_EN_GARDE_HUMIDEX,
    ),
}

# grandeur -> (lignes mensuelles, lignes annuelles, borne basse, borne haute) attendues
BILANS: dict[str, tuple[int, int, float, float]] = {
    "variabilite_journaliere": (0, NB_DEPARTEMENTS * NB_ANNEES, 0.0, 1.0),
    "humidex": (NB_DEPARTEMENTS * NB_MOIS, NB_DEPARTEMENTS * NB_ANNEES, 10.0, 50.0),
}


def codes_series(grandeur: str) -> list[str]:
    """Codes des séries calculées d'une grandeur aux 108 départements."""
    prefixe = GRANDEURS[grandeur][2]
    return [f"{prefixe}_{code}" for code, _, _, _ in points_journalier_departements()]


def _amont(grandeur: str) -> list[str]:
    contrats = {**CONTRATS_RAYONNEMENT_DEPARTEMENTS, **CONTRATS_METEO_DEPARTEMENTS}
    return [
        contrats[grandeur].code_serie(code) for code, _, _, _ in points_journalier_departements()
    ]


def _verifier_amont(bind: sa.Connection, grandeur: str) -> None:
    row = bind.execute(
        sa.text(
            """
            SELECT COUNT(*) AS n,
                   COUNT(*) FILTER (
                       WHERE s.granularite = 'journalier' AND s.grandeur_code = :g
                         AND src.code = 'nasa_power'
                         AND s.periode_debut = :debut AND s.periode_fin = :fin
                   ) AS conformes
            FROM series_metadonnees s JOIN sources src ON src.id = s.source_id
            WHERE s.code = ANY(:c)
            """
        ),
        {
            "g": grandeur,
            "c": _amont(grandeur),
            "debut": f"{ANNEE_DEBUT}-01-01",
            "fin": f"{ANNEE_FIN}-12-31",
        },
    ).one()
    if (row.n, row.conformes) != (NB_DEPARTEMENTS, NB_DEPARTEMENTS):
        raise RuntimeError(f"Migration 0049 : séries {grandeur} journalières amont {tuple(row)!r}.")


def _creer_series(bind: sa.Connection, grandeur: str, loc: dict[str, int]) -> None:
    gid, unite, prefixe, libelle, note = GRANDEURS[grandeur]
    row = bind.execute(
        sa.text(
            "SELECT g.id, g.famille, g.strategie_calcul, g.version_formule_actuelle, "
            "u.code AS unite FROM grandeurs_referentiel g JOIN unites u ON u.id = g.unite_id "
            "WHERE g.code = :c"
        ),
        {"c": grandeur},
    ).one_or_none()
    if row is None or tuple(row) != (gid, "F1", "stockee", 1, unite):
        raise RuntimeError(f"Migration 0049 : grandeur {grandeur!r} hors contrat : {row!r}.")
    preexistantes = bind.execute(
        sa.text("SELECT COUNT(*) FROM series_metadonnees WHERE code = ANY(:c)"),
        {"c": codes_series(grandeur)},
    ).scalar_one()
    if preexistantes:
        raise RuntimeError(f"Migration 0049 : {preexistantes} séries {grandeur} déjà présentes.")
    source_calcul_id = bind.execute(
        sa.text("SELECT id FROM sources WHERE code = :c"), {"c": SOURCE_CALCUL}
    ).scalar_one()
    op.bulk_insert(
        sa.table(
            "series_metadonnees",
            sa.column("code", sa.String),
            sa.column("libelle", sa.Text),
            sa.column("localite_id", sa.BigInteger),
            sa.column("grandeur_code", sa.String),
            sa.column("source_id", sa.BigInteger),
            sa.column("periode_debut", sa.Date),
            sa.column("periode_fin", sa.Date),
            sa.column("methode_collecte", sa.String),
            sa.column("granularite", sa.String),
            sa.column("note_publique", sa.Text),
        ),
        [
            {
                "code": f"{prefixe}_{code}",
                "libelle": f"{libelle} — {nom} ({ANNEE_DEBUT}-{ANNEE_FIN})",
                "localite_id": loc[code],
                "grandeur_code": grandeur,
                "source_id": source_calcul_id,
                "periode_debut": f"{ANNEE_DEBUT}-01-01",
                "periode_fin": f"{ANNEE_FIN}-12-31",
                "methode_collecte": "calcul_derive",
                "granularite": None,
                "note_publique": note,
            }
            for code, nom, _, _ in points_journalier_departements()
        ],
    )


def _bilan(bind: sa.Connection, grandeur: str) -> None:
    mensuel, annuel, bmin, bmax = BILANS[grandeur]
    row = bind.execute(
        sa.text(
            """
            SELECT COUNT(*) FILTER (WHERE gm.periode_type = 'mensuel') AS mensuel,
                   COUNT(*) FILTER (WHERE gm.periode_type = 'annuel') AS annuel,
                   COUNT(DISTINCT gm.series_metadonnees_id) AS series,
                   MIN(gm.annee_debut) AS debut, MAX(gm.annee_debut) AS fin,
                   COUNT(*) FILTER (WHERE NOT (gm.valeur > :bmin AND gm.valeur < :bmax))
                       AS hors_domaine
            FROM grandeurs_metier gm JOIN series_metadonnees s ON s.id = gm.series_metadonnees_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": codes_series(grandeur), "bmin": bmin, "bmax": bmax},
    ).one()
    attendu = (mensuel, annuel, NB_DEPARTEMENTS, ANNEE_DEBUT, ANNEE_FIN, 0)
    if tuple(row) != attendu:
        raise RuntimeError(f"Migration 0049 : {grandeur} : {tuple(row)!r}, {attendu!r} attendu.")


def upgrade() -> None:
    bind = op.get_bind()
    points = points_journalier_departements()
    loc = {
        r.code: r.id
        for r in bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:c)"),
            {"c": [code for code, _, _, _ in points]},
        ).all()
    }
    if len(loc) != NB_DEPARTEMENTS:
        raise RuntimeError(f"Migration 0049 : {len(loc)} localités, {NB_DEPARTEMENTS} attendues.")
    for grandeur in ("ghi", "t2m", "rh2m"):
        _verifier_amont(bind, grandeur)

    # 1. Variabilité journalière : σ_pop / μ des GHI journaliers, années complètes.
    _creer_series(bind, "variabilite_journaliere", loc)
    bind.execute(
        sa.text(
            """
            WITH jours AS (
                SELECT sv.id AS serie_cible, sv.localite_id,
                       EXTRACT(YEAR FROM m.instant_mesure)::int AS annee,
                       m.valeur::numeric AS ghi
                FROM series_metadonnees sv
                JOIN series_metadonnees sg
                    ON sg.localite_id = sv.localite_id AND sg.grandeur_code = 'ghi'
                   AND sg.granularite = 'journalier' AND sg.code = ANY(:amont)
                JOIN mesures_ressource m
                    ON m.serie_id = sg.id AND m.valide_au IS NULL AND m.statut <> 'deprecie'
                WHERE sv.code = ANY(:codes)
            )
            INSERT INTO grandeurs_metier (
                grandeur_code, localite_id, series_metadonnees_id, periode_type,
                annee_debut, annee_fin, mois, version_formule, valeur,
                niveau_confiance_derive
            )
            SELECT 'variabilite_journaliere', localite_id, serie_cible, 'annuel',
                   annee, annee, NULL, 1,
                   -- numeric : stddev_pop et avg exacts, indépendants de l'ordre.
                   (stddev_pop(ghi) / avg(ghi))::float8, 'B'
            FROM jours
            GROUP BY localite_id, serie_cible, annee
            HAVING COUNT(*) = make_date(annee + 1, 1, 1) - make_date(annee, 1, 1)
               AND avg(ghi) > 0
            """
        ),
        {"codes": codes_series("variabilite_journaliere"), "amont": _amont("ghi")},
    )
    _bilan(bind, "variabilite_journaliere")

    # 2. Humidex : moyenne des humidex journaliers, mensuel et annuel (ROLLUP).
    _creer_series(bind, "humidex", loc)
    bind.execute(
        sa.text(
            """
            WITH jours AS (
                SELECT sh.id AS serie_cible, sh.localite_id,
                       EXTRACT(YEAR FROM mt.instant_mesure)::int AS annee,
                       EXTRACT(MONTH FROM mt.instant_mesure)::int AS mois,
                       mt.valeur::numeric AS t, mr.valeur::numeric AS rh
                FROM series_metadonnees sh
                JOIN series_metadonnees st
                    ON st.localite_id = sh.localite_id AND st.grandeur_code = 't2m'
                   AND st.granularite = 'journalier' AND st.code = ANY(:amont_t2m)
                JOIN mesures_ressource mt
                    ON mt.serie_id = st.id AND mt.valide_au IS NULL AND mt.statut <> 'deprecie'
                JOIN series_metadonnees sr
                    ON sr.localite_id = sh.localite_id AND sr.grandeur_code = 'rh2m'
                   AND sr.granularite = 'journalier' AND sr.code = ANY(:amont_rh2m)
                JOIN mesures_ressource mr
                    ON mr.serie_id = sr.id AND mr.instant_mesure = mt.instant_mesure
                   AND mr.valide_au IS NULL AND mr.statut <> 'deprecie'
                WHERE sh.code = ANY(:codes)
            ),
            humidex AS (
                -- e = (RH/100)·6,112·exp(17,67·T / (T + 243,5)) ; H = T + 5/9·(e − 10).
                SELECT serie_cible, localite_id, annee, mois,
                       t + (rh / 100 * 6.112 * exp(17.67 * t / (t + 243.5)) - 10) * 5 / 9 AS h
                FROM jours
            )
            INSERT INTO grandeurs_metier (
                grandeur_code, localite_id, series_metadonnees_id, periode_type,
                annee_debut, annee_fin, mois, version_formule, valeur,
                niveau_confiance_derive
            )
            SELECT 'humidex', localite_id, serie_cible,
                   CASE WHEN GROUPING(mois) = 0 THEN 'mensuel' ELSE 'annuel' END,
                   annee, annee, mois, 1, avg(h)::float8, 'B'
            FROM humidex
            GROUP BY localite_id, serie_cible, annee, ROLLUP (mois)
            HAVING COUNT(*) = CASE
                WHEN GROUPING(mois) = 0
                    THEN (make_date(annee, mois, 1) + INTERVAL '1 month')::date
                         - make_date(annee, mois, 1)
                ELSE make_date(annee + 1, 1, 1) - make_date(annee, 1, 1)
            END
            """
        ),
        {
            "codes": codes_series("humidex"),
            "amont_t2m": _amont("t2m"),
            "amont_rh2m": _amont("rh2m"),
        },
    )
    _bilan(bind, "humidex")
    bind.execute(sa.text("ANALYZE grandeurs_metier"))


def downgrade() -> None:
    bind = op.get_bind()
    codes = codes_series("variabilite_journaliere") + codes_series("humidex")
    bind.execute(
        sa.text(
            "DELETE FROM grandeurs_metier WHERE series_metadonnees_id IN "
            "(SELECT id FROM series_metadonnees WHERE code = ANY(:c))"
        ),
        {"c": codes},
    )
    bind.execute(sa.text("DELETE FROM series_metadonnees WHERE code = ANY(:c)"), {"c": codes})
