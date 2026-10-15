"""humidex_nasa

Revision ID: 0045
Revises: 0044
Create Date: 2026-10-15

Matérialise l'**humidex** (``humidex``, id 15, seedé en 0002, F1 ``stockee``,
``degree_celsius`` : °C apparents) aux **34 localités du journalier NASA POWER**
(3 pilotes + 31 régions, ADR-0016), depuis la **température** (``t2m``) et
l'**humidité relative** (``rh2m``) journalières NASA POWER (réanalyse MERRA-2,
migration 0035, ADR-0020) — ADR-0030.

Définition héritée, **version 1 inchangée** (fiche
``docs/methodologie/grandeurs/humidex.md`` et service
``services/grandeurs/humidex.py``), Masterton & Richardson (1979) avec les
constantes de Magnus de la fiche :

    e = (RH/100) · 6,112 · exp(17,67 · T / (T + 243,5))      (hPa)
    H = T + 5/9 · (e − 10)                                   (°C apparents)

calculé **jour par jour** (T et RH moyennes du jour), puis **moyenne
arithmétique** des humidex journaliers par mois et par année (l'annuel est la
moyenne des jours de l'année, pas celle des 12 mois). Complétude stricte de la
fiche, sur l'**intersection** T2M ∩ RH2M : un mois (une année) n'est gravé que
si tous ses jours civils ont les deux mesures. Mesures courantes seulement
(``valide_au IS NULL``, statut non ``deprecie``), comme le service. Seul
l'humidex moyen est stocké : le compteur de jours d'inconfort (H ≥ 40) n'a pas
d'entrée au référentiel (fiche § 4) ; ses valeurs sont dans l'ADR.

Grave, **par agrégation SQL hors-ligne** sur ``mesures_ressource`` (aucun seed,
aucun réseau) :

- 34 séries calculées ``humidex_nasa_power_<localité>`` (source
  ``kuma_calculs``, ``calcul_derive``) ;
- **14 280 lignes mensuelles** (420 mois 1991-2025 × 34) et **1 190 annuelles**
  (35 ans × 34), confiance **B**.

Humidex journalier et moyennes en ``numeric`` : ``exp`` et les quotients y sont
déterministes et la somme est exacte, donc indépendante de l'ordre
d'agrégation ; la moyenne est convertie en ``float8`` (reproductible au bit
près, ADR-0017). Mensuel et annuel sont produits en un seul passage
(``ROLLUP``).

La note publique porte la **mise en garde 2024-2025** : la hausse de l'humidex
NASA ces deux années vient de la T2M NASA, que ERA5 ne confirme pas (ADR-0021).

Garde-fous durs : grandeur conforme (id, famille, stratégie, version de
formule, unité), unités des entrées (°C, %), aucune série ni ligne ``humidex``
préexistante, exactement 34 séries T2M et 34 séries RH2M journalières NASA en
amont sur 1991-2025, 420 mois et 35 années par série, comptes totaux exacts,
toute valeur dans ``]10, 50[`` °C apparents (borne de sanité, pas valeur
attendue). ``ANALYZE grandeurs_metier`` en fin de migration. ``downgrade``
supprime les lignes puis les séries ; la grandeur (seed 0002) est conservée.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.lots_civ import points_journalier
from kuma_data_core.db.seeds.meteo_civ import CONTRATS_METEO_NASA_JOURNALIERS

# revision identifiers, used by Alembic.
revision: str = "0045"
down_revision: str | Sequence[str] | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANDEUR_CODE: str = "humidex"
GRANDEUR_ID: int = 15
VERSION_FORMULE: int = 1
UNITE: str = "degree_celsius"
SOURCE_CALCUL: str = "kuma_calculs"
ANNEE_DEBUT: int = 1991  # T2M et RH2M journaliers NASA (ADR-0020)
ANNEE_FIN: int = 2025
NB_POINTS: int = 34
NB_MOIS_PAR_SERIE: int = 420  # 35 ans × 12
NB_ANNEES_PAR_SERIE: int = 35
NB_MENSUEL_ATTENDU: int = 14_280  # 34 localités × 420 mois
NB_ANNUEL_ATTENDU: int = 1_190  # 34 localités × 35 ans
BORNE_MIN: float = 10.0  # °C apparents, garde-fou de sanité
BORNE_MAX: float = 50.0

# Entrées du calcul : grandeur -> unité attendue au référentiel (la formule
# suppose T en °C et RH en %).
ENTREES: dict[str, str] = {"t2m": "degree_celsius", "rh2m": "pourcent"}

MISE_EN_GARDE_2024: str = (
    " Mise en garde : l'humidex 2024-2025 dépasse de 0,81 °C la moyenne 2016-2023 "
    "(34 localités), sous l'effet de la T2M NASA (+0,87 °C), dont la hausse n'est pas "
    "confirmée par ERA5 (+0,21 °C contre +0,85 °C pour NASA sur 142 localités, "
    "ADR-0021) ; NASA POWER signale un changement de source de sa météo (MERRA-2, "
    "GEOS-IT). Aucune tendance à en tirer sans recoupement."
)


def code_serie(localite_code: str) -> str:
    """Code de la série calculée d'une localité."""
    return f"humidex_nasa_power_{localite_code}"


