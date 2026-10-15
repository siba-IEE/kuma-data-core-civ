"""series_meteo_nasa_journalieres

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-15

**Météo journalière NASA POWER** (ADR-0020) : 6 grandeurs météorologiques
**journalières** aux **34 localités** du lot ``pilotes_regions`` (3 points
pilotes + 31 régions, ADR-0016), dans la table ``mesures_ressource`` (grain
journalier, ``instant_mesure`` = date). Contrats : ``seeds/meteo_civ.py``.

| Grandeur | Paramètre NASA | Produit | Méthode | Période | Jours par série | Mesures |
|---|---|---|---|---|---:|---:|
| ``t2m`` | ``T2M`` | MERRA-2 | ``reanalyse`` | 1991-2025 | 12 784 | 434 656 |
| ``rh2m`` | ``RH2M`` | MERRA-2 | ``reanalyse`` | 1991-2025 | 12 784 | 434 656 |
| ``vent_2m`` | ``WS2M`` | MERRA-2 | ``reanalyse`` | 1991-2025 | 12 784 | 434 656 |
| ``vent_10m`` | ``WS10M`` | MERRA-2 | ``reanalyse`` | 1991-2025 | 12 784 | 434 656 |
| ``precipitation`` | ``PRECTOTCORR`` | MERRA-2 | ``reanalyse`` | 1991-2025 | 12 784 | 434 656 |
| ``albedo_surface`` | ``ALLSKY_SRF_ALB`` | CERES SYN1deg | ``modele_satellitaire`` | 2001-2025 | 9 131 | 310 454 |

Soit **204 séries** (``granularite='journalier'``) et **2 483 734 mesures**,
confiance **B**, source ``nasa_power`` (id 1). Valeurs dans l'unité servie,
qui est celle de la grandeur au référentiel (°C, %, m/s, mm/jour, sans
dimension ; vérifié ici) : aucune conversion. Aucune valeur de remplissage dans
les périodes gravées (l'albédo est rempli avant 2001, d'où son contrat).

**Pluie** : NASA POWER sert des valeurs aberrantes probables (726,74 mm le
2022-09-16 à San-Pédro, 710,75 mm à Gbôklé), gravées telles quelles sous la
borne journalière de 1000 mm/jour du contrat. La note publique des 34 séries de
pluie porte une mise en garde (septembre 2022 dans l'ouest, 2025-12-02 au nord,
fortes pluies plus fréquentes depuis 2017 ; ADR-0020) : métadonnée seulement,
aucune valeur corrigée.

Valeurs lues hors-ligne dans les CSV gzip committés
(``seeds/donnees/nasa_power_<grandeur>_journalier_pilotes_regions.csv.gz``,
générés par ``scripts/ingest_nasa_power_meteo_journalier.py``) et validées par
``series_csv.lire_series_journalieres`` (tous les jours civils, bornes, doublons,
localités). Insertion par ``COPY`` (volume) ; le trigger d'audit par ligne
s'applique normalement. Garde-fous : identité de la source, unités du
référentiel, aucune série préexistante (code ou série journalière NASA de même
grandeur et localité, qui rendrait la résolution des compagnes ambiguë), 34
séries par grandeur, comptes par grandeur et total. ``ANALYZE`` en fin de
migration. ``downgrade`` supprime les mesures puis les séries.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.lots_civ import points_journalier
from kuma_data_core.db.seeds.meteo_civ import (
    CONTRATS_METEO_NASA_JOURNALIERS,
    LOT_METEO_JOURNALIER,
    PARAMETRES_METEO_NASA,
)
from kuma_data_core.db.seeds.series_csv import ContratSerie, lire_series_journalieres, nb_jours

# revision identifiers, used by Alembic.
revision: str = "0035"
down_revision: str | Sequence[str] | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_ID: int = 1
SOURCE_CODE: str = "nasa_power"
NB_POINTS: int = 34
NB_MESURES_ATTENDU: int = 2_483_734  # 34 × (5 × 12 784 + 9 131)

# Unité de chaque grandeur au référentiel = unité servie par NASA POWER.
UNITES: dict[str, tuple[str, str]] = {
    "t2m": ("degree_celsius", "°C"),
    "rh2m": ("pourcent", "%"),
    "vent_2m": ("metre_par_seconde", "m/s"),
    "vent_10m": ("metre_par_seconde", "m/s"),
    "precipitation": ("mm_par_jour", "mm/jour"),
    "albedo_surface": ("sans_unite", "sans dimension"),
}
# Produit NASA POWER et nature de la confiance B, par méthode de collecte.
PRODUITS: dict[str, tuple[str, str]] = {
    "reanalyse": ("réanalyse MERRA-2", "réanalyse"),
    "modele_satellitaire": ("CERES SYN1deg", "satellite"),
}
MISE_EN_GARDE_PLUIE: str = (
    " Mise en garde : valeurs aberrantes probables servies par NASA POWER, gravées "
    "sans correction. Les 5 seuls jours au-delà de 200 mm (1991-2025, 34 localités) "
    "tombent dans l'ouest en septembre 2022 (726,74 mm à San-Pédro et 710,75 mm à "
    "Gbôklé le 16 ; 329,59 mm au Guémon et au Cavally, 248,92 mm dans la Nawa le 23), "
    "septembre le plus pluvieux de 1991-2025 dans 23 des 34 localités ; le 2025-12-02, "
    "en saison sèche, 84,12 mm dans le Tchologo. Sur les 34 localités, les jours > 50 mm "
    "passent de 4,4 par an en 1991-2015 à 55,6 en 2017-2025. Fortes pluies à recouper "
    "avec ERA5 (ADR-0020)."
)


def _note(grandeur: str, contrat: ContratSerie) -> str:
    parametre, methode, _, libelle, _, _ = PARAMETRES_METEO_NASA[grandeur]
    produit, nature = PRODUITS[methode]
    note = (
        f"{libelle} journalier NASA POWER ({parametre}, {produit}), {UNITES[grandeur][1]}, "
        f"{contrat.annee_debut}-{contrat.annee_fin}, sans conversion. Lot national "
        "« pilotes + régions » (ADR-0020) ; la moyenne des jours du mois redonne la "
        f"série mensuelle NASA (à l'arrondi près). Confiance B ({nature})."
    )
    return note + MISE_EN_GARDE_PLUIE if grandeur == "precipitation" else note


def _codes_series() -> list[str]:
    codes = [code for code, _, _, _ in points_journalier()]
    return [c.code_serie(code) for c in CONTRATS_METEO_NASA_JOURNALIERS.values() for code in codes]


def upgrade() -> None:
    bind = op.get_bind()
    contrats = CONTRATS_METEO_NASA_JOURNALIERS

    # 0. Garde-fous : source, unités du référentiel, localités, séries préexistantes.
    code_source = bind.execute(
        sa.text("SELECT code FROM sources WHERE id = :i"), {"i": SOURCE_ID}
    ).scalar_one_or_none()
    if code_source != SOURCE_CODE:
        raise RuntimeError(
            f"Migration 0035 : source id {SOURCE_ID} = {code_source!r}, {SOURCE_CODE!r} attendue."
        )
    unites = {
        row.grandeur: row.unite
        for row in bind.execute(
            sa.text(
                "SELECT g.code AS grandeur, u.code AS unite FROM grandeurs_referentiel g "
                "JOIN unites u ON u.id = g.unite_id WHERE g.code = ANY(:g) AND g.actif"
            ),
            {"g": list(contrats)},
        ).all()
    }
    attendues = {g: u for g, (u, _) in UNITES.items()}
    if unites != attendues:
        raise RuntimeError(f"Migration 0035 : unités {unites!r}, {attendues!r} attendues.")
    codes_loc = sorted(code for code, _, _, _ in points_journalier())
    if len(codes_loc) != NB_POINTS:
        raise RuntimeError(f"Migration 0035 : {len(codes_loc)} localités, {NB_POINTS} attendues.")
    loc = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:c)"), {"c": codes_loc}
        ).all()
    }
    manquants = [c for c in codes_loc if c not in loc]
    if manquants:
        raise RuntimeError(f"Migration 0035 : localité(s) introuvable(s) : {manquants!r}.")
    preexistantes = bind.execute(
        sa.text(
            """
            SELECT code FROM series_metadonnees
            WHERE code = ANY(:codes)
               OR (source_id = :src AND granularite = 'journalier'
                   AND grandeur_code = ANY(:g) AND localite_id = ANY(:loc))
            """
        ),
        {
            "codes": _codes_series(),
            "src": SOURCE_ID,
            "g": list(contrats),
            "loc": list(loc.values()),
        },
    ).all()
    if preexistantes:
        raise RuntimeError(
            f"Migration 0035 : séries déjà présentes : {[r.code for r in preexistantes]!r}."
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
    for grandeur, contrat in contrats.items():
        series = lire_series_journalieres(contrat, LOT_METEO_JOURNALIER)
        if sorted(s["localite_code"] for s in series) != codes_loc:
            raise RuntimeError(
                f"Migration 0035 : {contrat.nom_fichier(LOT_METEO_JOURNALIER)} ne couvre pas le lot."
            )

        # 1. Séries journalières.
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
                    "note_publique": _note(grandeur, contrat),
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

        # 2. Mesures journalières, par COPY.
        with (
            connexion.cursor() as curseur,
            curseur.copy(
                "COPY mesures_ressource "
                "(serie_id, instant_mesure, valeur, statut, niveau_confiance_derive) "
                "FROM STDIN"
            ) as copie,
        ):
            for s in series:
                sid = serie_id[s["code"]]
                for jour, valeur in s["mesures"]:
                    copie.write_row((sid, jour, valeur, "brut", contrat.niveau_confiance))

        nb = bind.execute(
            sa.text("SELECT COUNT(*) FROM mesures_ressource WHERE serie_id = ANY(:ids)"),
            {"ids": list(serie_id.values())},
        ).scalar_one()
        if len(serie_id) != NB_POINTS or nb != NB_POINTS * nb_jours(contrat):
            raise RuntimeError(
                f"Migration 0035 : {grandeur} : {len(serie_id)} séries et {nb} mesures, "
                f"{NB_POINTS} et {NB_POINTS * nb_jours(contrat)} attendues."
            )
        total += nb

    if total != NB_MESURES_ATTENDU:
        raise RuntimeError(f"Migration 0035 : {total} mesures, {NB_MESURES_ATTENDU} attendues.")
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource"))


def downgrade() -> None:
    bind = op.get_bind()
    ids = [
        row.id
        for row in bind.execute(
            sa.text("SELECT id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": _codes_series()},
        ).all()
    ]
    if ids:
        bind.execute(
            sa.text("DELETE FROM mesures_ressource WHERE serie_id = ANY(:ids)"), {"ids": ids}
        )
        bind.execute(sa.text("DELETE FROM series_metadonnees WHERE id = ANY(:ids)"), {"ids": ids})
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource"))
