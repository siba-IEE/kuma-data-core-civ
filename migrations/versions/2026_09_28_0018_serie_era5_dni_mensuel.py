"""serie_era5_dni_mensuel

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-28

**Quatrième source de DNI mensuel** (triangulation DNI, ADR-0012) : **ERA5**
(réanalyse ECMWF) servie par PVGIS (JRC), champ ``Hb(n)_m`` (option ``mr_dni=1``
de l'API MRcalc v5_3), aux mêmes 3 points.

Grave **3 séries** brutes DNI (``series_metadonnees``) et **576 mesures**
(``mesures_ressource_mensuelles``, 192 par série), méthode ``reanalyse``,
confiance **B**, couverture **2005-2020** (fenêtre commune aux sources DNI).

Réutilise la source **existante** ``era5_pvgis`` (id 16, migration 0012) : même
produit et même requête que le GHI déjà gravé (0012) — la réponse PVGIS porte
les deux champs, et le GHI régénéré par l'ingesteur est identique à l'octet au
seed gravé. **Aucune nouvelle source ni valeur d'énumération.** Garde-fou : la
migration échoue si la source id 16 n'est pas ``era5_pvgis``.

**ERA5 est une source de COMPARAISON, jamais une référence** (ADR-0010) : la
réanalyse représente mal nuages et aérosols en Afrique de l'Ouest (Sawadogo et
al. 2023) ; ici elle donne le DNI le plus élevé des quatre sources. C'est la
seule classe de méthode indépendante de l'imagerie Meteosat.

Valeur **normalisée** : ``Hb(n)_m`` est l'irradiation directe normale mensuelle
totale (kWh/m²/mois), ramenée en moyenne journalière (÷ jours du mois) pour
l'unité ``kwh_par_m2_jour`` de la grandeur ``dni`` (convention ADR-0008).

Valeurs figées dans le seed ``series_pvgis_era5_dni_mensuel_civ`` (généré
hors-ligne par ``scripts/ingest_pvgis_era5_mensuel.py``) ; la migration
n'accède jamais au réseau. ``downgrade`` supprime les mesures puis les séries ;
la source (migration 0012) est conservée.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds import series_pvgis_era5_dni_mensuel_civ as seed

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_ID: int = 16
SOURCE_CODE: str = "era5_pvgis"
NB_MESURES_ATTENDU: int = 576  # 3 points × 192 mois (2005-2020)
_CODES_SERIES: tuple[str, ...] = tuple(s["code"] for s in seed.SERIES)

_NOTE_PUBLIQUE: str = (
    "DNI mensuel ERA5 (réanalyse ECMWF, via PVGIS, Hb(n)_m), moyenne "
    "journalière du mois (kWh/m²/jour, normalisée depuis l'irradiation directe "
    "normale mensuelle totale), 2005-2020. Confiance B (réanalyse). Source de "
    "comparaison inter-source (ADR-0012), jamais une vérité sol : la réanalyse "
    "représente mal nuages et aérosols en Afrique de l'Ouest (Sawadogo 2023)."
)


def upgrade() -> None:
    bind = op.get_bind()

    # 0. Garde-fous : contrat du seed et identité de la source réutilisée.
    if (
        seed.SOURCE_CODE != SOURCE_CODE
        or seed.GRANDEUR_CODE != "dni"
        or seed.NIVEAU_CONFIANCE != "B"
    ):
        raise RuntimeError("Migration 0018 : seed hors contrat ADR-0012.")
    code_source = bind.execute(
        sa.text("SELECT code FROM sources WHERE id = :i"), {"i": SOURCE_ID}
    ).scalar_one_or_none()
    if code_source != SOURCE_CODE:
        raise RuntimeError(
            f"Migration 0018 : source id {SOURCE_ID} = {code_source!r}, {SOURCE_CODE!r} attendue."
        )

    # 1. Séries brutes (même schéma que les migrations 0008-0014).
    codes_loc = sorted({s["localite_code"] for s in seed.SERIES})
    loc = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:c)"), {"c": codes_loc}
        ).all()
    }
    manquants = [c for c in codes_loc if c not in loc]
    if manquants:
        raise RuntimeError(f"Migration 0018 : localité(s) introuvable(s) : {manquants!r}.")

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
            f"Migration 0018 : {len(payload)} mesures, {NB_MESURES_ATTENDU} attendues."
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
    # La source era5_pvgis (migration 0012) est conservée.