def _codes_series() -> list[str]:
    return [code_serie(code) for code, _, _, _ in points_journalier()]


def _note() -> str:
    return (
        "Humidex moyen NASA POWER, en °C apparents, mensuel et annuel "
        f"{ANNEE_DEBUT}-{ANNEE_FIN} : moyenne arithmétique des humidex journaliers "
        "(Masterton & Richardson 1979, constantes de Magnus 6,112 / 17,67 / 243,5), "
        "calculés depuis la température (T2M) et l'humidité relative (RH2M) moyennes "
        "du jour NASA POWER (réanalyse MERRA-2). Mois et année gravés seulement si "
        "tous leurs jours civils ont T2M et RH2M. Indice de la journée moyenne, pas "
        "du pic de l'après-midi. Confiance B (réanalyse). ADR-0030." + MISE_EN_GARDE_2024
    )


def upgrade() -> None:
    bind = op.get_bind()
    points = points_journalier()
    if len(points) != NB_POINTS:
        raise RuntimeError(f"Migration 0045 : {len(points)} localités, {NB_POINTS} attendues.")

    # 0. Garde-fous : grandeur conforme au seed 0002, entrées en °C et en %,
    #    rien de préexistant.
    row = bind.execute(
        sa.text(
            "SELECT g.id, g.famille, g.strategie_calcul, g.version_formule_actuelle, "
            "u.code AS unite FROM grandeurs_referentiel g JOIN unites u ON u.id = g.unite_id "
            "WHERE g.code = :c"
        ),
        {"c": GRANDEUR_CODE},
    ).one_or_none()
    if row is None or tuple(row) != (GRANDEUR_ID, "F1", "stockee", VERSION_FORMULE, UNITE):
        raise RuntimeError(f"Migration 0045 : grandeur {GRANDEUR_CODE!r} hors contrat : {row!r}.")
    unites = {
        r.grandeur: r.unite
        for r in bind.execute(
            sa.text(
                "SELECT g.code AS grandeur, u.code AS unite FROM grandeurs_referentiel g "
                "JOIN unites u ON u.id = g.unite_id WHERE g.code = ANY(:g)"
            ),
            {"g": list(ENTREES)},
        ).all()
    }
    if unites != ENTREES:
        raise RuntimeError(
            f"Migration 0045 : unités des entrées {unites!r}, {ENTREES!r} attendues."
        )
    preexistantes = bind.execute(
        sa.text(
            "SELECT (SELECT COUNT(*) FROM series_metadonnees WHERE grandeur_code = :c) "
            "+ (SELECT COUNT(*) FROM grandeurs_metier WHERE grandeur_code = :c)"
        ),
        {"c": GRANDEUR_CODE},
    ).scalar_one()
    if preexistantes:
        raise RuntimeError(f"Migration 0045 : {GRANDEUR_CODE!r} déjà présente.")

    # 1. Séries T2M et RH2M journalières NASA en amont : une par localité et par
    #    grandeur, période 1991-2025.
    amont = {
        grandeur: [
            CONTRATS_METEO_NASA_JOURNALIERS[grandeur].code_serie(code) for code, _, _, _ in points
        ]
        for grandeur in ENTREES
    }
    for grandeur, codes_amont in amont.items():
        conformes = bind.execute(
            sa.text(
                """
                SELECT COUNT(*) AS n,
                       COUNT(*) FILTER (
                           WHERE s.granularite = 'journalier' AND s.grandeur_code = :g
                             AND src.code = 'nasa_power'
                             AND s.periode_debut = :debut AND s.periode_fin = :fin
                       ) AS conformes
                FROM series_metadonnees s JOIN sources src ON src.id = s.source_id
                WHERE s.code = ANY(:c)
                """
            ),
            {
                "g": grandeur,
                "c": codes_amont,
                "debut": f"{ANNEE_DEBUT}-01-01",
                "fin": f"{ANNEE_FIN}-12-31",
            },
        ).one()
        if (conformes.n, conformes.conformes) != (NB_POINTS, NB_POINTS):
            raise RuntimeError(
                f"Migration 0045 : séries {grandeur} journalières amont {tuple(conformes)!r}."
            )

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
        raise RuntimeError(f"Migration 0045 : localité(s) introuvable(s) : {manquants!r}.")
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
                "libelle": f"Humidex moyen NASA POWER — {nom} ({ANNEE_DEBUT}-{ANNEE_FIN})",
                "localite_id": loc[code],
                "grandeur_code": GRANDEUR_CODE,
                "source_id": source_calcul_id,
                "periode_debut": f"{ANNEE_DEBUT}-01-01",
                "periode_fin": f"{ANNEE_FIN}-12-31",
                "methode_collecte": "calcul_derive",
                "granularite": None,
                "note_publique": _note(),
            }
            for code, nom, _, _ in points
        ],
    )

    # 3. Lignes mensuelles et annuelles : moyenne des humidex journaliers, périodes
    #    complètes sur l'intersection T2M ∩ RH2M. ROLLUP (mois) produit le groupe
    #    (année, mois) et le groupe (année) ; GROUPING(mois) = 1 sur ce dernier.
    bind.execute(
        sa.text(
            """
            WITH jours AS (
                SELECT sh.id AS serie_cible, sh.localite_id,
                       EXTRACT(YEAR FROM mt.instant_mesure)::int AS annee,
                       EXTRACT(MONTH FROM mt.instant_mesure)::int AS mois,
                       mt.valeur::numeric AS t, mr.valeur::numeric AS rh
                FROM series_metadonnees sh
                JOIN series_metadonnees st
                    ON st.localite_id = sh.localite_id AND st.grandeur_code = 't2m'
                   AND st.granularite = 'journalier' AND st.code = ANY(:amont_t2m)
                JOIN mesures_ressource mt
                    ON mt.serie_id = st.id AND mt.valide_au IS NULL AND mt.statut <> 'deprecie'
                JOIN series_metadonnees sr
                    ON sr.localite_id = sh.localite_id AND sr.grandeur_code = 'rh2m'
                   AND sr.granularite = 'journalier' AND sr.code = ANY(:amont_rh2m)
                JOIN mesures_ressource mr
                    ON mr.serie_id = sr.id AND mr.instant_mesure = mt.instant_mesure
                   AND mr.valide_au IS NULL AND mr.statut <> 'deprecie'
                WHERE sh.code = ANY(:codes)
            ),
            humidex AS (
                -- Masterton & Richardson (1979), constantes de Magnus de la fiche :
                -- e = (RH/100)·6,112·exp(17,67·T / (T + 243,5)) ; H = T + 5/9·(e − 10).
                SELECT serie_cible, localite_id, annee, mois,
                       t + (rh / 100 * 6.112 * exp(17.67 * t / (t + 243.5)) - 10) * 5 / 9 AS h
                FROM jours
            )
            INSERT INTO grandeurs_metier (
                grandeur_code, localite_id, series_metadonnees_id, periode_type,
                annee_debut, annee_fin, mois, version_formule, valeur,
                niveau_confiance_derive
            )
            SELECT :g, localite_id, serie_cible,
                   CASE WHEN GROUPING(mois) = 0 THEN 'mensuel' ELSE 'annuel' END,
                   annee, annee, mois, :v,
                   -- numeric : somme exacte, donc indépendante de l'ordre
                   -- d'agrégation (résultat reproductible au bit près).
                   avg(h)::float8, 'B'
            FROM humidex
            GROUP BY localite_id, serie_cible, annee, ROLLUP (mois)
            HAVING COUNT(*) = CASE
                WHEN GROUPING(mois) = 0
                    THEN (make_date(annee, mois, 1) + INTERVAL '1 month')::date
                         - make_date(annee, mois, 1)
                ELSE make_date(annee + 1, 1, 1) - make_date(annee, 1, 1)
            END
            """
        ),
        {
            "g": GRANDEUR_CODE,
            "v": VERSION_FORMULE,
            "codes": _codes_series(),
            "amont_t2m": amont["t2m"],
            "amont_rh2m": amont["rh2m"],
        },
    )

    # 4. Garde-fous durs : comptes, couverture par série, domaine de sanité.
    bilan = bind.execute(
        sa.text(
            """
            WITH par_serie AS (
                SELECT series_metadonnees_id,
                       COUNT(*) FILTER (WHERE periode_type = 'mensuel') AS mensuel,
                       COUNT(*) FILTER (WHERE periode_type = 'annuel') AS annuel
                FROM grandeurs_metier WHERE grandeur_code = :g
                GROUP BY series_metadonnees_id
            )
            SELECT (SELECT COUNT(*) FROM grandeurs_metier
                    WHERE grandeur_code = :g AND periode_type = 'mensuel') AS mensuel,
                   (SELECT COUNT(*) FROM grandeurs_metier
                    WHERE grandeur_code = :g AND periode_type = 'annuel') AS annuel,
                   (SELECT COUNT(*) FROM par_serie
                    WHERE mensuel = :nb_mois AND annuel = :nb_annees) AS series_completes,
                   (SELECT MIN(annee_debut) FROM grandeurs_metier WHERE grandeur_code = :g)
                       AS debut,
                   (SELECT MAX(annee_debut) FROM grandeurs_metier WHERE grandeur_code = :g)
                       AS fin,
                   (SELECT COUNT(*) FROM grandeurs_metier
                    WHERE grandeur_code = :g
                      AND NOT (valeur > :bmin AND valeur < :bmax)) AS hors_domaine
            """
        ),
        {
            "g": GRANDEUR_CODE,
            "nb_mois": NB_MOIS_PAR_SERIE,
            "nb_annees": NB_ANNEES_PAR_SERIE,
            "bmin": BORNE_MIN,
            "bmax": BORNE_MAX,
        },
    ).one()
    attendu = (NB_MENSUEL_ATTENDU, NB_ANNUEL_ATTENDU, NB_POINTS, ANNEE_DEBUT, ANNEE_FIN, 0)
    if tuple(bilan) != attendu:
        raise RuntimeError(f"Migration 0045 : bilan {tuple(bilan)!r}, {attendu!r} attendu.")
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
    # La grandeur humidex (seed 0002) est conservée.
