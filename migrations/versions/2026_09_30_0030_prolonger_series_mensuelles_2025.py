"""prolonger_series_mensuelles_2025

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-30

**Extension temporelle** (ADR-0018) : prolonge les **1420 séries mensuelles
brutes** déjà gravées (10 familles source × grandeur, 142 localités : 3 pilotes
0008-0022, 31 régions 0025, 108 départements 0027) au-delà de 2020, jusqu'à la
dernière année servie par chaque source :

| Source | Grandeurs | Ajout | Mesures |
|---|---|---|---:|
| NASA POWER | GHI, DNI, DHI | 2021-2025 | 25 560 |
| CAMS Radiation | GHI, DNI, DHI | 2021-2025 | 25 560 |
| SARAH-3 (PVGIS) | GHI, DNI | 2021-2023 | 10 224 |
| ERA5 (PVGIS) | GHI, DNI | 2021-2023 | 10 224 |

Soit **71 568 mesures**, aux **mêmes contrats** (source, méthode, conversion,
confiance B) et sous les **mêmes codes de série** : les séries sont prolongées,
pas dupliquées. Les valeurs 1991-2020 déjà gravées ne sont pas touchées ; la
normale climatologique NASA 1991-2020 reste la référence.

Métadonnées : ``periode_fin`` passe à la fin servie ; le libellé « (AAAA-2020) »
devient « (AAAA-fin) » ; une phrase est **ajoutée** à la note publique (le texte
existant, par exemple « climatologie 1991-2020 », reste vrai et n'est pas
réécrit).

Valeurs lues hors-ligne dans les CSV gzip ``*_ext_2021_2025.csv.gz`` (générés par
les ingesteurs avec ``--extension``) et validées par ``lire_series``. Garde-fous :
chaque série existe, finit en 2020 et n'a aucune mesure après 2020 ; nombre de
mesures par famille et total. ``ANALYZE`` en fin de migration. ``downgrade``
supprime les mesures postérieures à 2020 et restaure période, libellé et note.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.lots_civ import CONTRATS_EXTENSION, LOT_EXTENSION, points_nationaux
from kuma_data_core.db.seeds.series_csv import lire_series

# revision identifiers, used by Alembic.
revision: str = "0030"
down_revision: str | Sequence[str] | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NB_POINTS: int = 142
NB_MESURES_ATTENDU: int = 71_568  # 142 × (6 × 60 + 4 × 36)
FIN_ACTUELLE: str = "2020-12-31"


def _phrase(fin: int) -> str:
    return f" Prolongée jusqu'en {fin} (ADR-0018)."


def _codes(contrat: Any) -> list[str]:
    return [contrat.code_serie(code) for code, _, _, _ in points_nationaux()]


def upgrade() -> None:
    bind = op.get_bind()
    codes_loc = sorted(code for code, _, _, _ in points_nationaux())
    if len(codes_loc) != NB_POINTS:
        raise RuntimeError(f"Migration 0030 : {len(codes_loc)} localités, {NB_POINTS} attendues.")

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
    for contrat in CONTRATS_EXTENSION:
        series = lire_series(contrat, LOT_EXTENSION)
        if sorted(s["localite_code"] for s in series) != codes_loc:
            raise RuntimeError(
                f"Migration 0030 : {contrat.nom_fichier(LOT_EXTENSION)} ne couvre pas les "
                f"{NB_POINTS} localités."
            )
        existantes = {
            row.code: row
            for row in bind.execute(
                sa.text(
                    """
                    SELECT s.code, s.id, s.periode_fin, s.granularite, src.code AS source,
                           s.grandeur_code,
                           (SELECT COUNT(*) FROM mesures_ressource_mensuelles m
                            WHERE m.serie_id = s.id AND m.annee > 2020) AS apres_2020
                    FROM series_metadonnees s JOIN sources src ON src.id = s.source_id
                    WHERE s.code = ANY(:c)
                    """
                ),
                {"c": [s["code"] for s in series]},
            ).all()
        }
        for s in series:
            e = existantes.get(s["code"])
            if (
                e is None
                or str(e.periode_fin) != FIN_ACTUELLE
                or e.granularite != "mensuel"
                or e.source != contrat.source_code
                or e.grandeur_code != contrat.grandeur_code
                or e.apres_2020
            ):
                raise RuntimeError(f"Migration 0030 : série {s['code']!r} hors contrat : {e!r}.")

        # 1. Métadonnées : fin de période, libellé, note (phrase ajoutée).
        for s in series:
            bind.execute(
                sa.text(
                    """
                    UPDATE series_metadonnees
                    SET periode_fin = :fin,
                        libelle = regexp_replace(libelle, '-2020\\)$', :suffixe),
                        note_publique = note_publique || :phrase
                    WHERE id = :id
                    """
                ),
                {
                    "fin": contrat.periode_fin,
                    "suffixe": f"-{contrat.annee_fin})",
                    "phrase": _phrase(contrat.annee_fin),
                    "id": existantes[s["code"]].id,
                },
            )

        # 2. Mesures 2021+.
        payload: list[dict[str, Any]] = [
            {
                "serie_id": existantes[s["code"]].id,
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
                f"Migration 0030 : {contrat.prefixe_code} : {len(payload)} mesures, "
                f"{NB_POINTS * contrat.nb_mois} attendues."
            )
        op.bulk_insert(mesures_table, payload)
        total += len(payload)

    if total != NB_MESURES_ATTENDU:
        raise RuntimeError(f"Migration 0030 : {total} mesures, {NB_MESURES_ATTENDU} attendues.")
    bind.execute(sa.text("ANALYZE mesures_ressource_mensuelles"))
    bind.execute(sa.text("ANALYZE series_metadonnees"))


def downgrade() -> None:
    bind = op.get_bind()
    for contrat in CONTRATS_EXTENSION:
        codes = _codes(contrat)
        bind.execute(
            sa.text(
                "DELETE FROM mesures_ressource_mensuelles WHERE annee > 2020 AND serie_id IN "
                "(SELECT id FROM series_metadonnees WHERE code = ANY(:c))"
            ),
            {"c": codes},
        )
        bind.execute(
            sa.text(
                """
                UPDATE series_metadonnees
                SET periode_fin = :fin_actuelle,
                    libelle = regexp_replace(libelle, :motif, '-2020)'),
                    note_publique = left(note_publique, length(note_publique) - length(:phrase))
                WHERE code = ANY(:c) AND right(note_publique, length(:phrase)) = :phrase
                """
            ),
            {
                "fin_actuelle": FIN_ACTUELLE,
                "motif": re.escape(f"-{contrat.annee_fin})") + "$",
                "phrase": _phrase(contrat.annee_fin),
                "c": codes,
            },
        )
