"""fraction_diffuse_cams

Revision ID: 0040
Revises: 0039
Create Date: 2026-10-15

**Deuxième source de fraction diffuse** : grave ``fraction_diffuse`` (id 3)
depuis le **DHI** et le **GHI CAMS Radiation** mensuels (0022, 0014 et lots
nationaux, prolongés jusqu'en 2025 par 0030), aux **142 localités**, à côté de la
fraction diffuse NASA POWER (0024, 0029, 0032) — ADR-0025.

Formule de la fiche, **version 1 inchangée**, même politique que la série NASA
(ADR-0014, ADR-0017) : ``moy(DHI) / moy(GHI)`` par mois (= ``Σ DHI / Σ GHI`` sur
les jours du mois), ``Σ DHI_m·n_m / Σ GHI_m·n_m`` par année (``n_m`` = jours du
mois ; année gravée seulement si ses 12 mois existent dans les deux séries).
L'identité de ``grandeurs_metier`` inclut la série : les deux sources coexistent
sans collision.

Grave, **par jointure SQL hors-ligne** sur les séries CAMS **mensuelles** :

- 142 séries ``fraction_diffuse_cams_<localité>`` (``kuma_calculs``,
  ``calcul_derive``) ;
- **35 784 lignes mensuelles** (252 mois 2005-2025 × 142) et **2 982
  annuelles** (21 ans × 142), confiance B.

Sommes annuelles en ``numeric`` (exactes, indépendantes de l'ordre
d'agrégation). Garde-fous : aucune série ni ligne CAMS préexistante, 142 séries
DHI et GHI CAMS mensuelles en amont, comptes exacts, 21 années par localité,
toute valeur dans ``[0, 1]``. ``ANALYZE grandeurs_metier`` en fin de migration.
``downgrade`` supprime les lignes puis les séries CAMS ; la fraction diffuse NASA
reste intacte.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.lots_civ import CONTRATS_CAMS, FIN_EXTENSION, points_nationaux

# revision identifiers, used by Alembic.
revision: str = "0040"
down_revision: str | Sequence[str] | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANDEUR_CODE: str = "fraction_diffuse"
GRANDEUR_ID: int = 3
SOURCE_CALCUL: str = "kuma_calculs"
SOURCE_AMONT: str = "cams_radiation"
ANNEE_DEBUT: int = 2005  # CAMS Radiation (ADR-0011)
ANNEE_FIN: int = FIN_EXTENSION[SOURCE_AMONT]  # 2025 (ADR-0018)
NB_POINTS: int = 142
NB_MENSUEL_ATTENDU: int = 35_784  # 142 × 252 mois (2005-2025)
NB_ANNUEL_ATTENDU: int = 2_982  # 142 × 21 ans


def code_serie(localite_code: str) -> str:
    """Code de la série calculée d'une localité."""
    return f"fraction_diffuse_cams_{localite_code}"


def _codes_series() -> list[str]:
    return [code_serie(code) for code, _, _, _ in points_nationaux()]


# Couples (DHI, GHI) CAMS mensuels par (localité, année, mois), restreints aux
# séries cibles, avec le nombre de jours du mois.
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
           AND sd.granularite = 'mensuel' AND sd.code = ANY(:amont)
        JOIN sources xd ON xd.id = sd.source_id AND xd.code = :src
        JOIN mesures_ressource_mensuelles md ON md.serie_id = sd.id
        JOIN series_metadonnees sg
            ON sg.localite_id = sf.localite_id AND sg.grandeur_code = 'ghi'
           AND sg.granularite = 'mensuel' AND sg.code = ANY(:amont)
        JOIN sources xg ON xg.id = sg.source_id AND xg.code = :src
        JOIN mesures_ressource_mensuelles mg
            ON mg.serie_id = sg.id AND mg.annee = md.annee AND mg.mois = md.mois
        WHERE sf.code = ANY(:codes)
    )
