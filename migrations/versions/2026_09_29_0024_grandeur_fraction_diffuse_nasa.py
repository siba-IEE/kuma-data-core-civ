"""grandeur_fraction_diffuse_nasa

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-29

Matérialise la grandeur **``fraction_diffuse``** (id 3, seedée en 0002, F1
``stockee``, unité ``sans_unite``) aux 3 points, depuis le **DHI** (0021) et le
**GHI** (0008) **NASA POWER**, source amont fixée par la fiche
``docs/methodologie/grandeurs/fraction_diffuse.md`` (ADR-0014).

Formule de la fiche, **version 1 inchangée** :

    fraction_diffuse(annee, mois) := Σ DHI(t) / Σ GHI(t), t ∈ jours(annee, mois)
    fraction_diffuse(annee)       := Σ DHI(t) / Σ GHI(t), t ∈ jours(annee)

L'instance ne porte que le **mensuel** NASA (moyenne journalière du mois). Sur
les jours d'un mois, ``Σ DHI / Σ GHI = moy(DHI) / moy(GHI)`` ; sur une année,
``Σ_m DHI_m·n_m / Σ_m GHI_m·n_m`` (``n_m`` = jours du mois). Équivalence
vérifiée contre le NASA POWER **journalier** (Abidjan, 2005) : écart ≤ 4·10⁻⁵
(arrondi des seeds à 4 décimales), cf. ADR-0014.

Grave, **par jointure SQL hors-ligne** (aucun seed, aucun réseau) :

- 3 séries calculées (source ``kuma_calculs``, ``calcul_derive``) ;
- **720 lignes mensuelles** (240 mois 2001-2020 × 3) et **60 lignes
  annuelles** (20 ans × 3), confiance dérivée **B**. La fenêtre suit le DHI
  NASA (2001-2020, 0021) : la jointure avec le GHI 1991-2020 ne garde que
  l'intersection. Une année n'est gravée que
  si ses 12 mois existent sur les deux séries (complétude stricte de la fiche,
  au grain mensuel).

Garde-fous durs : ``COUNT`` mensuel = 720, annuel = 60, et toute valeur dans
``[0, 1]`` — c'est ce garde-fou qui a révélé la rupture du DHI NASA avant 2001
(valeurs > 1). ``downgrade`` supprime les lignes et les séries ; la grandeur
(seed 0002) est conservée.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANDEUR_CODE: str = "fraction_diffuse"
GRANDEUR_ID: int = 3
SOURCE_CALCUL: str = "kuma_calculs"
SOURCE_AMONT: str = "nasa_power"
PERIODE_DEBUT: str = "2001-01-01"
PERIODE_FIN: str = "2020-12-31"
NB_MENSUEL_ATTENDU: int = 720  # 240 mois (2001-2020) × 3 localités
NB_ANNUEL_ATTENDU: int = 60  # 20 ans × 3 localités

# (code localité, nom d'affichage) — les 3 points déjà gravés (0008/0021).
_POINTS: tuple[tuple[str, str], ...] = (
    ("civ_dep_abidjan", "Abidjan"),
    ("civ_dep_yamoussoukro", "Yamoussoukro"),
    ("civ_dep_korhogo", "Korhogo"),
)

_CODES_SERIES: tuple[str, ...] = tuple(f"fraction_diffuse_nasa_power_{code}" for code, _ in _POINTS)

# Couples (DHI, GHI) NASA POWER par (localité, année, mois), avec le nombre de
# jours du mois. La jointure ne garde que les mois présents dans les deux séries.
_CTE_COUPLES: str = """
    WITH couples AS (
        SELECT
            sd.localite_id,
            md.annee,
            md.mois,
            md.valeur AS dhi,
            mg.valeur AS ghi,
            EXTRACT(
                DAY FROM (make_date(md.annee, md.mois, 1) + INTERVAL '1 month - 1 day')
            )::int AS n_jours
        FROM mesures_ressource_mensuelles md
        JOIN series_metadonnees sd
            ON sd.id = md.serie_id AND sd.grandeur_code = 'dhi'
        JOIN sources src_d
            ON src_d.id = sd.source_id AND src_d.code = :src_amont
        JOIN series_metadonnees sg
            ON sg.grandeur_code = 'ghi' AND sg.localite_id = sd.localite_id
        JOIN sources src_g
            ON src_g.id = sg.source_id AND src_g.code = :src_amont
        JOIN mesures_ressource_mensuelles mg
            ON mg.serie_id = sg.id AND mg.annee = md.annee AND mg.mois = md.mois
    )
