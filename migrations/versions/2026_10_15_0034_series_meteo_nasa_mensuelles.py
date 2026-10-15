"""series_meteo_nasa_mensuelles

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-15

**Météo mensuelle NASA POWER aux 142 localités** (ADR-0019) : six grandeurs
météorologiques du référentiel (0002), aux 142 localités des séries mensuelles
(3 pilotes + 31 régions + 108 départements, ``points_nationaux``) :

| Grandeur | Paramètre NASA | Origine | Unité | Période | Mesures |
|---|---|---|---|---|---:|
| ``t2m`` | ``T2M`` | MERRA-2 | °C | 1991-2025 | 59 640 |
| ``rh2m`` | ``RH2M`` | MERRA-2 | % | 1991-2025 | 59 640 |
| ``vent_2m`` | ``WS2M`` | MERRA-2 | m/s | 1991-2025 | 59 640 |
| ``vent_10m`` | ``WS10M`` | MERRA-2 | m/s | 1991-2025 | 59 640 |
| ``precipitation`` | ``PRECTOTCORR`` | MERRA-2 | mm/jour | 1991-2025 | 59 640 |
| ``albedo_surface`` | ``ALLSKY_SRF_ALB`` | CERES SYN1deg | sans dimension | 2001-2025 | 42 600 |

Soit **852 séries** (``granularite='mensuel'``) et **340 800 mesures**, source
``nasa_power`` (id 1), méthode ``reanalyse`` (MERRA-2) ou ``modele_satellitaire``
(albédo), confiance **B**. Chaque valeur est la **moyenne des jours du mois**
telle que servie par NASA POWER (vérifié contre le journalier, ADR-0019) — pour
les précipitations, en mm/jour et non en cumul mensuel. Aucune conversion :
l'unité servie par NASA est l'unité de la grandeur au référentiel.

Valeurs lues hors-ligne dans les CSV gzip committés
(``seeds/donnees/nasa_power_<grandeur>_mensuel_civ142.csv.gz``, générés par
``scripts/ingest_nasa_power_meteo_mensuel.py``) et validées par
``series_csv.lire_series`` (complétude, bornes, doublons, localités), aux
contrats ``meteo_civ.CONTRATS_METEO_NASA_MENSUELS``. Insertion des
mesures par ``COPY`` (volume) ; le trigger d'audit par ligne s'applique.

Garde-fous : identité de la source ; unité de chaque grandeur au référentiel ;
142 localités présentes ; **aucune série préexistante** (codes, ni série NASA
mensuelle de ces grandeurs) ; 142 séries et nombre de mesures par grandeur ;
total. ``ANALYZE`` en fin de migration. ``downgrade`` supprime les mesures puis
les séries.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.meteo_civ import (
    CONTRATS_METEO_NASA_MENSUELS,
    LOT_METEO_MENSUEL,
    PARAMETRES_METEO_NASA,
    UNITES_REFERENTIEL,
)
from kuma_data_core.db.seeds.series_csv import ContratSerie, lire_series

# revision identifiers, used by Alembic.
revision: str = "0034"
down_revision: str | Sequence[str] | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NB_LOCALITES: int = 142
NB_MESURES_ATTENDU: int = 340_800  # 142 × (5 × 420 + 300)

SOURCE_ID: int = 1
SOURCE_CODE: str = "nasa_power"
DATE_EXTRACTION: str = "2026-10-15"

# Origine NASA POWER et maille de chaque méthode (pour la note publique).
_ORIGINE: dict[str, str] = {
    "reanalyse": "réanalyse MERRA-2, maille 0,5° × 0,625°",
    "modele_satellitaire": "CERES SYN1deg, maille 1°",
}
_UNITE: dict[str, str] = {
    "t2m": "en °C",
    "rh2m": "en %",
    "vent_2m": "en m/s",
    "vent_10m": "en m/s",
    "precipitation": "en mm/jour (pas un cumul mensuel)",
    "albedo_surface": "(grandeur sans dimension)",
}
# Mise en garde propre à la grandeur : elle voyage avec les données (ADR-0019).
_MISE_EN_GARDE: dict[str, str] = {
    "vent_2m": (
        " Sous couvert forestier, le vent à 2 m de MERRA-2 descend jusqu'à 12 % du vent "
        "à 10 m (Issia) : effet du couvert dans la réanalyse, pas une mesure."
    ),
    "precipitation": (
        " Réanalyse corrigée : quelques mois aberrants sont gravés tels que servis, sans "
        "correction — septembre 2022 dans l'ouest (jusqu'à 56,28 mm/jour à San-Pédro, "
        "contre 4,89 mm/jour dans ERA5 à San-Pédro), décembre 2025 à Ouangolodougou."
    ),
    "albedo_surface": (
        " Non servi avant 2001. Dans le pixel littoral de Sassandra et des régions de "
        "San-Pédro et du Gbôklé, l'albédo est bas (0,078 en moyenne, contre 0,148 sur les "
        "142 localités), vraisemblablement par la part d'océan dans le pixel de 1°."
    ),
}


def _note(grandeur: str, contrat: ContratSerie) -> str:
    return (
        f"{contrat.libelle_grandeur} — série mensuelle NASA POWER (paramètre "
        f"{PARAMETRES_METEO_NASA[grandeur][0]}, {_ORIGINE[contrat.methode_collecte]}), "
        f"moyenne des jours du mois {_UNITE[grandeur]}, "
        f"{contrat.annee_debut}-{contrat.annee_fin} (extraction du {DATE_EXTRACTION}). "
        f"Lot national « 142 localités » (ADR-0019). Confiance {contrat.niveau_confiance}."
        f"{_MISE_EN_GARDE.get(grandeur, '')}"
    )


def _codes_series() -> list[str]:
    codes = [code for code, _, _, _ in points_nationaux()]
    return [c.code_serie(code) for c in CONTRATS_METEO_NASA_MENSUELS.values() for code in codes]


def upgrade() -> None:
    bind = op.get_bind()

    # 0. Garde-fous : source, unités du référentiel, localités, absence de séries.
    code_source = bind.execute(
        sa.text("SELECT code FROM sources WHERE id = :i"), {"i": SOURCE_ID}
    ).scalar_one_or_none()
    if code_source != SOURCE_CODE:
        raise RuntimeError(
            f"Migration 0034 : source id {SOURCE_ID} = {code_source!r}, {SOURCE_CODE!r} attendue."
        )
    unites = {
        row.grandeur: row.unite
        for row in bind.execute(
            sa.text(
                "SELECT g.code AS grandeur, u.code AS unite FROM grandeurs_referentiel g "
                "JOIN unites u ON u.id = g.unite_id WHERE g.code = ANY(:g)"
            ),
            {"g": list(CONTRATS_METEO_NASA_MENSUELS)},
        ).all()
    }
    if unites != UNITES_REFERENTIEL:
        raise RuntimeError(
            f"Migration 0034 : unités du référentiel {unites!r}, {UNITES_REFERENTIEL!r} "
            "attendues (aucune conversion n'est faite)."
        )
    codes_loc = sorted(code for code, _, _, _ in points_nationaux())
    if len(codes_loc) != NB_LOCALITES:
        raise RuntimeError(
            f"Migration 0034 : {len(codes_loc)} localités, {NB_LOCALITES} attendues."
        )
    loc = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:c)"), {"c": codes_loc}
        ).all()
    }
    manquants = [c for c in codes_loc if c not in loc]
    if manquants:
        raise RuntimeError(f"Migration 0034 : localité(s) introuvable(s) : {manquants!r}.")
    existantes = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM series_metadonnees WHERE code = ANY(:c) "
            "OR (source_id = :s AND granularite = 'mensuel' AND grandeur_code = ANY(:g))"
        ),
        {"c": _codes_series(), "s": SOURCE_ID, "g": list(CONTRATS_METEO_NASA_MENSUELS)},
    ).scalar_one()
    if existantes:
        raise RuntimeError(f"Migration 0034 : {existantes} série(s) météo NASA déjà présente(s).")

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
    for grandeur, contrat in CONTRATS_METEO_NASA_MENSUELS.items():
        # 1. Lecture validée du CSV (complétude, bornes, doublons, localités).
        series = lire_series(contrat, LOT_METEO_MENSUEL)
        if [s["localite_code"] for s in series] != codes_loc:
            raise RuntimeError(
                f"Migration 0034 : {contrat.nom_fichier(LOT_METEO_MENSUEL)} ne couvre pas les "
                f"{NB_LOCALITES} localités."
            )

        # 2. Séries mensuelles.
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
        if len(serie_id) != NB_LOCALITES:
            raise RuntimeError(f"Migration 0034 : {grandeur} : {len(serie_id)} séries créées.")

        # 3. Mesures mensuelles, par COPY.
        with (
            connexion.cursor() as curseur,
            curseur.copy(
                "COPY mesures_ressource_mensuelles "
                "(serie_id, annee, mois, valeur, statut, niveau_confiance_derive) FROM STDIN"
            ) as copie,
        ):
            for s in series:
                sid = serie_id[s["code"]]
                for annee, mois, valeur in s["mesures"]:
                    copie.write_row((sid, annee, mois, valeur, "brut", contrat.niveau_confiance))

        nb = bind.execute(
            sa.text("SELECT COUNT(*) FROM mesures_ressource_mensuelles WHERE serie_id = ANY(:ids)"),
            {"ids": list(serie_id.values())},
        ).scalar_one()
        if nb != NB_LOCALITES * contrat.nb_mois:
            raise RuntimeError(
                f"Migration 0034 : {grandeur} : {nb} mesures, "
                f"{NB_LOCALITES * contrat.nb_mois} attendues."
            )
        total += nb

    if total != NB_MESURES_ATTENDU:
        raise RuntimeError(f"Migration 0034 : {total} mesures, {NB_MESURES_ATTENDU} attendues.")
    bind.execute(sa.text("ANALYZE mesures_ressource_mensuelles"))
    bind.execute(sa.text("ANALYZE series_metadonnees"))


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
            sa.text("DELETE FROM mesures_ressource_mensuelles WHERE serie_id = ANY(:ids)"),
            {"ids": ids},
        )
        bind.execute(sa.text("DELETE FROM series_metadonnees WHERE id = ANY(:ids)"), {"ids": ids})
    bind.execute(sa.text("ANALYZE mesures_ressource_mensuelles"))
    bind.execute(sa.text("ANALYZE series_metadonnees"))