"""


def upgrade() -> None:
    bind = op.get_bind()
    points = points_nationaux()
    if len(points) != NB_POINTS:
        raise RuntimeError(f"Migration 0040 : {len(points)} localités, {NB_POINTS} attendues.")
    codes = _codes_series()

    # 0. Garde-fous : grandeur conforme au seed 0002, aucune série CAMS préexistante.
    row = bind.execute(
        sa.text("SELECT id, strategie_calcul FROM grandeurs_referentiel WHERE code = :c"),
        {"c": GRANDEUR_CODE},
    ).one_or_none()
    if row is None or row.id != GRANDEUR_ID or row.strategie_calcul != "stockee":
        raise RuntimeError(f"Migration 0040 : grandeur {GRANDEUR_CODE!r} hors contrat : {row!r}.")
    preexistantes = bind.execute(
        sa.text("SELECT COUNT(*) FROM series_metadonnees WHERE code = ANY(:c)"), {"c": codes}
    ).scalar_one()
    if preexistantes:
        raise RuntimeError(f"Migration 0040 : {preexistantes} série(s) CAMS déjà présente(s).")

    # 1. Séries DHI et GHI CAMS mensuelles en amont : une par localité et grandeur.
    codes_amont = [
        CONTRATS_CAMS[g].code_serie(code) for g in ("dhi", "ghi") for code, _, _, _ in points
    ]
    amont = bind.execute(
        sa.text(
            """
            SELECT s.grandeur_code, COUNT(*) AS n
            FROM series_metadonnees s JOIN sources src ON src.id = s.source_id
            WHERE s.code = ANY(:c) AND src.code = :src AND s.granularite = 'mensuel'
              AND s.periode_debut = :debut AND s.periode_fin = :fin
            GROUP BY s.grandeur_code
            """
        ),
        {
            "c": codes_amont,
            "src": SOURCE_AMONT,
            "debut": f"{ANNEE_DEBUT}-01-01",
            "fin": f"{ANNEE_FIN}-12-31",
        },
    ).all()
    if dict(amont) != {"dhi": NB_POINTS, "ghi": NB_POINTS}:
        raise RuntimeError(f"Migration 0040 : séries CAMS amont {dict(amont)!r}.")

    # 2. Séries calculées (une par localité), source éditoriale kuma_calculs.
    source_calcul_id = bind.execute(
        sa.text("SELECT id FROM sources WHERE code = :c"), {"c": SOURCE_CALCUL}
    ).scalar_one()
    loc = {
        r.code: r.id
        for r in bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:c)"),
            {"c": [code for code, _, _, _ in points]},
        ).all()
    }
    manquants = [code for code, _, _, _ in points if code not in loc]
    if manquants:
        raise RuntimeError(f"Migration 0040 : localité(s) introuvable(s) : {manquants!r}.")
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
                "code": code_serie(code),
                "libelle": f"Fraction diffuse CAMS Radiation — {nom} ({ANNEE_DEBUT}-{ANNEE_FIN})",
                "localite_id": loc[code],
                "grandeur_code": GRANDEUR_CODE,
                "source_id": source_calcul_id,
                "periode_debut": f"{ANNEE_DEBUT}-01-01",
                "periode_fin": f"{ANNEE_FIN}-12-31",
                "methode_collecte": "calcul_derive",
                "granularite": None,
                "note_publique": (
                    "Fraction diffuse DHI/GHI CAMS Radiation (Σ DHI / Σ GHI sur les jours de "
                    f"la période), sans dimension, mensuelle et annuelle {ANNEE_DEBUT}-"
                    f"{ANNEE_FIN}, calculée depuis le mensuel CAMS. Deuxième source à côté de "
                    "la fraction diffuse NASA POWER, même formule et même politique "
                    "(ADR-0025). Confiance B (deux entrées satellite B)."
                ),
            }
            for code, nom, _, _ in points
        ],
    )

    # 3. Lignes mensuelles puis annuelles (pondérées par les jours, sommes en numeric).
    params = {"g": GRANDEUR_CODE, "src": SOURCE_AMONT, "codes": codes, "amont": codes_amont}
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

    # 4. Garde-fous durs : comptes, couverture par localité, domaine [0, 1].
    bilan = {
        r.periode_type: tuple(r)[1:]
        for r in bind.execute(
            sa.text(
                """
                SELECT gm.periode_type, COUNT(*) AS n,
                       COUNT(DISTINCT gm.series_metadonnees_id) AS series,
                       MIN(gm.annee_debut) AS debut, MAX(gm.annee_debut) AS fin,
                       COUNT(*) FILTER (WHERE gm.valeur < 0 OR gm.valeur > 1) AS hors_domaine
                FROM grandeurs_metier gm
                JOIN series_metadonnees s ON s.id = gm.series_metadonnees_id
                WHERE s.code = ANY(:codes)
                GROUP BY gm.periode_type
                """
            ),
            params,
        ).all()
    }
    attendu = {
        "mensuel": (NB_MENSUEL_ATTENDU, NB_POINTS, ANNEE_DEBUT, ANNEE_FIN, 0),
        "annuel": (NB_ANNUEL_ATTENDU, NB_POINTS, ANNEE_DEBUT, ANNEE_FIN, 0),
    }
    if bilan != attendu:
        raise RuntimeError(f"Migration 0040 : bilan {bilan!r}, {attendu!r} attendu.")
    bind.execute(sa.text("ANALYZE grandeurs_metier"))


def downgrade() -> None:
    bind = op.get_bind()
    codes = _codes_series()
    bind.execute(
        sa.text(
            "DELETE FROM grandeurs_metier WHERE series_metadonnees_id IN "
            "(SELECT id FROM series_metadonnees WHERE code = ANY(:c))"
        ),
        {"c": codes},
    )
    bind.execute(sa.text("DELETE FROM series_metadonnees WHERE code = ANY(:c)"), {"c": codes})
    # La grandeur fraction_diffuse (seed 0002) et la série NASA sont conservées.
