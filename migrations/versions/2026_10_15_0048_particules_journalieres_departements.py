"""particules_journalieres_departements

Revision ID: 0048
Revises: 0047
Create Date: 2026-10-15

**Particules fines PM2.5 et PM10 journalières CAMS EAC4 aux 108 départements**
hors pilotes (lot ``departements``, ADR-0031) : le journalier EAC4 ne couvrait
que les 34 localités du lot « pilotes + régions » (migration 0037, ADR-0022).
Avec ce lot, les 111 départements ont leurs PM journalières, entrée du proxy de
salissure (``taux_salissure_proxy``, modèle HSU) et du PR réaliste de l'API.

| Grandeur | Séries | Période | Table | Mesures |
|---|---:|---|---|---:|
| PM2.5 (``cams_eac4_pm2_5_journalier_<loc>``) | 108 | 2003-01-01 → 2025-12-31 | ``mesures_ressource`` | 907 308 |
| PM10 (``cams_eac4_pm10_journalier_<loc>``) | 108 | 2003-01-01 → 2025-12-31 | ``mesures_ressource`` | 907 308 |

Soit **216 séries** et **1 814 616 mesures** (2 × 108 × 8401 jours), mêmes
contrats que le journalier 0037
(``journalier_departements_civ.CONTRATS_PARTICULES_DEPARTEMENTS``) : source
``cams_eac4`` (id 15), méthode ``reanalyse``, confiance **B**, unité
``microgramme_par_metre_cube`` (kg/m³ natif × 1e9), point de grille 0,75° le
plus proche, moyenne des 8 analyses 3-horaires 00-21 UTC du jour civil UTC.
Aucune nouvelle source, grandeur, unité ni valeur d'énumération.

Valeurs lues hors-ligne dans les CSV gzip committés
(``seeds/donnees/cams_eac4_{pm2_5,pm10}_journalier_departements.csv.gz``,
générés par ``scripts/ingest_cams_eac4_pm.py --departements`` depuis les mêmes
archives que 0037) et validés par ``series_csv`` (complétude, bornes, doublons,
localités). Insertion par ``COPY``, avec l'**audit par série**
(``audit_par_serie``) : trigger d'audit ligne à ligne de ``mesures_ressource``
suspendu le temps de l'insertion, puis une entrée ``audit_log`` par série
(nombre de mesures, bornes, CSV et son empreinte SHA-256).

Garde-fous : identité de la source, unité ``microgramme_par_metre_cube`` des
deux grandeurs, **aucune série préexistante** (ni ces codes, ni série PM
``cams_eac4`` journalière aux 108 départements : les résolveurs de l'API
prennent la première trouvée), localités, couverture exacte de chaque CSV,
comptes par grandeur et total, une entrée d'audit par série. ``ANALYZE`` en fin
de migration. ``downgrade`` écrit l'audit par série (``D``), puis supprime les
mesures (audit ligne à ligne suspendu) et les séries.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.aerosols_civ import (
    PARAMETRES_EAC4,
    SOURCE_CODE,
    SOURCE_ID,
    UNITE_CODE,
)
from kuma_data_core.db.seeds.audit_par_serie import (
    audit_ligne_suspendu,
    auditer_series,
    empreinte_fichier,
)
from kuma_data_core.db.seeds.journalier_departements_civ import (
    CONTRATS_PARTICULES_DEPARTEMENTS,
    LOT_JOURNALIER_DEPARTEMENTS,
    NB_DEPARTEMENTS,
    points_journalier_departements,
)
from kuma_data_core.db.seeds.series_csv import ContratSerie, lire_series_journalieres, nb_jours

# revision identifiers, used by Alembic.
revision: str = "0048"
down_revision: str | Sequence[str] | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NB_JOURS: int = 8401  # 2003-01-01 → 2025-12-31
NB_SERIES: int = 216  # 2 grandeurs × 108 départements
NB_MESURES: int = 1_814_616  # 2 grandeurs × 108 départements × 8401 jours


def _fichiers() -> dict[str, tuple[str, str]]:
    """Code de série → (CSV, empreinte SHA-256), pour l'audit par série."""
    fichiers: dict[str, tuple[str, str]] = {}
    for contrat in CONTRATS_PARTICULES_DEPARTEMENTS.values():
        fichier = (
            contrat.nom_fichier(LOT_JOURNALIER_DEPARTEMENTS),
            empreinte_fichier(contrat, LOT_JOURNALIER_DEPARTEMENTS),  # une lecture par CSV
        )
        for code, _, _, _ in points_journalier_departements():
            fichiers[contrat.code_serie(code)] = fichier
    return fichiers


def _note(contrat: ContratSerie) -> str:
    libelle = PARAMETRES_EAC4[contrat.grandeur_code][2]
    return (
        f"{libelle} journalier CAMS EAC4, moyenne des 8 analyses 3-horaires 00-21 UTC du "
        f"jour, µg/m³ (kg/m³ natif × 1e9), {contrat.annee_debut}-{contrat.annee_fin}. "
        "Réanalyse sur grille 0,75° : valeur du point de grille le plus proche, partagée "
        "par les localités voisines de la même maille. Lot « départements » (108 "
        "départements hors pilotes), entrée du proxy de salissure (HSU) et du PR "
        "réaliste (ADR-0022, ADR-0031). Les analyses nulles servies par EAC4 (vers "
        "12-21 UTC) entrent dans les moyennes sans correction. En mars 2024, le mensuel "
        "EAC4 diffère de la moyenne de ses analyses 3-horaires (jusqu'à 6 %) : "
        f"incohérence de la source, non corrigée. Confiance {contrat.niveau_confiance}."
    )


