"""fraction_diffuse_lots

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-30

Étend la **fraction diffuse NASA POWER** (``fraction_diffuse``, ADR-0014,
migration 0024), gravée aux 3 pilotes, aux **139 localités des lots nationaux**
(31 régions + 108 départements) — ADR-0017.

Formule de la fiche, **version 1 inchangée**, calculée depuis le mensuel NASA :
``moy(DHI) / moy(GHI)`` par mois, ``Σ DHI_m·n_m / Σ GHI_m·n_m`` par année (année
gravée seulement si ses 12 mois existent). Fenêtre 2001-2020 (DHI NASA, rupture
avant 2001, ADR-0013). Séries **mensuelles** uniquement (les séries
journalières NASA de 0026 sont exclues explicitement).

Grave 139 séries ``calcul_derive`` (``kuma_calculs``), **33 360 lignes
mensuelles** et **2 780 annuelles**, confiance B. Garde-fous : comptes, et toute
valeur dans ``[0, 1]``. ``ANALYZE grandeurs_metier`` en fin de migration.
``downgrade`` supprime les lignes puis les séries des lots ; les pilotes restent
intacts.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.lots_civ import points_lots_mensuels

# revision identifiers, used by Alembic.
revision: str = "0029"
down_revision: str | Sequence[str] | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANDEUR_CODE: str = "fraction_diffuse"
SOURCE_CALCUL: str = "kuma_calculs"
NB_POINTS: int = 139
NB_MENSUEL_ATTENDU: int = 33_360  # 139 × 240 mois (2001-2020)
NB_ANNUEL_ATTENDU: int = 2_780  # 139 × 20 ans


def _code_serie(localite_code: str) -> str:
    return f"fraction_diffuse_nasa_power_{localite_code}"


# Couples (DHI, GHI) NASA mensuels par (localité, année, mois), restreints aux
# séries cibles des lots.
_CTE: str = """
    WITH couples AS (
        SELECT sf.id AS serie_cible, sf.localite_id, md.annee, md.mois,
               md.valeur AS dhi, mg.valeur AS ghi,
               EXTRACT(
                   DAY FROM (make_date(md.annee, md.mois, 1) + INTERVAL '1 month - 1 day')
               )::int AS n_jours
        FROM series_metadonnees sf
        JOIN series_metadonnees sd
            ON sd.localite_id = sf.localite_id AND sd.grandeur_code = 'dhi'
           AND sd.granularite = 'mensuel'
        JOIN sources xd ON xd.id = sd.source_id AND xd.code = 'nasa_power'
        JOIN mesures_ressource_mensuelles md ON md.serie_id = sd.id
        JOIN series_metadonnees sg
            ON sg.localite_id = sf.localite_id AND sg.grandeur_code = 'ghi'
           AND sg.granularite = 'mensuel'
        JOIN sources xg ON xg.id = sg.source_id AND xg.code = 'nasa_power'
        JOIN mesures_ressource_mensuelles mg
            ON mg.serie_id = sg.id AND mg.annee = md.annee AND mg.mois = md.mois
        WHERE sf.code = ANY(:codes)
    )
"""


def upgrade() -> None:
    bind = op.get_bind()
    points = points_lots_mensuels()
    if len(points) != NB_POINTS:
        raise RuntimeError(f"Migration 0029 : {len(points)} localités, {NB_POINTS} attendues.")
    source_calcul_id = bind.execute(
        sa.text("SELECT id FROM sources WHERE code = :c"), {"c": SOURCE_CALCUL}
    ).scalar_one()
    loc = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:c)"),
            {"c": [code for code, _, _, _ in points]},
        ).all()
    }

    op.bulk_insert(
        sa.table(
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
        ),
        [
            {
                "code": _code_serie(code),
                "libelle": f"Fraction diffuse NASA POWER — {nom} (2001-2020)",
                "localite_id": loc[code],
                "grandeur_code": GRANDEUR_CODE,
                "source_id": source_calcul_id,
                "periode_debut": "2001-01-01",
                "periode_fin": "2020-12-31",
                "methode_collecte": "calcul_derive",
                "granularite": None,
                "note_publique": (
                    "Fraction diffuse DHI/GHI NASA POWER (Σ DHI / Σ GHI sur les jours de la "
                    "période), sans dimension, mensuelle et annuelle 2001-2020, calculée depuis "
                    "le mensuel NASA. Lot national (ADR-0017), même contrat que les pilotes "
                    "(ADR-0014). Confiance B."
                ),
            }
            for code, nom, _, _ in points
        ],
    )

    params = {"g": GRANDEUR_CODE, "codes": [_code_serie(code) for code, _, _, _ in points]}
    bind.execute(
        sa.text(
            _CTE
            + """
            INSERT INTO grandeurs_metier (
                grandeur_code, localite_id, series_metadonnees_id, periode_type,
                annee_debut, annee_fin, mois, version_formule, valeur,
                niveau_confiance_derive
            )
            SELECT :g, localite_id, serie_cible, 'mensuel', annee, annee, mois, 1,
                   dhi / ghi, 'B'
            FROM couples WHERE ghi > 0
            """
        ),
        params,
    )
    bind.execute(
        sa.text(
            _CTE
            + """
            INSERT INTO grandeurs_metier (
                grandeur_code, localite_id, series_metadonnees_id, periode_type,
                annee_debut, annee_fin, mois, version_formule, valeur,
                niveau_confiance_derive
            )
            SELECT :g, localite_id, serie_cible, 'annuel', annee, annee, NULL, 1,
                   -- Sommes en numeric : exactes, donc indépendantes de l'ordre
                   -- d'agrégation (résultat reproductible au bit près).
                   (SUM(dhi::numeric * n_jours) / SUM(ghi::numeric * n_jours))::float8, 'B'
            FROM couples
            GROUP BY localite_id, serie_cible, annee
            HAVING COUNT(*) = 12 AND SUM(ghi * n_jours) > 0
            """
        ),
        params,
    )

    comptes = dict(
        bind.execute(
            sa.text(
                "SELECT gm.periode_type, COUNT(*) FROM grandeurs_metier gm "
                "JOIN series_metadonnees s ON s.id = gm.series_metadonnees_id "
                "WHERE s.code = ANY(:codes) GROUP BY gm.periode_type"
            ),
            params,
        ).all()
    )
    attendu = {"mensuel": NB_MENSUEL_ATTENDU, "annuel": NB_ANNUEL_ATTENDU}
    if comptes != attendu:
        raise RuntimeError(f"Migration 0029 : lignes {comptes!r}, {attendu!r} attendues.")
    hors_domaine = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM grandeurs_metier WHERE grandeur_code = :g "
            "AND (valeur < 0 OR valeur > 1)"
        ),
        params,
    ).scalar_one()
    if hors_domaine:
        raise RuntimeError(f"Migration 0029 : {hors_domaine} valeur(s) hors de [0, 1].")
    bind.execute(sa.text("ANALYZE grandeurs_metier"))


def downgrade() -> None:
    bind = op.get_bind()
    codes = [_code_serie(code) for code, _, _, _ in points_lots_mensuels()]
    bind.execute(
        sa.text(
            "DELETE FROM grandeurs_metier WHERE series_metadonnees_id IN "
            "(SELECT id FROM series_metadonnees WHERE code = ANY(:c))"
        ),
        {"c": codes},
    )
    bind.execute(sa.text("DELETE FROM series_metadonnees WHERE code = ANY(:c)"), {"c": codes})
