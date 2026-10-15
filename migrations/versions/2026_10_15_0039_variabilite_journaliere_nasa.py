"""variabilite_journaliere_nasa

Revision ID: 0039
Revises: 0038
Create Date: 2026-10-15

Matérialise la grandeur **``variabilite_journaliere``** (id 5, seedée en 0002, F1
``stockee``, sans dimension) aux **34 localités du journalier NASA POWER**
(3 pilotes + 31 régions, ADR-0016), depuis le **GHI journalier** NASA (migration
0026, prolongé jusqu'en 2025 par 0031) — ADR-0024.

Définition héritée, **version 1 inchangée** (fiche
``docs/methodologie/grandeurs/variabilite_journaliere.md`` et service
``services/grandeurs/variabilite_journaliere.py``) :

    CoV(annee) := σ(GHI_jour sur annee) / μ(GHI_jour sur annee)

σ est l'écart-type **de population** (division par N, ``ddof=0`` : c'est ce que
calcule le service, la fiche le nomme « d'échantillon » mais précise « divisé par
N »), μ la moyenne arithmétique. **Annuel uniquement** ; une année n'est gravée que
si **tous ses jours civils** (365 ou 366) sont présents et si μ > 0 (complétude
stricte de la fiche, ici vérifiée au grain journalier). Mesures courantes
seulement (``valide_au IS NULL``, statut non ``deprecie``), comme le service.

Grave, **par agrégation SQL hors-ligne** sur ``mesures_ressource`` (aucun seed,
aucun réseau) :

- 34 séries calculées ``variabilite_journaliere_nasa_power_<localité>`` (source
  ``kuma_calculs``, ``calcul_derive``) ;
- **1 190 lignes annuelles** (35 ans 1991-2025 × 34 localités), confiance **B**.

Sommes en ``numeric`` : ``stddev_pop`` et ``avg`` y sont exacts (sommes des
valeurs et des carrés sans arrondi), donc indépendants de l'ordre d'agrégation ;
le quotient est converti en ``float8`` (reproductible au bit près, ADR-0017).

Garde-fous durs : grandeur conforme (id, stratégie, version de formule), aucune
série ni ligne ``variabilite_journaliere`` préexistante, exactement 34 séries GHI
journalières NASA en amont, 1 190 lignes et 35 années par localité, toute valeur
dans ``]0, 1[``. ``ANALYZE grandeurs_metier`` en fin de migration. ``downgrade``
supprime les lignes puis les séries ; la grandeur (seed 0002) est conservée.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.lots_civ import CONTRATS_NASA_JOURNALIERS, points_journalier

# revision identifiers, used by Alembic.
revision: str = "0039"
down_revision: str | Sequence[str] | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANDEUR_CODE: str = "variabilite_journaliere"
GRANDEUR_ID: int = 5
VERSION_FORMULE: int = 1
SOURCE_CALCUL: str = "kuma_calculs"
ANNEE_DEBUT: int = 1991  # GHI journalier NASA (ADR-0016)
ANNEE_FIN: int = 2025  # prolongé par 0031 (ADR-0018)
NB_POINTS: int = 34
NB_ANNUEL_ATTENDU: int = 1_190  # 34 localités × 35 ans (1991-2025)


def code_serie(localite_code: str) -> str:
    """Code de la série calculée d'une localité."""
    return f"variabilite_journaliere_nasa_power_{localite_code}"


def _codes_series() -> list[str]:
    return [code_serie(code) for code, _, _, _ in points_journalier()]


