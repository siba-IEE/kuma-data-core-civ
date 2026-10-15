"""series_particules_cams_eac4

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-15

**Particules fines PM2.5 et PM10 CAMS EAC4** (ADR-0022) : concentrations de
surface de la réanalyse de composition atmosphérique EAC4 (ADS Copernicus),
entrée du proxy de salissure (``taux_salissure_proxy``, modèle HSU) et du PR
réaliste de l'API.

| Granularité | Localités | Période | Table | Mesures |
|---|---:|---|---|---:|
| mensuel (``monthly_mean``) | 142 (``civ142``) | 2003-01 → 2025-12 | ``mesures_ressource_mensuelles`` | 78 384 |
| journalier (moyenne des 8 analyses 00-21 UTC) | 34 (``pilotes_regions``) | 2003-01-01 → 2025-12-31 | ``mesures_ressource`` | 571 268 |

Soit **352 séries** (2 grandeurs × (142 + 34)) et **649 652 mesures**, source
``cams_eac4`` (id 15), méthode ``reanalyse``, confiance **B**, unité
``microgramme_par_metre_cube`` (kg/m³ natif × 1e9), point de grille 0,75° le
plus proche. Aucune nouvelle source, grandeur, unité ni valeur d'énumération.

Valeurs lues hors-ligne dans les CSV gzip committés
(``seeds/donnees/cams_eac4_{pm2_5,pm10}_{mensuel_civ142,journalier_pilotes_regions}.csv.gz``,
générés par ``scripts/ingest_cams_eac4_pm.py``) et validés par ``series_csv``
(complétude, bornes, doublons, localités). Insertion par ``COPY`` (volume) ; le
trigger d'audit par ligne s'applique normalement.

Garde-fous : identité de la source, existence des grandeurs et de leur unité,
**aucune série PM ``cams_eac4`` préexistante** (les résolveurs de l'API prennent
la première série trouvée), localités, couverture exacte de chaque CSV, comptes
par famille et total. ``ANALYZE`` en fin de migration. ``downgrade`` supprime
les mesures puis les séries.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.aerosols_civ import (
    CONTRATS_EAC4_JOURNALIERS,
    CONTRATS_EAC4_MENSUELS,
    LOT_AEROSOLS_JOURNALIER,
    LOT_AEROSOLS_MENSUEL,
    PARAMETRES_EAC4,
    SOURCE_CODE,
    SOURCE_ID,
    UNITE_CODE,
)
from kuma_data_core.db.seeds.lots_civ import points_journalier, points_nationaux
from kuma_data_core.db.seeds.series_csv import (
    ContratSerie,
    lire_series,
    lire_series_journalieres,
    nb_jours,
)

# revision identifiers, used by Alembic.
revision: str = "0037"
down_revision: str | Sequence[str] | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NB_POINTS_MENSUELS: int = 142
NB_POINTS_JOURNALIERS: int = 34
NB_MESURES_MENSUELLES: int = 78_384  # 2 grandeurs × 142 localités × 276 mois
NB_MESURES_JOURNALIERES: int = 571_268  # 2 grandeurs × 34 localités × 8401 jours


def _codes_series() -> list[str]:
    mensuels = [code for code, _, _, _ in points_nationaux()]
    journaliers = [code for code, _, _, _ in points_journalier()]
    return [c.code_serie(code) for c in CONTRATS_EAC4_MENSUELS.values() for code in mensuels] + [
        c.code_serie(code) for c in CONTRATS_EAC4_JOURNALIERS.values() for code in journaliers
    ]


def _note(contrat: ContratSerie) -> str:
    libelle = PARAMETRES_EAC4[contrat.grandeur_code][2]
    if contrat.granularite == "mensuel":
        nature = (
            f"{libelle} mensuel CAMS EAC4 (produit monthly_mean : moyenne des analyses du mois)"
        )
        lot = "Lot national de 142 localités"
    else:
        nature = (
            f"{libelle} journalier CAMS EAC4, moyenne des 8 analyses 3-horaires 00-21 UTC du jour"
        )
        lot = (
            "Lot « pilotes + régions » (34 localités), entrée du proxy de salissure (HSU) "
            "et du PR réaliste"
        )
    return (
        f"{nature}, µg/m³ (kg/m³ natif × 1e9), {contrat.annee_debut}-{contrat.annee_fin}. "
        "Réanalyse sur grille 0,75° : valeur du point de grille le plus proche, partagée "
        f"par les localités voisines de la même maille. {lot} (ADR-0022). "
        "Les analyses nulles servies par EAC4 (vers 12-21 UTC) entrent dans les moyennes "
        "sans correction. En mars 2024, le mensuel EAC4 diffère de la moyenne de ses "
        "analyses 3-horaires (jusqu'à 6 %) : incohérence de la source, non corrigée. "
        f"Confiance {contrat.niveau_confiance}."
    )


def _copier(connexion: Any, requete: str, lignes: list[tuple[Any, ...]]) -> None:
    with connexion.cursor() as curseur, curseur.copy(requete) as copie:
        for ligne in lignes:
            copie.write_row(ligne)


def upgrade() -> None:
    bind = op.get_bind()

    # 0. Garde-fous : source, grandeurs et unité, absence de séries PM préexistantes.
    code_source = bind.execute(
        sa.text("SELECT code FROM sources WHERE id = :i"), {"i": SOURCE_ID}
    ).scalar_one_or_none()
    if code_source != SOURCE_CODE:
        raise RuntimeError(
            f"Migration 0037 : source id {SOURCE_ID} = {code_source!r}, {SOURCE_CODE!r} attendue."
        )
    unites = {
        row.code: row.unite
        for row in bind.execute(
            sa.text(
                """
                SELECT g.code, u.code AS unite FROM grandeurs_referentiel g
                JOIN unites u ON u.id = g.unite_id WHERE g.code = ANY(:g)
                """
            ),
            {"g": list(PARAMETRES_EAC4)},
        ).all()
    }
    if unites != dict.fromkeys(PARAMETRES_EAC4, UNITE_CODE):
        raise RuntimeError(f"Migration 0037 : grandeurs ou unités inattendues : {unites!r}.")
    preexistantes = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM series_metadonnees WHERE source_id = :s "
            "AND grandeur_code = ANY(:g)"
        ),
        {"s": SOURCE_ID, "g": list(PARAMETRES_EAC4)},
    ).scalar_one()
    if preexistantes:
        raise RuntimeError(f"Migration 0037 : {preexistantes} série(s) PM EAC4 déjà présentes.")

    lots = (
        (CONTRATS_EAC4_MENSUELS, LOT_AEROSOLS_MENSUEL, points_nationaux(), NB_POINTS_MENSUELS),
        (
            CONTRATS_EAC4_JOURNALIERS,
            LOT_AEROSOLS_JOURNALIER,
            points_journalier(),
            NB_POINTS_JOURNALIERS,
        ),
    )
    codes_tous = sorted({code for _, _, points, _ in lots for code, _, _, _ in points})
    loc = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:c)"), {"c": codes_tous}
        ).all()
    }
    manquants = [c for c in codes_tous if c not in loc]
    if manquants:
        raise RuntimeError(f"Migration 0037 : localité(s) introuvable(s) : {manquants!r}.")

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
    totaux = {"mensuel": 0, "journalier": 0}
    for contrats, lot, points, nb_points in lots:
        codes_loc = sorted(code for code, _, _, _ in points)
        if len(codes_loc) != nb_points:
            raise RuntimeError(f"Migration 0037 : lot {lot} : {len(codes_loc)} localités.")
        for contrat in contrats.values():
            # 1. Lecture validée du CSV (complétude, bornes, doublons, localités).
            journalier = contrat.granularite == "journalier"
            series = (
                lire_series_journalieres(contrat, lot) if journalier else lire_series(contrat, lot)
            )
            if sorted(s["localite_code"] for s in series) != codes_loc:
                raise RuntimeError(
                    f"Migration 0037 : {contrat.nom_fichier(lot)} ne couvre pas les "
                    f"{nb_points} localités du lot."
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
                        "source_id": SOURCE_ID,
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

            # 3. Mesures, par COPY.
            if journalier:
                table = "mesures_ressource"
                _copier(
                    connexion,
                    "COPY mesures_ressource "
                    "(serie_id, instant_mesure, valeur, statut, niveau_confiance_derive) "
                    "FROM STDIN",
                    [
                        (serie_id[s["code"]], jour, valeur, "brut", contrat.niveau_confiance)
                        for s in series
                        for jour, valeur in s["mesures"]
                    ],
                )
                attendu = nb_points * nb_jours(contrat)
            else:
                table = "mesures_ressource_mensuelles"
                _copier(
                    connexion,
                    "COPY mesures_ressource_mensuelles "
                    "(serie_id, annee, mois, valeur, statut, niveau_confiance_derive) "
                    "FROM STDIN",
                    [
                        (serie_id[s["code"]], annee, mois, valeur, "brut", contrat.niveau_confiance)
                        for s in series
                        for annee, mois, valeur in s["mesures"]
                    ],
                )
                attendu = nb_points * contrat.nb_mois
            nb = bind.execute(
                sa.text(f"SELECT COUNT(*) FROM {table} WHERE serie_id = ANY(:ids)"),
                {"ids": list(serie_id.values())},
            ).scalar_one()
            if len(serie_id) != nb_points or nb != attendu:
                raise RuntimeError(
                    f"Migration 0037 : {contrat.prefixe_code} : {len(serie_id)} séries, "
                    f"{nb} mesures ; {nb_points} et {attendu} attendues."
                )
            totaux[contrat.granularite] += nb

    if totaux != {"mensuel": NB_MESURES_MENSUELLES, "journalier": NB_MESURES_JOURNALIERES}:
        raise RuntimeError(f"Migration 0037 : comptes inattendus {totaux!r}.")
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource_mensuelles"))
    bind.execute(sa.text("ANALYZE mesures_ressource"))


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
        bind.execute(
            sa.text("DELETE FROM mesures_ressource_mensuelles WHERE serie_id = ANY(:ids)"),
            {"ids": ids},
        )
        bind.execute(sa.text("DELETE FROM series_metadonnees WHERE id = ANY(:ids)"), {"ids": ids})
