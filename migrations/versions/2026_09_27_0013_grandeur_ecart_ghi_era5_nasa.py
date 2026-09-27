"""grandeur_ecart_ghi_era5_nasa

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-27

**Deuxième grandeur dérivée** (triangulation, ADR-0010) : écart inter-source
relatif du GHI entre **ERA5** (réanalyse, via PVGIS) et **NASA POWER**, aux 3
points. Complète ``ecart_relatif_ghi_sarah3_nasa`` (0011) : les deux écarts
partagent la **même référence NASA POWER** (dénominateur), donc sont
directement comparables — c'est ce qui permet de **localiser l'aberrant** par
(localité, mois).

Contrat **identique à ADR-0009** : grandeur ``ecart_relatif_ghi_era5_nasa``
(``grandeurs_referentiel``, id 36), unité ``pourcent``, famille ``F1``,
``strategie_calcul='stockee'``, formule ``(era5 − nasa) / nasa × 100``, matérialisée
dans ``grandeurs_metier`` (``periode_type='mensuel'``) sur la **fenêtre commune
2005-2020** — 576 lignes (192 mois × 3), confiance dérivée **B**.

Calcul **hors-ligne, en base, par jointure SQL** sur les mesures déjà gravées
(0008 GHI NASA + 0012 GHI ERA5) : la jointure ne produit que l'intersection des
(localité, année, mois). **Aucun seed, aucun réseau.** Garde-fou dur
``COUNT = 576``. ``downgrade`` supprime les mesures dérivées, les 3 séries, puis
la grandeur.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANDEUR_CODE: str = "ecart_relatif_ghi_era5_nasa"
GRANDEUR_ID: int = 36
SOURCE_CALCUL: str = "kuma_calculs"
SOURCE_NASA: str = "nasa_power"
SOURCE_ERA5: str = "era5_pvgis"
PERIODE_DEBUT: str = "2005-01-01"
PERIODE_FIN: str = "2020-12-31"
NB_LIGNES_ATTENDU: int = 576  # 192 mois (2005-2020) × 3 localités

# (code localité, nom d'affichage) — les 3 points déjà gravés (0008/0012).
_POINTS: tuple[tuple[str, str], ...] = (
    ("civ_dep_abidjan", "Abidjan"),
    ("civ_dep_yamoussoukro", "Yamoussoukro"),
    ("civ_dep_korhogo", "Korhogo"),
)

_CODES_SERIES: tuple[str, ...] = tuple(f"ecart_ghi_era5_nasa_{code}" for code, _ in _POINTS)


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Grandeur dérivée (id explicite, cf. seed 0002 : referentiels à id figé).
    grandeurs_table = sa.table(
        "grandeurs_referentiel",
        sa.column("id", sa.BigInteger),
        sa.column("code", sa.String),
        sa.column("libelle", sa.Text),
        sa.column("unite_id", sa.BigInteger),
        sa.column("famille", sa.String),
        sa.column("strategie_calcul", sa.String),
        sa.column("version_formule_actuelle", sa.Integer),
        sa.column("description", sa.Text),
    )
    unite_pourcent = bind.execute(
        sa.text("SELECT id FROM unites WHERE code = 'pourcent'")
    ).scalar_one()
    op.bulk_insert(
        grandeurs_table,
        [
            {
                "id": GRANDEUR_ID,
                "code": GRANDEUR_CODE,
                "libelle": "Écart relatif GHI ERA5 par rapport à NASA POWER",
                "unite_id": unite_pourcent,
                "famille": "F1",
                "strategie_calcul": "stockee",
                "version_formule_actuelle": 1,
                "description": (
                    "Écart relatif inter-source du GHI mensuel entre ERA5 (réanalyse, "
                    "comparée) et NASA POWER (référence), formule (era5 − nasa) / nasa × "
                    "100, en pourcent signé. Déterministe, indépendante du périmètre, "
                    "matérialisée dans grandeurs_metier par (localité, année, mois) sur "
                    "la fenêtre commune 2005-2020 (3 points CIV). Partage la référence "
                    "NASA POWER avec ecart_relatif_ghi_sarah3_nasa : triangulation "
                    "inter-source (ADR-0010). strategie_calcul=stockee. Famille F1."
                ),
            }
        ],
    )

    # 2. Séries calculées (une par localité), source éditoriale kuma_calculs.
    source_calcul_id = bind.execute(
        sa.text("SELECT id FROM sources WHERE code = :c"), {"c": SOURCE_CALCUL}
    ).scalar_one()
    loc = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:c)"),
            {"c": [code for code, _ in _POINTS]},
        ).all()
    }
    manquants = [code for code, _ in _POINTS if code not in loc]
    if manquants:
        raise RuntimeError(f"Migration 0013 : localité(s) introuvable(s) : {manquants!r}.")

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
                "code": f"ecart_ghi_era5_nasa_{code}",
                "libelle": f"Écart relatif GHI ERA5 vs NASA POWER — {nom} (2005-2020)",
                "localite_id": loc[code],
                "grandeur_code": GRANDEUR_CODE,
                "source_id": source_calcul_id,
                "periode_debut": PERIODE_DEBUT,
                "periode_fin": PERIODE_FIN,
                "methode_collecte": "calcul_derive",
                "granularite": None,
                "note_publique": (
                    "Écart relatif mensuel du GHI entre ERA5 (réanalyse, via PVGIS) et "
                    "NASA POWER (référence), (era5 − nasa) / nasa × 100 en %, sur les mois "
                    "communs 2005-2020. Positif = ERA5 plus haut. Confiance B (dérivée "
                    "d'une réanalyse B et d'un satellite B). Même référence NASA POWER "
                    "que l'écart SARAH-3 : triangulation inter-source."
                ),
            }
            for (code, nom) in _POINTS
        ],
    )

    # 3. Calcul de l'écart en base, par jointure SQL sur la fenêtre commune.
    #    La jointure ERA5↔NASA sur (localité, année, mois) ne produit que
    #    l'intersection : la fenêtre commune 2005-2020 est garantie par
    #    construction (ADR-0009 piège 2). Aucun accès réseau ni seed.
    bind.execute(
        sa.text(
            """
            INSERT INTO grandeurs_metier (
                grandeur_code, localite_id, series_metadonnees_id, periode_type,
                annee_debut, annee_fin, mois, version_formule, valeur,
                niveau_confiance_derive
            )
            SELECT
                :grandeur_code,
                se.localite_id,
                se.id,
                'mensuel',
                me.annee, me.annee, me.mois,
                1,
                (me.valeur - mn.valeur) / mn.valeur * 100.0,
                'B'
            FROM mesures_ressource_mensuelles me
            JOIN series_metadonnees ss
                ON ss.id = me.serie_id AND ss.grandeur_code = 'ghi'
            JOIN sources src_e
                ON src_e.id = ss.source_id AND src_e.code = :src_era5
            JOIN series_metadonnees sn
                ON sn.grandeur_code = 'ghi' AND sn.localite_id = ss.localite_id
            JOIN sources src_n
                ON src_n.id = sn.source_id AND src_n.code = :src_nasa
            JOIN mesures_ressource_mensuelles mn
                ON mn.serie_id = sn.id AND mn.annee = me.annee AND mn.mois = me.mois
            JOIN series_metadonnees se
                ON se.grandeur_code = :grandeur_code AND se.localite_id = ss.localite_id
            """
        ),
        {
            "grandeur_code": GRANDEUR_CODE,
            "src_era5": SOURCE_ERA5,
            "src_nasa": SOURCE_NASA,
        },
    )

    nb = bind.execute(
        sa.text("SELECT COUNT(*) FROM grandeurs_metier WHERE grandeur_code = :c"),
        {"c": GRANDEUR_CODE},
    ).scalar_one()
    if nb != NB_LIGNES_ATTENDU:
        raise RuntimeError(
            f"Migration 0013 : {nb} lignes d'écart calculées, {NB_LIGNES_ATTENDU} attendues "
            "(fenêtre commune 2005-2020 × 3 points)."
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM grandeurs_metier WHERE grandeur_code = :c"),
        {"c": GRANDEUR_CODE},
    )
    bind.execute(
        sa.text("DELETE FROM series_metadonnees WHERE code = ANY(:c)"),
        {"c": list(_CODES_SERIES)},
    )
    bind.execute(
        sa.text("DELETE FROM grandeurs_referentiel WHERE code = :c"),
        {"c": GRANDEUR_CODE},
    )
