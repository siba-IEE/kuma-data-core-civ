"""rayonnement_journalier_departements

Revision ID: 0046
Revises: 0045
Create Date: 2026-10-15

**Rayonnement journalier NASA POWER aux 108 départements** hors pilotes (lot
``departements``, ADR-0031) : GHI, DNI et DHI **journaliers**, mêmes contrats
que le lot « pilotes + régions » (ADR-0016, prolongé en 2025 par l'ADR-0018),
gravés ici d'un seul tenant. Avec les 34 localités déjà gravées (0026, 0031),
les 111 départements et les 31 régions ont un rayonnement journalier.

| Grandeur | Paramètre NASA | Période | Jours par série | Mesures |
|---|---|---|---:|---:|
| GHI | ``ALLSKY_SFC_SW_DWN`` | 1991-2025 | 12 784 | 1 380 672 |
| DNI | ``ALLSKY_SFC_SW_DNI`` | 2001-2025 | 9 131 | 986 148 |
| DHI | ``ALLSKY_SFC_SW_DIFF`` | 2001-2025 | 9 131 | 986 148 |

Soit **324 séries** ``nasa_power_<grandeur>_journalier_<localité>``
(``granularite='journalier'``) et **3 352 968 mesures**, méthode
``modele_satellitaire``, confiance **B**, source ``nasa_power`` (id 1). DNI non
servi et DHI en rupture avant 2001 (ADR-0013). Valeurs en kWh/m²/jour, unité
servie et unité de la grandeur au référentiel : aucune conversion. Aucune valeur
de remplissage dans les périodes gravées.

Valeurs lues hors-ligne dans les CSV gzip committés
(``seeds/donnees/nasa_power_<grandeur>_journalier_departements.csv.gz``, générés
par ``scripts/ingest_nasa_power_journalier.py --departements``) et validées par
``series_csv.lire_series_journalieres`` (tous les jours civils, bornes, doublons,
localités). Mesures insérées par ``COPY`` avec l'**audit par série**
(``seeds/audit_par_serie.py``) : trigger d'audit ligne à ligne de
``mesures_ressource`` suspendu le temps du ``COPY``, puis une entrée
``audit_log`` par série (code, nombre de mesures, bornes, CSV et son empreinte
SHA-256). Les 324 séries (``series_metadonnees``) gardent l'audit ligne à ligne.

Garde-fous : identité de la source, unité du référentiel, 108 localités,
**aucune série préexistante** (même code, ou série journalière NASA de même
grandeur et localité, qui rendrait ambiguë la résolution des compagnes), 108
séries et nombre de mesures par grandeur, totaux. ``ANALYZE`` en fin de
migration. ``downgrade`` écrit l'audit par série des suppressions, puis
supprime les mesures (audit ligne suspendu) et les séries.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.audit_par_serie import (
    audit_ligne_suspendu,
    auditer_series,
    empreinte_fichier,
)
from kuma_data_core.db.seeds.journalier_departements_civ import (
    CONTRATS_RAYONNEMENT_DEPARTEMENTS,
    LOT_JOURNALIER_DEPARTEMENTS,
    NB_DEPARTEMENTS,
    points_journalier_departements,
)
from kuma_data_core.db.seeds.lots_civ import PARAMETRES_NASA
from kuma_data_core.db.seeds.series_csv import ContratSerie, lire_series_journalieres, nb_jours

# revision identifiers, used by Alembic.
revision: str = "0046"
down_revision: str | Sequence[str] | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_ID: int = 1
SOURCE_CODE: str = "nasa_power"
UNITE: str = "kwh_par_m2_jour"
NB_POINTS: int = NB_DEPARTEMENTS  # 108
NB_SERIES_ATTENDU: int = 324  # 3 grandeurs × 108 départements
NB_MESURES_ATTENDU: int = 3_352_968  # 108 × (12 784 + 9 131 + 9 131)


def _note(grandeur: str, contrat: ContratSerie) -> str:
    return (
        f"{grandeur.upper()} journalier NASA POWER ({PARAMETRES_NASA[grandeur]}), "
        f"kWh/m²/jour, {contrat.annee_debut}-{contrat.annee_fin}. Lot national "
        "« départements » (108 départements hors pilotes, ADR-0031), même contrat que le "
        "lot « pilotes + régions » (ADR-0016) ; la moyenne mensuelle des jours redonne la "
        "série mensuelle NASA. Confiance B (satellite)."
    )


def _codes_series() -> list[str]:
    codes = [code for code, _, _, _ in points_journalier_departements()]
    return [
        c.code_serie(code) for c in CONTRATS_RAYONNEMENT_DEPARTEMENTS.values() for code in codes
    ]


def _fichiers_audit() -> dict[str, tuple[str, str]]:
    """Code de série → (CSV gzip, empreinte SHA-256), pour l'audit par série."""
    codes = [code for code, _, _, _ in points_journalier_departements()]
    fichiers: dict[str, tuple[str, str]] = {}
    for contrat in CONTRATS_RAYONNEMENT_DEPARTEMENTS.values():
        nom = contrat.nom_fichier(LOT_JOURNALIER_DEPARTEMENTS)
        empreinte = empreinte_fichier(contrat, LOT_JOURNALIER_DEPARTEMENTS)
        fichiers.update({contrat.code_serie(code): (nom, empreinte) for code in codes})
    return fichiers


