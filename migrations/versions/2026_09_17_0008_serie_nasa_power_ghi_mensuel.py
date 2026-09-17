"""serie_nasa_power_ghi_mensuel

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-17

Première ingestion de donnée solaire brute (Jalon 2) : GHI mensuel **NASA
POWER**, climatologie **1991-2020**, à 3 points ivoiriens (départements
d'Abidjan, Yamoussoukro, Korhogo — sud / centre / nord). Voir le contrat de
série ADR-0007.

- ``series_metadonnees`` : une série par point (source ``nasa_power``,
  grandeur ``ghi``, granularité ``mensuel``, méthode ``modele_satellitaire``,
  période 1991-01-01 → 2020-12-31). ``localite_id`` et ``source_id`` résolus
  depuis la base (localités posées en 0003-0007, source seedée en 0002).
- ``mesures_ressource_mensuelles`` : 360 mesures par série (12 mois sur 30 ans),
  ``valeur`` = moyenne journalière du mois en kWh/m²/jour (unité fixée par la
  grandeur ``ghi`` -> ``kwh_par_m2_jour``), ``statut='brut'``,
  ``niveau_confiance_derive='B'`` (satellite/réanalyse ; A réservé au sol).

Les valeurs proviennent du seed ``series_nasa_power_ghi_mensuel_civ`` (généré
hors-ligne par ``scripts/ingest_nasa_power_ghi_mensuel.py`` ; la migration
n'accède jamais au réseau — cf. README). ``downgrade`` supprime les mesures
puis les séries.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.series_nasa_power_ghi_mensuel_civ import (
    GRANDEUR_CODE,
    GRANULARITE,
    METHODE_COLLECTE,
    NIVEAU_CONFIANCE,
    PERIODE_DEBUT,
    PERIODE_FIN,
    SERIES,
    SOURCE_CODE,
)

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CODES_SERIES: tuple[str, ...] = tuple(s["code"] for s in SERIES)


def upgrade() -> None:
    bind = op.get_bind()

    source_id = bind.execute(
        sa.text("SELECT id FROM sources WHERE code = :c"), {"c": SOURCE_CODE}
    ).scalar_one_or_none()
    if source_id is None:
        raise RuntimeError(f"Migration 0008 : source {SOURCE_CODE!r} introuvable (seed 0002).")

    codes_loc = sorted({s["localite_code"] for s in SERIES})
    loc = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:c)"), {"c": codes_loc}
        ).all()
    }
    manquants = [c for c in codes_loc if c not in loc]
    if manquants:
        raise RuntimeError(f"Migration 0008 : localité(s) introuvable(s) : {manquants!r}.")

    series_table = sa.table(
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
    )
    op.bulk_insert(
        series_table,
        [
            {
                "code": s["code"],
                "libelle": s["libelle"],
                "localite_id": loc[s["localite_code"]],
                "grandeur_code": GRANDEUR_CODE,
                "source_id": source_id,
                "periode_debut": PERIODE_DEBUT,
                "periode_fin": PERIODE_FIN,
                "methode_collecte": METHODE_COLLECTE,
                "granularite": GRANULARITE,
                "note_publique": (
                    "GHI mensuel NASA POWER (moyenne journalière du mois, kWh/m²/jour), "
                    "climatologie 1991-2020. Confiance B (satellite/réanalyse)."
                ),
            }
            for s in SERIES
        ],
    )

    serie_id = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": list(_CODES_SERIES)},
        ).all()
    }

    mesures_table = sa.table(
        "mesures_ressource_mensuelles",
        sa.column("serie_id", sa.BigInteger),
        sa.column("annee", sa.SmallInteger),
        sa.column("mois", sa.SmallInteger),
        sa.column("valeur", sa.Float),
        sa.column("statut", sa.String),
        sa.column("niveau_confiance_derive", sa.String),
    )
    payload: list[dict[str, Any]] = []
    for s in SERIES:
        sid = serie_id[s["code"]]
        for annee, mois, valeur in s["mesures"]:
            payload.append(
                {
                    "serie_id": sid,
                    "annee": annee,
                    "mois": mois,
                    "valeur": valeur,
                    "statut": "brut",
                    "niveau_confiance_derive": NIVEAU_CONFIANCE,
                }
            )
    op.bulk_insert(mesures_table, payload)


def downgrade() -> None:
    bind = op.get_bind()
    ids = [
        row.id
        for row in bind.execute(
            sa.text("SELECT id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": list(_CODES_SERIES)},
        ).all()
    ]
    if ids:
        bind.execute(
            sa.text("DELETE FROM mesures_ressource_mensuelles WHERE serie_id = ANY(:ids)"),
            {"ids": ids},
        )
        bind.execute(sa.text("DELETE FROM series_metadonnees WHERE id = ANY(:ids)"), {"ids": ids})
