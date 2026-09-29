"""series_nasa_journalieres

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-29

**Lot national 3 — NASA POWER journalier** (ADR-0016) : GHI, DNI et DHI
**journaliers** NASA POWER aux **34 localités** du lot ``pilotes_regions`` (3
points pilotes + 31 régions), dans la table ``mesures_ressource`` (grain
journalier, ``instant_mesure`` = date).

| Grandeur | Paramètre NASA | Période | Jours par série | Mesures |
|---|---|---|---:|---:|
| GHI | ``ALLSKY_SFC_SW_DWN`` | 1991-2020 | 10 958 | 372 572 |
| DNI | ``ALLSKY_SFC_SW_DNI`` | 2001-2020 | 7 305 | 248 370 |
| DHI | ``ALLSKY_SFC_SW_DIFF`` | 2001-2020 | 7 305 | 248 370 |

Soit **102 séries** (``granularite='journalier'``) et **869 312 mesures**,
méthode ``modele_satellitaire``, confiance **B**, source ``nasa_power`` (id 1).
Mêmes périodes que le mensuel (DNI non servi, DHI en rupture avant 2001 —
ADR-0013). Valeurs en kWh/m²/jour, sans conversion ; la moyenne des jours de
chaque mois redonne le mensuel NASA gravé à 2·10⁻⁴ près (arrondi).

Valeurs lues hors-ligne dans les CSV gzip committés
(``seeds/donnees/nasa_power_*_journalier_pilotes_regions.csv.gz``, générés par
``scripts/ingest_nasa_power_journalier.py``) et validées par
``series_csv.lire_series_journalieres`` (complétude de tous les jours civils,
bornes, doublons, localités). Insertion par ``COPY`` (volume) ; le trigger
d'audit par ligne s'applique normalement. Garde-fous : identité de la source,
34 séries par grandeur, nombre de mesures par grandeur et total.
``downgrade`` supprime les mesures puis les séries.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.lots_civ import (
    CONTRATS_NASA_JOURNALIERS,
    LOT_JOURNALIER,
    PARAMETRES_NASA,
    points_journalier,
)
from kuma_data_core.db.seeds.series_csv import lire_series_journalieres, nb_jours

# revision identifiers, used by Alembic.
revision: str = "0026"
down_revision: str | Sequence[str] | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_ID: int = 1
SOURCE_CODE: str = "nasa_power"
NB_POINTS: int = 34
NB_MESURES_ATTENDU: int = 869_312  # 34 × (10 958 + 7 305 + 7 305)


def _codes_series() -> list[str]:
    codes = [code for code, _, _, _ in points_journalier()]
    return [c.code_serie(code) for c in CONTRATS_NASA_JOURNALIERS.values() for code in codes]


def upgrade() -> None:
    bind = op.get_bind()

    # 0. Garde-fous : source et localités du lot.
    code_source = bind.execute(
        sa.text("SELECT code FROM sources WHERE id = :i"), {"i": SOURCE_ID}
    ).scalar_one_or_none()
    if code_source != SOURCE_CODE:
        raise RuntimeError(
            f"Migration 0026 : source id {SOURCE_ID} = {code_source!r}, {SOURCE_CODE!r} attendue."
        )
    codes_loc = sorted(code for code, _, _, _ in points_journalier())
    if len(codes_loc) != NB_POINTS:
        raise RuntimeError(f"Migration 0026 : {len(codes_loc)} localités, {NB_POINTS} attendues.")
    loc = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:c)"), {"c": codes_loc}
        ).all()
    }
    manquants = [c for c in codes_loc if c not in loc]
    if manquants:
        raise RuntimeError(f"Migration 0026 : localité(s) introuvable(s) : {manquants!r}.")

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
    connexion = bind.connection.driver_connection  # psycopg 3 : COPY pour le volume
    total = 0
    for grandeur, contrat in CONTRATS_NASA_JOURNALIERS.items():
        series = lire_series_journalieres(contrat, LOT_JOURNALIER)
        if sorted(s["localite_code"] for s in series) != codes_loc:
            raise RuntimeError(
                f"Migration 0026 : {contrat.nom_fichier(LOT_JOURNALIER)} ne couvre pas le lot."
            )

        # 1. Séries journalières.
        op.bulk_insert(
            series_table,
            [
                {
                    "code": s["code"],
                    "libelle": s["libelle"],
                    "localite_id": loc[s["localite_code"]],
                    "grandeur_code": contrat.grandeur_code,
                    "source_id": SOURCE_ID,
                    "periode_debut": contrat.periode_debut,
                    "periode_fin": contrat.periode_fin,
                    "methode_collecte": contrat.methode_collecte,
                    "granularite": contrat.granularite,
                    "note_publique": (
                        f"{grandeur.upper()} journalier NASA POWER "
                        f"({PARAMETRES_NASA[grandeur]}), kWh/m²/jour, "
                        f"{contrat.annee_debut}-{contrat.annee_fin}. Lot national "
                        "« pilotes + régions » (ADR-0016) ; la moyenne mensuelle des jours "
                        "redonne la série mensuelle NASA. Confiance B (satellite)."
                    ),
                }
                for s in series
            ],
        )
        serie_id = {
            row.code: row.id
            for row in bind.execute(
                sa.text("SELECT code, id FROM series_metadonnees WHERE code = ANY(:c)"),
                {"c": [s["code"] for s in series]},
            ).all()
        }

        # 2. Mesures journalières, par COPY.
        with (
            connexion.cursor() as curseur,
            curseur.copy(
                "COPY mesures_ressource "
                "(serie_id, instant_mesure, valeur, statut, niveau_confiance_derive) "
                "FROM STDIN"
            ) as copie,
        ):
            for s in series:
                sid = serie_id[s["code"]]
                for jour, valeur in s["mesures"]:
                    copie.write_row((sid, jour, valeur, "brut", contrat.niveau_confiance))

        nb = bind.execute(
            sa.text("SELECT COUNT(*) FROM mesures_ressource WHERE serie_id = ANY(:ids)"),
            {"ids": list(serie_id.values())},
        ).scalar_one()
        if nb != NB_POINTS * nb_jours(contrat):
            raise RuntimeError(
                f"Migration 0026 : {grandeur} : {nb} mesures, "
                f"{NB_POINTS * nb_jours(contrat)} attendues."
            )
        total += nb

    if total != NB_MESURES_ATTENDU:
        raise RuntimeError(f"Migration 0026 : {total} mesures, {NB_MESURES_ATTENDU} attendues.")


def downgrade() -> None:
    bind = op.get_bind()
    ids = [
        row.id
        for row in bind.execute(
            sa.text("SELECT id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": _codes_series()},
        ).all()
    ]
    if ids:
        bind.execute(
            sa.text("DELETE FROM mesures_ressource WHERE serie_id = ANY(:ids)"), {"ids": ids}
        )
        bind.execute(sa.text("DELETE FROM series_metadonnees WHERE id = ANY(:ids)"), {"ids": ids})
