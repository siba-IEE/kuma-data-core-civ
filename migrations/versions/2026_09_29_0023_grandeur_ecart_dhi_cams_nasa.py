"""grandeur_ecart_dhi_cams_nasa

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-29

**Premier écart inter-source DHI** de l'instance (ADR-0013) : écart relatif du
DHI entre **CAMS Radiation** (0022) et **NASA POWER** (0021), aux 3 points. Même
référence NASA POWER au dénominateur que tous les écarts GHI et DNI.

Contrat **identique à ADR-0009** : grandeur ``ecart_relatif_dhi_cams_nasa``
(``grandeurs_referentiel``, id 41), unité ``pourcent``, famille ``F1``,
``strategie_calcul='stockee'``, formule ``(cams − nasa) / nasa × 100``,
matérialisée dans ``grandeurs_metier`` (``periode_type='mensuel'``) sur la
**fenêtre commune 2005-2020** — 576 lignes (192 mois × 3), confiance dérivée **B**.

Calcul **hors-ligne, en base, par jointure SQL** sur les mesures déjà gravées
(0021 DHI NASA 1991-2020 + 0022 DHI CAMS 2005-2020) : la jointure ne produit que
l'intersection 2005-2020. **Aucun seed, aucun réseau.** Garde-fou dur
``COUNT = 576``. ``downgrade`` supprime les mesures dérivées, les 3 séries, puis
la grandeur.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANDEUR_CODE: str = "ecart_relatif_dhi_cams_nasa"
GRANDEUR_BRUTE: str = "dhi"
GRANDEUR_ID: int = 41
SOURCE_CALCUL: str = "kuma_calculs"
SOURCE_NASA: str = "nasa_power"
SOURCE_CAMS: str = "cams_radiation"
PERIODE_DEBUT: str = "2005-01-01"
PERIODE_FIN: str = "2020-12-31"
NB_LIGNES_ATTENDU: int = 576  # 192 mois (2005-2020) × 3 localités

# (code localité, nom d'affichage) — les 3 points déjà gravés (0021/0022).
_POINTS: tuple[tuple[str, str], ...] = (
    ("civ_dep_abidjan", "Abidjan"),
    ("civ_dep_yamoussoukro", "Yamoussoukro"),
    ("civ_dep_korhogo", "Korhogo"),
)

_CODES_SERIES: tuple[str, ...] = tuple(f"ecart_dhi_cams_nasa_{code}" for code, _ in _POINTS)


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
                "libelle": "Écart relatif DHI CAMS Radiation par rapport à NASA POWER",
                "unite_id": unite_pourcent,
                "famille": "F1",
                "strategie_calcul": "stockee",
                "version_formule_actuelle": 1,
                "description": (
                    "Écart relatif inter-source du DHI mensuel entre CAMS Radiation (Heliosat-4, "
                    "comparée) et NASA POWER (référence), formule (cams − nasa) / nasa × 100, en "
                    "pourcent signé. Déterministe, indépendante du périmètre, matérialisée dans "
                    "grandeurs_metier par (localité, année, mois) sur la fenêtre commune 2005-2020 "
                    "(3 points CIV). Premier écart DHI de l'instance ; NASA POWER au dénominateur "
                    "comme tous les écarts CIV (ADR-0013). strategie_calcul=stockee. Famille F1."
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
        raise RuntimeError(f"Migration 0023 : localité(s) introuvable(s) : {manquants!r}.")

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
                "code": f"ecart_dhi_cams_nasa_{code}",
                "libelle": f"Écart relatif DHI CAMS vs NASA POWER — {nom} (2005-2020)",
                "localite_id": loc[code],
                "grandeur_code": GRANDEUR_CODE,
                "source_id": source_calcul_id,
                "periode_debut": PERIODE_DEBUT,
                "periode_fin": PERIODE_FIN,
                "methode_collecte": "calcul_derive",
                "granularite": None,
                "note_publique": (
                    "Écart relatif mensuel du DHI entre CAMS Radiation (Heliosat-4, ADS) et NASA "
                    "POWER (référence), (cams − nasa) / nasa × 100 en %, sur les mois communs "
                    "2005-2020. Positif = CAMS plus haut. Confiance B (dérivée de deux "
                    "satellites B). NASA POWER au dénominateur, comme tous les écarts CIV."
                ),
            }
            for (code, nom) in _POINTS
        ],
    )

    # 3. Calcul de l'écart en base, par jointure SQL sur la fenêtre commune.
    #    La jointure CAMS↔NASA (DHI) sur (localité, année, mois) ne produit
    #    que l'intersection : la fenêtre commune 2005-2020 est garantie par
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
                ON ss.id = me.serie_id AND ss.grandeur_code = :grandeur_brute
            JOIN sources src_c
                ON src_c.id = ss.source_id AND src_c.code = :src_cams
            JOIN series_metadonnees sn
                ON sn.grandeur_code = :grandeur_brute AND sn.localite_id = ss.localite_id
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
            "src_cams": SOURCE_CAMS,
            "grandeur_brute": GRANDEUR_BRUTE,
            "src_nasa": SOURCE_NASA,
        },
    )

    nb = bind.execute(
        sa.text("SELECT COUNT(*) FROM grandeurs_metier WHERE grandeur_code = :c"),
        {"c": GRANDEUR_CODE},
    ).scalar_one()
    if nb != NB_LIGNES_ATTENDU:
        raise RuntimeError(
            f"Migration 0023 : {nb} lignes d'écart calculées, {NB_LIGNES_ATTENDU} attendues "
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