def _copier(connexion: Any, requete: str, lignes: Iterable[tuple[Any, ...]]) -> None:
    with connexion.cursor() as curseur, curseur.copy(requete) as copie:
        for ligne in lignes:
            copie.write_row(ligne)


def upgrade() -> None:
    bind = op.get_bind()
    points = points_journalier_departements()
    codes_loc = sorted(code for code, _, _, _ in points)
    if len(codes_loc) != NB_DEPARTEMENTS or len(set(codes_loc)) != NB_DEPARTEMENTS:
        raise RuntimeError(f"Migration 0048 : {len(codes_loc)} départements, 108 attendus.")
    contrats = CONTRATS_PARTICULES_DEPARTEMENTS
    codes_series = [c.code_serie(code) for c in contrats.values() for code in codes_loc]

    # 0. Garde-fous : source, grandeurs et unité, localités, rien de préexistant.
    code_source = bind.execute(
        sa.text("SELECT code FROM sources WHERE id = :i"), {"i": SOURCE_ID}
    ).scalar_one_or_none()
    if code_source != SOURCE_CODE:
        raise RuntimeError(
            f"Migration 0048 : source id {SOURCE_ID} = {code_source!r}, {SOURCE_CODE!r} attendue."
        )
    if {c.source_code for c in contrats.values()} != {SOURCE_CODE} or set(contrats) != set(
        PARAMETRES_EAC4
    ):
        raise RuntimeError(f"Migration 0048 : contrats inattendus {sorted(contrats)!r}.")
    unites = {
        row.code: row.unite
        for row in bind.execute(
            sa.text(
                """
                SELECT g.code, u.code AS unite FROM grandeurs_referentiel g
                JOIN unites u ON u.id = g.unite_id WHERE g.code = ANY(:g)
                """
            ),
            {"g": list(contrats)},
        ).all()
    }
    if unites != dict.fromkeys(contrats, UNITE_CODE):
        raise RuntimeError(f"Migration 0048 : grandeurs ou unités inattendues : {unites!r}.")
    loc = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:c)"), {"c": codes_loc}
        ).all()
    }
    manquants = [c for c in codes_loc if c not in loc]
    if manquants:
        raise RuntimeError(f"Migration 0048 : localité(s) introuvable(s) : {manquants!r}.")
    preexistantes = bind.execute(
        sa.text(
            """
            SELECT COUNT(*) FROM series_metadonnees
            WHERE code = ANY(:codes)
               OR (source_id = :s AND grandeur_code = ANY(:g) AND granularite = 'journalier'
                   AND localite_id = ANY(:loc))
            """
        ),
        {"codes": codes_series, "s": SOURCE_ID, "g": list(contrats), "loc": list(loc.values())},
    ).scalar_one()
    if preexistantes:
        raise RuntimeError(
            f"Migration 0048 : {preexistantes} série(s) PM EAC4 journalière(s) déjà présentes "
            "aux 108 départements."
        )

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
    with audit_ligne_suspendu(bind):
        for contrat in contrats.values():
            # 1. Lecture validée du CSV (complétude, bornes, doublons, localités).
            series = lire_series_journalieres(contrat, LOT_JOURNALIER_DEPARTEMENTS)
            if sorted(s["localite_code"] for s in series) != codes_loc:
                raise RuntimeError(
                    f"Migration 0048 : {contrat.nom_fichier(LOT_JOURNALIER_DEPARTEMENTS)} ne "
                    f"couvre pas les {NB_DEPARTEMENTS} départements du lot."
                )

            # 2. Séries brutes (audit ligne à ligne de series_metadonnees inchangé).
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

            # 3. Mesures, par COPY, sans audit ligne à ligne.
            _copier(
                connexion,
                "COPY mesures_ressource "
                "(serie_id, instant_mesure, valeur, statut, niveau_confiance_derive) "
                "FROM STDIN",
                (
                    (serie_id[s["code"]], jour, valeur, "brut", contrat.niveau_confiance)
                    for s in series
                    for jour, valeur in s["mesures"]
                ),
            )
            nb = bind.execute(
                sa.text("SELECT COUNT(*) FROM mesures_ressource WHERE serie_id = ANY(:ids)"),
                {"ids": list(serie_id.values())},
            ).scalar_one()
            attendu = NB_DEPARTEMENTS * nb_jours(contrat)
            if len(serie_id) != NB_DEPARTEMENTS or nb_jours(contrat) != NB_JOURS or nb != attendu:
                raise RuntimeError(
                    f"Migration 0048 : {contrat.prefixe_code} : {len(serie_id)} séries, "
                    f"{nb} mesures ; {NB_DEPARTEMENTS} et {attendu} attendues."
                )
            total += nb

    if total != NB_MESURES:
        raise RuntimeError(f"Migration 0048 : {total} mesures, {NB_MESURES} attendues.")

    # 4. Une entrée d'audit par série (comptes et bornes relus en base).
    if auditer_series(bind, "I", revision, _fichiers()) != NB_SERIES:
        raise RuntimeError(f"Migration 0048 : audit par série incomplet ({NB_SERIES} attendues).")
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource"))


def downgrade() -> None:
    bind = op.get_bind()
    fichiers = _fichiers()
    ids = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": sorted(fichiers)},
        ).all()
    }
    if not ids:
        return
    # Audit par série d'abord : comptes et bornes lus avant la suppression.
    auditer_series(bind, "D", revision, {code: fichiers[code] for code in ids})
    with audit_ligne_suspendu(bind):
        bind.execute(
            sa.text("DELETE FROM mesures_ressource WHERE serie_id = ANY(:ids)"),
            {"ids": list(ids.values())},
        )
    bind.execute(
        sa.text("DELETE FROM series_metadonnees WHERE id = ANY(:ids)"),
        {"ids": list(ids.values())},
    )