def upgrade() -> None:
    bind = op.get_bind()
    points = points_journalier()
    if len(points) != NB_POINTS:
        raise RuntimeError(f"Migration 0039 : {len(points)} localités, {NB_POINTS} attendues.")

    # 0. Garde-fous : grandeur conforme au seed 0002, rien de préexistant.
    row = bind.execute(
        sa.text(
            "SELECT id, strategie_calcul, version_formule_actuelle "
            "FROM grandeurs_referentiel WHERE code = :c"
        ),
        {"c": GRANDEUR_CODE},
    ).one_or_none()
    if (
        row is None
        or row.id != GRANDEUR_ID
        or row.strategie_calcul != "stockee"
        or row.version_formule_actuelle != VERSION_FORMULE
    ):
        raise RuntimeError(f"Migration 0039 : grandeur {GRANDEUR_CODE!r} hors contrat : {row!r}.")
    preexistantes = bind.execute(
        sa.text(
            "SELECT (SELECT COUNT(*) FROM series_metadonnees WHERE grandeur_code = :c) "
            "+ (SELECT COUNT(*) FROM grandeurs_metier WHERE grandeur_code = :c)"
        ),
        {"c": GRANDEUR_CODE},
    ).scalar_one()
    if preexistantes:
        raise RuntimeError(f"Migration 0039 : {GRANDEUR_CODE!r} déjà présente.")

    # 1. Séries GHI journalières NASA en amont : une par localité, période 1991-2025.
    contrat_ghi = CONTRATS_NASA_JOURNALIERS["ghi"]
    amont = bind.execute(
        sa.text(
            """
            SELECT COUNT(*) AS n,
                   COUNT(*) FILTER (
                       WHERE s.granularite = 'journalier' AND s.grandeur_code = 'ghi'
                         AND src.code = 'nasa_power'
                         AND s.periode_debut = :debut AND s.periode_fin = :fin
                   ) AS conformes
            FROM series_metadonnees s JOIN sources src ON src.id = s.source_id
            WHERE s.code = ANY(:c)
            """
        ),
        {
            "c": [contrat_ghi.code_serie(code) for code, _, _, _ in points],
            "debut": f"{ANNEE_DEBUT}-01-01",
            "fin": f"{ANNEE_FIN}-12-31",
        },
    ).one()
    if (amont.n, amont.conformes) != (NB_POINTS, NB_POINTS):
        raise RuntimeError(f"Migration 0039 : séries GHI journalières amont {tuple(amont)!r}.")

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
        raise RuntimeError(f"Migration 0039 : localité(s) introuvable(s) : {manquants!r}.")
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
                "libelle": (
                    f"Variabilité journalière du GHI NASA POWER — {nom} ({ANNEE_DEBUT}-{ANNEE_FIN})"
                ),
                "localite_id": loc[code],
                "grandeur_code": GRANDEUR_CODE,
                "source_id": source_calcul_id,
                "periode_debut": f"{ANNEE_DEBUT}-01-01",
                "periode_fin": f"{ANNEE_FIN}-12-31",
                "methode_collecte": "calcul_derive",
                "granularite": None,
                "note_publique": (
                    "Coefficient de variation annuel du GHI journalier NASA POWER "
                    "(écart-type de population / moyenne des jours de l'année), sans "
                    f"dimension, {ANNEE_DEBUT}-{ANNEE_FIN}. Année gravée seulement si tous "
                    "ses jours civils sont présents. Annuel uniquement : un mois est trop "
                    "court pour un coefficient de variation robuste. Confiance B (entrée "
                    "satellite B). ADR-0024."
                ),
            }
            for code, nom, _, _ in points
        ],
    )

    # 3. Lignes annuelles : σ_pop / μ des GHI journaliers, années civiles complètes.
    bind.execute(
        sa.text(
            """
            WITH jours AS (
                SELECT sv.id AS serie_cible, sv.localite_id,
                       EXTRACT(YEAR FROM m.instant_mesure)::int AS annee,
                       m.valeur::numeric AS ghi
                FROM series_metadonnees sv
                JOIN series_metadonnees sg
                    ON sg.localite_id = sv.localite_id AND sg.grandeur_code = 'ghi'
                   AND sg.granularite = 'journalier' AND sg.code = ANY(:amont)
                JOIN sources xg ON xg.id = sg.source_id AND xg.code = 'nasa_power'
                JOIN mesures_ressource m
                    ON m.serie_id = sg.id AND m.valide_au IS NULL AND m.statut <> 'deprecie'
                WHERE sv.code = ANY(:codes)
            )
            INSERT INTO grandeurs_metier (
                grandeur_code, localite_id, series_metadonnees_id, periode_type,
                annee_debut, annee_fin, mois, version_formule, valeur,
                niveau_confiance_derive
            )
            SELECT :g, localite_id, serie_cible, 'annuel', annee, annee, NULL, :v,
                   -- numeric : stddev_pop et avg exacts, donc indépendants de l'ordre
                   -- d'agrégation (résultat reproductible au bit près).
                   (stddev_pop(ghi) / avg(ghi))::float8, 'B'
            FROM jours
            GROUP BY localite_id, serie_cible, annee
            HAVING COUNT(*) = make_date(annee + 1, 1, 1) - make_date(annee, 1, 1)
               AND avg(ghi) > 0
            """
        ),
        {
            "g": GRANDEUR_CODE,
            "v": VERSION_FORMULE,
            "codes": _codes_series(),
            "amont": [contrat_ghi.code_serie(code) for code, _, _, _ in points],
        },
    )

    # 4. Garde-fous durs : comptes, couverture par localité, domaine ]0, 1[.
    bilan = bind.execute(
        sa.text(
            """
            SELECT COUNT(*) AS n,
                   COUNT(DISTINCT gm.series_metadonnees_id) AS series,
                   MIN(gm.annee_debut) AS debut, MAX(gm.annee_debut) AS fin,
                   COUNT(*) FILTER (WHERE gm.periode_type <> 'annuel') AS non_annuel,
                   COUNT(*) FILTER (WHERE NOT (gm.valeur > 0 AND gm.valeur < 1)) AS hors_domaine
            FROM grandeurs_metier gm
            WHERE gm.grandeur_code = :g
            """
        ),
        {"g": GRANDEUR_CODE},
    ).one()
    attendu = (NB_ANNUEL_ATTENDU, NB_POINTS, ANNEE_DEBUT, ANNEE_FIN, 0, 0)
    if tuple(bilan) != attendu:
        raise RuntimeError(f"Migration 0039 : bilan {tuple(bilan)!r}, {attendu!r} attendu.")
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
    # La grandeur variabilite_journaliere (seed 0002) est conservée.
