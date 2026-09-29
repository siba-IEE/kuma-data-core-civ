"""series_solaires_regions

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-29

**Lot national 1 — les 31 régions** (ADR-0015) : séries solaires mensuelles
brutes aux 31 régions (niveau ``prefecture``, coordonnées Wikidata gravées en
0006), aux **mêmes contrats** que les 3 points pilotes (ADR-0007 à ADR-0013) :

| Source | Grandeurs | Période | Contrat pilote |
|---|---|---|---|
| NASA POWER (id 1) | GHI / DNI / DHI | 1991 / 2001 / 2001 → 2020 | 0008, 0009, 0021 |
| SARAH-3 PVGIS (id 11) | GHI / DNI | 2005-2020 | 0010, 0017 |
| ERA5 PVGIS (id 16) | GHI / DNI | 2005-2020 | 0012, 0018 |
| CAMS Radiation (id 13) | GHI / DNI / DHI | 2005-2020 | 0014, 0022 |

Soit **310 séries** (10 familles × 31 régions) et **67 704 mesures**, confiance
**B**. Aucune nouvelle source ni valeur d'énumération ; garde-fou d'identité de
chaque source.

Valeurs figées dans des **CSV gzip committés** (``seeds/donnees/*_regions.csv.gz``,
générés hors-ligne par les ingesteurs avec ``--lot regions``) et relus par
``series_csv.lire_series``, qui valide complétude, bornes, doublons et
localités. La migration n'accède jamais au réseau. Garde-fous : 31 séries par
famille, nombre de mesures par famille et total. ``downgrade`` supprime les
mesures puis les séries du lot.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.lots_civ import CONTRATS_MENSUELS, points_lot
from kuma_data_core.db.seeds.series_csv import ContratSerie, lire_series

# revision identifiers, used by Alembic.
revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOT: str = "regions"
NB_POINTS: int = 31
NB_MESURES_ATTENDU: int = 67_704  # 31 × (NASA 360+240+240 + SARAH-3 384 + ERA5 384 + CAMS 576)

# ADR du contrat pilote de chaque source, cité dans la note publique.
_ADR_SOURCE: dict[str, str] = {
    "nasa_power": "ADR-0007/0013",
    "sarah3_monthly": "ADR-0008/0012",
    "era5_pvgis": "ADR-0010/0012",
    "cams_radiation": "ADR-0011/0013",
}


def _codes_lot() -> list[str]:
    codes = {code for code, _, _, _ in points_lot(LOT)}
    return [c.code_serie(code) for c in CONTRATS_MENSUELS for code in sorted(codes)]


def _note(contrat: ContratSerie) -> str:
    caveat = (
        " Réanalyse : source de comparaison, jamais une référence (ADR-0010)."
        if contrat.methode_collecte == "reanalyse"
        else ""
    )
    return (
        f"{contrat.grandeur_code.upper()} mensuel {contrat.source_libelle}, moyenne "
        f"journalière du mois (kWh/m²/jour), {contrat.annee_debut}-{contrat.annee_fin}. "
        f"Lot national « régions » (ADR-0015), même contrat que les séries pilotes "
        f"({_ADR_SOURCE[contrat.source_code]}). Confiance {contrat.niveau_confiance}.{caveat}"
    )


def upgrade() -> None:
    bind = op.get_bind()

    # 0. Garde-fous : identité des sources réutilisées et localités du lot.
    for contrat in CONTRATS_MENSUELS:
        code = bind.execute(
            sa.text("SELECT code FROM sources WHERE id = :i"), {"i": contrat.source_id}
        ).scalar_one_or_none()
        if code != contrat.source_code:
            raise RuntimeError(
                f"Migration 0025 : source id {contrat.source_id} = {code!r}, "
                f"{contrat.source_code!r} attendue."
            )
    points = points_lot(LOT)
    if len(points) != NB_POINTS:
        raise RuntimeError(f"Migration 0025 : {len(points)} régions, {NB_POINTS} attendues.")
    codes_loc = sorted(code for code, _, _, _ in points)
    loc = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:c)"), {"c": codes_loc}
        ).all()
    }
    manquants = [c for c in codes_loc if c not in loc]
    if manquants:
        raise RuntimeError(f"Migration 0025 : localité(s) introuvable(s) : {manquants!r}.")

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
    mesures_table = sa.table(
        "mesures_ressource_mensuelles",
        sa.column("serie_id", sa.BigInteger),
        sa.column("annee", sa.SmallInteger),
        sa.column("mois", sa.SmallInteger),
        sa.column("valeur", sa.Float),
        sa.column("statut", sa.String),
        sa.column("niveau_confiance_derive", sa.String),
    )

    total = 0
    for contrat in CONTRATS_MENSUELS:
        # 1. Lecture validée du CSV du lot (complétude, bornes, doublons, localités).
        series = lire_series(contrat, LOT)
        if sorted(s["localite_code"] for s in series) != codes_loc:
            raise RuntimeError(
                f"Migration 0025 : {contrat.nom_fichier(LOT)} ne couvre pas les {NB_POINTS} "
                "régions du lot."
            )

        # 2. Séries brutes.
        op.bulk_insert(
            series_table,
            [
                {
                    "code": s["code"],
                    "libelle": s["libelle"],
                    "localite_id": loc[s["localite_code"]],
                    "grandeur_code": contrat.grandeur_code,
                    "source_id": contrat.source_id,
                    "periode_debut": contrat.periode_debut,
                    "periode_fin": contrat.periode_fin,
                    "methode_collecte": contrat.methode_collecte,
                    "granularite": contrat.granularite,
                    "note_publique": _note(contrat),
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

        # 3. Mesures mensuelles.
        payload: list[dict[str, Any]] = [
            {
                "serie_id": serie_id[s["code"]],
                "annee": annee,
                "mois": mois,
                "valeur": valeur,
                "statut": "brut",
                "niveau_confiance_derive": contrat.niveau_confiance,
            }
            for s in series
            for annee, mois, valeur in s["mesures"]
        ]
        if len(payload) != NB_POINTS * contrat.nb_mois:
            raise RuntimeError(
                f"Migration 0025 : {contrat.prefixe_code} : {len(payload)} mesures, "
                f"{NB_POINTS * contrat.nb_mois} attendues."
            )
        op.bulk_insert(mesures_table, payload)
        total += len(payload)

    if total != NB_MESURES_ATTENDU:
        raise RuntimeError(f"Migration 0025 : {total} mesures, {NB_MESURES_ATTENDU} attendues.")


def downgrade() -> None:
    bind = op.get_bind()
    ids = [
        row.id
        for row in bind.execute(
            sa.text("SELECT id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": _codes_lot()},
        ).all()
    ]
    if ids:
        bind.execute(
            sa.text("DELETE FROM mesures_ressource_mensuelles WHERE serie_id = ANY(:ids)"),
            {"ids": ids},
        )
        bind.execute(sa.text("DELETE FROM series_metadonnees WHERE id = ANY(:ids)"), {"ids": ids})
