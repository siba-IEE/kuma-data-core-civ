"""serie_cams_dhi_mensuel

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-29

**Deuxième source DHI** (ADR-0013) : irradiation diffuse horizontale mensuelle
all-sky **CAMS Radiation** (Heliosat-4, ADS Copernicus), colonne ``DHI`` du même
CSV que le GHI et le DNI déjà gravés (0014), aux 3 points, **2005-2020**.

Grave **3 séries** brutes et **576 mesures** (192 par série), méthode
``modele_satellitaire``, confiance **B**. Conversion ADR-0011 : Wh/m² intégrés
au mois ÷ 1000 ÷ jours du mois → kWh/m²/jour.

Source **existante** ``cams_radiation`` (id 13, seed 0002) ; garde-fou
d'identité. L'ingesteur régénère les seeds GHI et DNI CAMS **identiques à
l'octet** à ceux gravés en 0014. Aucune nouvelle source ni valeur d'énumération.

Valeurs figées dans le seed ``series_cams_dhi_mensuel_civ`` (généré hors-ligne
par ``scripts/ingest_cams_radiation_mensuel.py``, clé ``ADS_API_KEY``) ; la
migration n'accède jamais au réseau. ``downgrade`` supprime les mesures puis les
séries ; la source (seed 0002) est conservée.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds import series_cams_dhi_mensuel_civ as seed

# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_ID: int = 13
SOURCE_CODE: str = "cams_radiation"
NB_MESURES_ATTENDU: int = 576  # 3 points × 192 mois (2005-2020)
_CODES_SERIES: tuple[str, ...] = tuple(s["code"] for s in seed.SERIES)

_NOTE_PUBLIQUE: str = (
    "DHI mensuel CAMS Radiation (Heliosat-4, ADS Copernicus), all-sky, "
    "moyenne journalière du mois (kWh/m²/jour, normalisée depuis "
    "l'irradiation mensuelle intégrée Wh/m²), 2005-2020. Confiance B "
    "(satellite). 2ᵉ source DHI : rend l'écart DHI inter-source calculable "
    "(ADR-0013)."
)


def upgrade() -> None:
    bind = op.get_bind()

    # 0. Garde-fous : contrat du seed et identité de la source réutilisée.
    if (
        seed.SOURCE_CODE != SOURCE_CODE
        or seed.GRANDEUR_CODE != "dhi"
        or seed.NIVEAU_CONFIANCE != "B"
    ):
        raise RuntimeError("Migration 0022 : seed hors contrat ADR-0013.")
    code_source = bind.execute(
        sa.text("SELECT code FROM sources WHERE id = :i"), {"i": SOURCE_ID}
    ).scalar_one_or_none()
    if code_source != SOURCE_CODE:
        raise RuntimeError(
            f"Migration 0022 : source id {SOURCE_ID} = {code_source!r}, {SOURCE_CODE!r} attendue."
        )

    # 1. Séries brutes (même schéma que les migrations 0008-0018).
    codes_loc = sorted({s["localite_code"] for s in seed.SERIES})
    loc = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:c)"), {"c": codes_loc}
        ).all()
    }
    manquants = [c for c in codes_loc if c not in loc]
    if manquants:
        raise RuntimeError(f"Migration 0022 : localité(s) introuvable(s) : {manquants!r}.")

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
                "grandeur_code": seed.GRANDEUR_CODE,
                "source_id": SOURCE_ID,
                "periode_debut": seed.PERIODE_DEBUT,
                "periode_fin": seed.PERIODE_FIN,
                "methode_collecte": seed.METHODE_COLLECTE,
                "granularite": seed.GRANULARITE,
                "note_publique": _NOTE_PUBLIQUE,
            }
            for s in seed.SERIES
        ],
    )

    serie_id = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": list(_CODES_SERIES)},
        ).all()
    }

    # 2. Mesures mensuelles brutes.
    mesures_table = sa.table(
        "mesures_ressource_mensuelles",
        sa.column("serie_id", sa.BigInteger),
        sa.column("annee", sa.SmallInteger),
        sa.column("mois", sa.SmallInteger),
        sa.column("valeur", sa.Float),
        sa.column("statut", sa.String),
        sa.column("niveau_confiance_derive", sa.String),
    )
    payload: list[dict[str, Any]] = [
        {
            "serie_id": serie_id[s["code"]],
            "annee": annee,
            "mois": mois,
            "valeur": valeur,
            "statut": "brut",
            "niveau_confiance_derive": seed.NIVEAU_CONFIANCE,
        }
        for s in seed.SERIES
        for annee, mois, valeur in s["mesures"]
    ]
    if len(payload) != NB_MESURES_ATTENDU:
        raise RuntimeError(
            f"Migration 0022 : {len(payload)} mesures, {NB_MESURES_ATTENDU} attendues."
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
    # La source cams_radiation (seed 0002) est conservée.