def upgrade() -> None:
    bind = op.get_bind()
    contrats = CONTRATS_RAYONNEMENT_DEPARTEMENTS

    # 0. Garde-fous : source, unité du référentiel, localités, séries préexistantes.
    code_source = bind.execute(
        sa.text("SELECT code FROM sources WHERE id = :i"), {"i": SOURCE_ID}
    ).scalar_one_or_none()
    if code_source != SOURCE_CODE:
        raise RuntimeError(
            f"Migration 0046 : source id {SOURCE_ID} = {code_source!r}, {SOURCE_CODE!r} attendue."
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
    if unites != dict.fromkeys(contrats, UNITE):
        raise RuntimeError(f"Migration 0046 : unités {unites!r}, {UNITE!r} attendue partout.")
    codes_loc = sorted(code for code, _, _, _ in points_journalier_departements())
    if len(codes_loc) != NB_POINTS:
        raise RuntimeError(f"Migration 0046 : {len(codes_loc)} localités, {NB_POINTS} attendues.")
    loc = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:c)"), {"c": codes_loc}
        ).all()
    }
    manquants = [c for c in codes_loc if c not in loc]
    if manquants:
        raise RuntimeError(f"Migration 0046 : localité(s) introuvable(s) : {manquants!r}.")
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
            f"Migration 0046 : séries déjà présentes : {[r.code for r in preexistantes]!r}."
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
    nb_series = 0
    total = 0
    for grandeur, contrat in contrats.items():
        series = lire_series_journalieres(contrat, LOT_JOURNALIER_DEPARTEMENTS)
        if sorted(s["localite_code"] for s in series) != codes_loc:
            raise RuntimeError(
                f"Migration 0046 : {contrat.nom_fichier(LOT_JOURNALIER_DEPARTEMENTS)} "
                "ne couvre pas le lot."
            )

        # 1. Séries journalières (audit ligne à ligne).
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

        # 2. Mesures journalières, par COPY, audit ligne à ligne suspendu.
        with (
            audit_ligne_suspendu(bind),
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
        del series

        nb = bind.execute(
            sa.text("SELECT COUNT(*) FROM mesures_ressource WHERE serie_id = ANY(:ids)"),
            {"ids": list(serie_id.values())},
        ).scalar_one()
        if len(serie_id) != NB_POINTS or nb != NB_POINTS * nb_jours(contrat):
            raise RuntimeError(
                f"Migration 0046 : {grandeur} : {len(serie_id)} séries et {nb} mesures, "
                f"{NB_POINTS} et {NB_POINTS * nb_jours(contrat)} attendues."
            )
        nb_series += len(serie_id)
        total += nb

    if nb_series != NB_SERIES_ATTENDU or total != NB_MESURES_ATTENDU:
        raise RuntimeError(
            f"Migration 0046 : {nb_series} séries et {total} mesures, "
            f"{NB_SERIES_ATTENDU} et {NB_MESURES_ATTENDU} attendues."
        )

    # 3. Audit par série des insertions.
    auditer_series(bind, "I", revision, _fichiers_audit())

    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource"))


def downgrade() -> None:
    bind = op.get_bind()
    series = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": _codes_series()},
        ).all()
    }
    ids = list(series.values())
    if ids:
        # Audit par série des suppressions, lu en base avant de supprimer.
        auditer_series(
            bind, "D", revision, {c: f for c, f in _fichiers_audit().items() if c in series}
        )
        with audit_ligne_suspendu(bind):
            bind.execute(
                sa.text("DELETE FROM mesures_ressource WHERE serie_id = ANY(:ids)"), {"ids": ids}
            )
        bind.execute(sa.text("DELETE FROM series_metadonnees WHERE id = ANY(:ids)"), {"ids": ids})
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource"))
