"""serie_cams_ghi_dni_mensuel

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-27

**Quatrième source** de GHI et **deuxième source** de DNI mensuels (ADR-0011) :
**CAMS Radiation** (Heliosat-4 + McClear, Meteosat, aérosols CAMS explicites),
servie par l'ADS Copernicus, aux mêmes 3 points.

Grave **6 séries** brutes (``series_metadonnees``) — GHI et DNI × 3 points — et
**1152 mesures** (``mesures_ressource_mensuelles``, 192 par série), méthode
``modele_satellitaire``, confiance **B**, couverture **2005-2020** (fenêtre
commune aux autres sources GHI).

Réutilise la source **existante** ``cams_radiation`` (id 13, seed 0002) pour les
deux grandeurs : Heliosat-4 est une restitution satellitaire, donc — à la
différence d'ERA5 (0012) — **aucune extension d'énumération** ni nouvelle
source. Garde-fou : la migration échoue si la source 13 n'est pas
``cams_radiation``.

Valeur **normalisée** : le CSV ADS donne l'irradiation mensuelle intégrée en
Wh/m², ramenée en moyenne journalière ``(Wh/m² ÷ 1000) ÷ jours du mois`` pour
l'unité ``kwh_par_m2_jour`` des grandeurs ``ghi`` et ``dni``.

Valeurs figées dans les seeds ``series_cams_ghi_mensuel_civ`` et
``series_cams_dni_mensuel_civ`` (générés hors-ligne par
``scripts/ingest_cams_radiation_mensuel.py``) ; la migration n'accède jamais au
réseau. ``downgrade`` supprime les mesures puis les séries ; la source 13
(seed 0002) est conservée.
"""

from __future__ import annotations

from collections.abc import Sequence
from types import ModuleType
from typing import Any

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds import series_cams_dni_mensuel_civ as cams_dni
from kuma_data_core.db.seeds import series_cams_ghi_mensuel_civ as cams_ghi

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_ID: int = 13
SOURCE_CODE: str = "cams_radiation"
NB_MESURES_ATTENDU: int = 1152  # 2 grandeurs × 3 points × 192 mois (2005-2020)

_SEEDS: tuple[ModuleType, ...] = (cams_ghi, cams_dni)
_CODES_SERIES: tuple[str, ...] = tuple(s["code"] for seed in _SEEDS for s in seed.SERIES)

_NOTES: dict[str, str] = {
    "ghi": (
        "GHI mensuel CAMS Radiation (Heliosat-4, ADS Copernicus), all-sky, moyenne "
        "journalière du mois (kWh/m²/jour, normalisée depuis l'irradiation mensuelle "
        "intégrée Wh/m²), 2005-2020. Confiance B (satellite). 4ᵉ source GHI de la "
        "triangulation inter-source, traitement d'aérosols explicite (ADR-0011)."
    ),
    "dni": (
        "DNI mensuel CAMS Radiation (BNI all-sky, Heliosat-4, ADS Copernicus), "
        "aérosol-corrigé, moyenne journalière du mois (kWh/m²/jour, normalisée depuis "
        "l'irradiation mensuelle intégrée Wh/m²), 2005-2020. Confiance B (satellite). "
        "2ᵉ source DNI de l'instance : rend l'écart DNI inter-source calculable "
        "(ADR-0011)."
    ),
}


def upgrade() -> None:
    bind = op.get_bind()

    # 0. Garde-fous : contrat des seeds et identité de la source réutilisée.
    for seed in _SEEDS:
        if seed.SOURCE_CODE != SOURCE_CODE or seed.NIVEAU_CONFIANCE != "B":
            raise RuntimeError(f"Migration 0014 : seed {seed.__name__} hors contrat ADR-0011.")
    code_source = bind.execute(
        sa.text("SELECT code FROM sources WHERE id = :i"), {"i": SOURCE_ID}
    ).scalar_one_or_none()
    if code_source != SOURCE_CODE:
        raise RuntimeError(
            f"Migration 0014 : source id {SOURCE_ID} = {code_source!r}, {SOURCE_CODE!r} attendue."
        )

    # 1. Séries brutes (identique au schéma NASA/SARAH-3/ERA5, migrations 0008-0012).
    codes_loc = sorted({s["localite_code"] for seed in _SEEDS for s in seed.SERIES})
    loc = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:c)"), {"c": codes_loc}
        ).all()
    }
    manquants = [c for c in codes_loc if c not in loc]
    if manquants:
        raise RuntimeError(f"Migration 0014 : localité(s) introuvable(s) : {manquants!r}.")

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
                "note_publique": _NOTES[seed.GRANDEUR_CODE],
            }
            for seed in _SEEDS
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
    payload: list[dict[str, Any]] = []
    for seed in _SEEDS:
        for s in seed.SERIES:
            sid = serie_id[s["code"]]
            for annee, mois, valeur in s["mesures"]:
                payload.append(
                    {
                        "serie_id": sid,
                        "annee": annee,
                        "mois": mois,
                        "valeur": valeur,
                        "statut": "brut",
                        "niveau_confiance_derive": seed.NIVEAU_CONFIANCE,
                    }
                )
    if len(payload) != NB_MESURES_ATTENDU:
        raise RuntimeError(
            f"Migration 0014 : {len(payload)} mesures, {NB_MESURES_ATTENDU} attendues."
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
    # La source cams_radiation (id 13) appartient au seed 0002 : conservée.
