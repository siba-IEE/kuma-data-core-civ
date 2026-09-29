"""prolonger_series_journalieres_2025

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-30

**Extension temporelle du journalier NASA POWER** (ADR-0018) : prolonge les 102
séries journalières (GHI, DNI, DHI × 34 localités, migration 0026) sur
**2021-2025** : 3 × 34 × 1826 jours = **186 252 mesures**, mêmes contrats et
mêmes codes de série (``mesures_ressource``, insertion par ``COPY``).

Mêmes règles que 0030 : ``periode_fin`` → 2025-12-31, libellé « (AAAA-2020) » →
« (AAAA-2025) », phrase ajoutée à la note publique. Valeurs lues dans les CSV
``nasa_power_*_journalier_ext_2021_2025.csv.gz`` (validés : tous les jours civils,
bornes, doublons). Garde-fous : séries existantes, finissant en 2020, sans mesure
après 2020 ; comptes par grandeur et total. ``ANALYZE`` en fin de migration.
``downgrade`` supprime les jours postérieurs à 2020 et restaure les métadonnées.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.lots_civ import (
    CONTRATS_NASA_JOURNALIERS_EXTENSION,
    LOT_EXTENSION,
    points_journalier,
)
from kuma_data_core.db.seeds.series_csv import lire_series_journalieres, nb_jours

# revision identifiers, used by Alembic.
revision: str = "0031"
down_revision: str | Sequence[str] | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NB_POINTS: int = 34
NB_MESURES_ATTENDU: int = 186_252  # 3 grandeurs × 34 localités × 1826 jours
FIN_ACTUELLE: str = "2020-12-31"
PHRASE: str = " Prolongée jusqu'en 2025 (ADR-0018)."
DEBUT_EXTENSION: date = date(2021, 1, 1)


def _codes() -> list[str]:
    return [
        c.code_serie(code)
        for c in CONTRATS_NASA_JOURNALIERS_EXTENSION.values()
        for code, _, _, _ in points_journalier()
    ]


def upgrade() -> None:
    bind = op.get_bind()
    codes_loc = sorted(code for code, _, _, _ in points_journalier())
    connexion = bind.connection.driver_connection  # psycopg 3 : COPY pour le volume
    total = 0
    for grandeur, contrat in CONTRATS_NASA_JOURNALIERS_EXTENSION.items():
        series = lire_series_journalieres(contrat, LOT_EXTENSION)
        if sorted(s["localite_code"] for s in series) != codes_loc:
            raise RuntimeError(f"Migration 0031 : {grandeur} ne couvre pas les {NB_POINTS} lieux.")
        existantes = {
            row.code: row
            for row in bind.execute(
                sa.text(
                    """
                    SELECT s.code, s.id, s.periode_fin, s.granularite,
                           (SELECT COUNT(*) FROM mesures_ressource m
                            WHERE m.serie_id = s.id AND m.instant_mesure >= :d) AS apres_2020
                    FROM series_metadonnees s WHERE s.code = ANY(:c)
                    """
                ),
                {"c": [s["code"] for s in series], "d": DEBUT_EXTENSION},
            ).all()
        }
        for s in series:
            e = existantes.get(s["code"])
            if (
                e is None
                or str(e.periode_fin) != FIN_ACTUELLE
                or e.granularite != "journalier"
                or e.apres_2020
            ):
                raise RuntimeError(f"Migration 0031 : série {s['code']!r} hors contrat : {e!r}.")

        ids = [existantes[s["code"]].id for s in series]
        bind.execute(
            sa.text(
                """
                UPDATE series_metadonnees
                SET periode_fin = :fin,
                    libelle = regexp_replace(libelle, '-2020\\)$', '-2025)'),
                    note_publique = note_publique || :phrase
                WHERE id = ANY(:ids)
                """
            ),
            {"fin": contrat.periode_fin, "phrase": PHRASE, "ids": ids},
        )

        with (
            connexion.cursor() as curseur,
            curseur.copy(
                "COPY mesures_ressource "
                "(serie_id, instant_mesure, valeur, statut, niveau_confiance_derive) "
                "FROM STDIN"
            ) as copie,
        ):
            for s in series:
                sid = existantes[s["code"]].id
                for jour, valeur in s["mesures"]:
                    copie.write_row((sid, jour, valeur, "brut", contrat.niveau_confiance))

        nb = bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM mesures_ressource "
                "WHERE serie_id = ANY(:ids) AND instant_mesure >= :d"
            ),
            {"ids": ids, "d": DEBUT_EXTENSION},
        ).scalar_one()
        if nb != NB_POINTS * nb_jours(contrat):
            raise RuntimeError(
                f"Migration 0031 : {grandeur} : {nb} mesures, {NB_POINTS * nb_jours(contrat)} "
                "attendues."
            )
        total += nb

    if total != NB_MESURES_ATTENDU:
        raise RuntimeError(f"Migration 0031 : {total} mesures, {NB_MESURES_ATTENDU} attendues.")
    bind.execute(sa.text("ANALYZE mesures_ressource"))


def downgrade() -> None:
    bind = op.get_bind()
    codes = _codes()
    bind.execute(
        sa.text(
            "DELETE FROM mesures_ressource WHERE instant_mesure >= :d AND serie_id IN "
            "(SELECT id FROM series_metadonnees WHERE code = ANY(:c))"
        ),
        {"c": codes, "d": DEBUT_EXTENSION},
    )
    bind.execute(
        sa.text(
            """
            UPDATE series_metadonnees
            SET periode_fin = :fin_actuelle,
                libelle = regexp_replace(libelle, '-2025\\)$', '-2020)'),
                note_publique = left(note_publique, length(note_publique) - length(:phrase))
            WHERE code = ANY(:c) AND right(note_publique, length(:phrase)) = :phrase
            """
        ),
        {"fin_actuelle": FIN_ACTUELLE, "phrase": PHRASE, "c": codes},
    )
