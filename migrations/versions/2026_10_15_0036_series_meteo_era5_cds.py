"""series_meteo_era5_cds

Revision ID: 0036
Revises: 0034
Create Date: 2026-10-15

**Météo ERA5 directe (CDS Copernicus), 142 localités** (ADR-0021) : deuxième
source des grandeurs météo, à côté de NASA POWER (réanalyse MERRA-2). Moyennes
mensuelles de la réanalyse ERA5 (ECMWF, Copernicus C3S) au point de grille 0,25°
le plus proche de chaque localité (110 mailles distinctes), source
``ecmwf_era5`` (id 2, seedée en 0002), méthode ``reanalyse``, confiance **B** :

| Grandeur | Variable CDS | Conversion | Période |
|---|---|---|---|
| ``t2m`` | ``2m_temperature`` | K − 273,15 → °C | 1991-2025 |
| ``vent_10m`` | ``10m_wind_speed`` | moyenne des vitesses, m/s | 1991-2025 |
| ``precipitation`` | ``total_precipitation`` | m/jour × 1000 → mm/jour | 1991-2025 |

Soit **426 séries** (3 grandeurs × 142 localités) et **178 920 mesures**
(420 mois par série). Ni ``rh2m`` (biais de la recomposition mensuelle) ni
``albedo_surface`` (``forecast_albedo`` limité au diffus) : abstentions motivées
dans l'ADR-0021. Aucune nouvelle source, grandeur ni valeur d'énumération.

Aucune mise en garde de saut : le contrôle de continuité 2020/2021 (ADR-0021)
ne montre pas, sur ces trois grandeurs, le saut que l'ERA5 présente sur le
rayonnement (ADR-0018).

Valeurs figées dans des **CSV gzip committés**
(``seeds/donnees/ecmwf_era5_<grandeur>_mensuel_civ142.csv.gz``, produits par
``scripts/ingest_era5_cds_mensuel.py``) et relus par ``series_csv.lire_series``,
qui valide complétude, bornes, doublons et localités. La migration n'accède
jamais au réseau. Garde-fous : identité de la source, unité de chaque grandeur
au référentiel (cohérente avec la conversion), aucune série préexistante sous
ces codes, couverture exacte des 142 localités, nombre de mesures par famille et
total. ``ANALYZE`` en fin de migration. ``downgrade`` supprime les mesures puis
les séries.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.meteo_era5_civ import (
    CONTRATS_METEO_ERA5_MENSUELS,
    LOT_METEO_ERA5,
    VARIABLES_ERA5,
)
from kuma_data_core.db.seeds.series_csv import lire_series

# revision identifiers, used by Alembic.
revision: str = "0036"
down_revision: str | Sequence[str] | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NB_POINTS: int = 142
NB_SERIES_ATTENDU: int = 426  # 3 grandeurs × 142 localités
NB_MESURES_ATTENDU: int = 178_920  # 426 × 420 mois (1991-2025)

_COMMUN: str = (
    "au point de grille 0,25° le plus proche, 1991-2025. Confiance B (réanalyse). "
    "Deuxième source de comparaison à côté de NASA POWER (réanalyse MERRA-2), "
    "jamais une mesure au sol (ADR-0021). Attribution : contient des informations "
    "modifiées du Copernicus Climate Change Service (2026)."
)
NOTES: dict[str, str] = {
    "t2m": (
        "Température à 2 m mensuelle ERA5 (réanalyse ECMWF, Copernicus C3S, moyennes "
        "mensuelles du CDS) : moyenne des 24 heures UTC des jours du mois, en °C "
        f"(convertie des kelvins), {_COMMUN}"
    ),
    "vent_10m": (
        "Vent à 10 m mensuel ERA5 (réanalyse ECMWF, Copernicus C3S, moyennes mensuelles "
        "du CDS) : moyenne des vitesses horaires du mois, en m/s (et non la norme des "
        f"composantes moyennes), {_COMMUN}"
    ),
    "precipitation": (
        "Précipitations mensuelles ERA5 (réanalyse ECMWF, Copernicus C3S, moyennes "
        "mensuelles du CDS) : cumul du mois entier rapporté au jour, en mm/jour "
        f"(converti des mètres d'eau par jour), {_COMMUN}"
    ),
}


def _codes_series() -> list[str]:
    return [
        c.code_serie(code)
        for c in CONTRATS_METEO_ERA5_MENSUELS.values()
        for code, _, _, _ in points_nationaux()
    ]


def upgrade() -> None:
    bind = op.get_bind()

    # 0. Garde-fous : source, unités au référentiel, séries absentes, localités.
    contrats = list(CONTRATS_METEO_ERA5_MENSUELS.values())
    for contrat in contrats:
        code = bind.execute(
            sa.text("SELECT code FROM sources WHERE id = :i"), {"i": contrat.source_id}
        ).scalar_one_or_none()
        if code != contrat.source_code:
            raise RuntimeError(
                f"Migration 0036 : source id {contrat.source_id} = {code!r}, "
                f"{contrat.source_code!r} attendue."
            )
        unite = bind.execute(
            sa.text(
                "SELECT u.code FROM grandeurs_referentiel g JOIN unites u ON u.id = g.unite_id "
                "WHERE g.code = :g"
            ),
            {"g": contrat.grandeur_code},
        ).scalar_one_or_none()
        attendue = VARIABLES_ERA5[contrat.grandeur_code].unite_referentiel
        if unite != attendue:
            raise RuntimeError(
                f"Migration 0036 : grandeur {contrat.grandeur_code!r} en {unite!r}, "
                f"{attendue!r} attendue par la conversion."
            )
    codes_series = _codes_series()
    if len(codes_series) != NB_SERIES_ATTENDU:
        raise RuntimeError(
            f"Migration 0036 : {len(codes_series)} séries, {NB_SERIES_ATTENDU} attendues."
        )
    deja = bind.execute(
        sa.text("SELECT COUNT(*) FROM series_metadonnees WHERE code = ANY(:c)"),
        {"c": codes_series},
    ).scalar_one()
    if deja:
        raise RuntimeError(f"Migration 0036 : {deja} série(s) déjà présente(s) sous ces codes.")
    codes_loc = sorted(code for code, _, _, _ in points_nationaux())
    if len(codes_loc) != NB_POINTS:
        raise RuntimeError(f"Migration 0036 : {len(codes_loc)} localités, {NB_POINTS} attendues.")
    loc = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:c)"), {"c": codes_loc}
        ).all()
    }
    manquants = [c for c in codes_loc if c not in loc]
    if manquants:
        raise RuntimeError(f"Migration 0036 : localité(s) introuvable(s) : {manquants!r}.")

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
    for contrat in contrats:
        # 1. Lecture validée du CSV (complétude, bornes, doublons, localités).
        series = lire_series(contrat, LOT_METEO_ERA5)
        if [s["localite_code"] for s in series] != codes_loc:
            raise RuntimeError(
                f"Migration 0036 : {contrat.nom_fichier(LOT_METEO_ERA5)} ne couvre pas les "
                f"{NB_POINTS} localités."
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
                    "note_publique": NOTES[contrat.grandeur_code],
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
                f"Migration 0036 : {contrat.prefixe_code} : {len(payload)} mesures, "
                f"{NB_POINTS * contrat.nb_mois} attendues."
            )
        op.bulk_insert(mesures_table, payload)
        total += len(payload)

    if total != NB_MESURES_ATTENDU:
        raise RuntimeError(f"Migration 0036 : {total} mesures, {NB_MESURES_ATTENDU} attendues.")
    bind.execute(sa.text("ANALYZE mesures_ressource_mensuelles"))
    bind.execute(sa.text("ANALYZE series_metadonnees"))


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
            sa.text("DELETE FROM mesures_ressource_mensuelles WHERE serie_id = ANY(:ids)"),
            {"ids": ids},
        )
        bind.execute(sa.text("DELETE FROM series_metadonnees WHERE id = ANY(:ids)"), {"ids": ids})
    bind.execute(sa.text("ANALYZE mesures_ressource_mensuelles"))
    bind.execute(sa.text("ANALYZE series_metadonnees"))