"""


def upgrade() -> None:
    bind = op.get_bind()

    # 0. Garde-fou : la grandeur seedée en 0002 est bien celle attendue.
    row = bind.execute(
        sa.text("SELECT id, strategie_calcul FROM grandeurs_referentiel WHERE code = :c"),
        {"c": GRANDEUR_CODE},
    ).one_or_none()
    if row is None or row.id != GRANDEUR_ID or row.strategie_calcul != "stockee":
        raise RuntimeError(f"Migration 0024 : grandeur {GRANDEUR_CODE!r} hors contrat : {row!r}.")

    # 1. Séries calculées (une par localité), source éditoriale kuma_calculs.
    source_calcul_id = bind.execute(
        sa.text("SELECT id FROM sources WHERE code = :c"), {"c": SOURCE_CALCUL}
    ).scalar_one()
    loc = {
        r.code: r.id
        for r in bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:c)"),
            {"c": [code for code, _ in _POINTS]},
        ).all()
    }
    manquants = [code for code, _ in _POINTS if code not in loc]
    if manquants:
        raise RuntimeError(f"Migration 0024 : localité(s) introuvable(s) : {manquants!r}.")

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
                "code": f"fraction_diffuse_nasa_power_{code}",
                "libelle": f"Fraction diffuse NASA POWER — {nom} (2001-2020)",
                "localite_id": loc[code],
                "grandeur_code": GRANDEUR_CODE,
                "source_id": source_calcul_id,
                "periode_debut": PERIODE_DEBUT,
                "periode_fin": PERIODE_FIN,
                "methode_collecte": "calcul_derive",
                "granularite": None,
                "note_publique": (
                    "Fraction diffuse DHI/GHI NASA POWER (Σ DHI / Σ GHI sur les jours de la "
                    "période), sans dimension, mensuelle et annuelle 2001-2020. Calculée depuis "
                    "les moyennes journalières mensuelles NASA (équivalent exact au calcul "
                    "journalier, vérifié à 4·10⁻⁵ près). Confiance B (deux entrées satellite B)."
                ),
            }
            for (code, nom) in _POINTS
        ],
    )

    # 2. Lignes mensuelles : moy(DHI) / moy(GHI) = Σ DHI / Σ GHI sur les jours du mois.
    params = {"grandeur_code": GRANDEUR_CODE, "src_amont": SOURCE_AMONT}
    bind.execute(
        sa.text(
            _CTE_COUPLES
            + """
            INSERT INTO grandeurs_metier (
                grandeur_code, localite_id, series_metadonnees_id, periode_type,
                annee_debut, annee_fin, mois, version_formule, valeur,
                niveau_confiance_derive
            )
            SELECT :grandeur_code, c.localite_id, sf.id, 'mensuel',
                   c.annee, c.annee, c.mois, 1, c.dhi / c.ghi, 'B'
            FROM couples c
            JOIN series_metadonnees sf
                ON sf.grandeur_code = :grandeur_code AND sf.localite_id = c.localite_id
            WHERE c.ghi > 0
            """
        ),
        params,
    )

    # 3. Lignes annuelles : Σ_m DHI_m·n_m / Σ_m GHI_m·n_m, années complètes seulement.
    bind.execute(
        sa.text(
            _CTE_COUPLES
            + """
            INSERT INTO grandeurs_metier (
                grandeur_code, localite_id, series_metadonnees_id, periode_type,
                annee_debut, annee_fin, mois, version_formule, valeur,
                niveau_confiance_derive
            )
            SELECT :grandeur_code, c.localite_id, sf.id, 'annuel',
                   c.annee, c.annee, NULL, 1,
                   SUM(c.dhi * c.n_jours) / SUM(c.ghi * c.n_jours), 'B'
            FROM couples c
            JOIN series_metadonnees sf
                ON sf.grandeur_code = :grandeur_code AND sf.localite_id = c.localite_id
            GROUP BY c.localite_id, sf.id, c.annee
            HAVING COUNT(*) = 12 AND SUM(c.ghi * c.n_jours) > 0
            """
        ),
        params,
    )

    # 4. Garde-fous durs : complétude et domaine physique [0, 1].
    comptes = dict(
        bind.execute(
            sa.text(
                "SELECT periode_type, COUNT(*) FROM grandeurs_metier "
                "WHERE grandeur_code = :c GROUP BY periode_type"
            ),
            {"c": GRANDEUR_CODE},
        ).all()
    )
    attendu = {"mensuel": NB_MENSUEL_ATTENDU, "annuel": NB_ANNUEL_ATTENDU}
    if comptes != attendu:
        raise RuntimeError(f"Migration 0024 : lignes {comptes!r}, {attendu!r} attendues.")
    hors_domaine = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM grandeurs_metier "
            "WHERE grandeur_code = :c AND (valeur < 0 OR valeur > 1)"
        ),
        {"c": GRANDEUR_CODE},
    ).scalar_one()
    if hors_domaine:
        raise RuntimeError(f"Migration 0024 : {hors_domaine} valeur(s) hors de [0, 1].")


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
    # La grandeur fraction_diffuse (seed 0002) est conservée.
