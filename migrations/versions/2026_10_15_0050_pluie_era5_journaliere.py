"""pluie_era5_journaliere

Revision ID: 0050
Revises: 0049
Create Date: 2026-10-15

**Pluie journalière ERA5 (CDS Copernicus) aux 142 localités** : deuxième source
journalière de la pluie, à côté de NASA POWER (``PRECTOTCORR``, MERRA-2, 0035 et
0047), pour recouper jour par jour ses fortes pluies douteuses (jours au-delà
de 200 mm, rupture vers 2017 : ADR-0020, ADR-0031). La pluie mensuelle ERA5 est
gravée depuis 0036 (ADR-0021).

| Grandeur | Données CDS | Cumul du jour | Conversion | Période | Jours par série | Mesures |
|---|---|---|---|---|---:|---:|
| ``precipitation`` | cumuls horaires ``total_precipitation`` | heures datées 01 h (J) → 00 h (J + 1) | m × 1000 → mm/jour | 1991-2025 | 12 784 | 1 815 328 |

Soit **142 séries** ``ecmwf_era5_precipitation_journalier_<localité>``
(``granularite='journalier'``, table ``mesures_ressource``), source
``ecmwf_era5`` (id 2), méthode ``reanalyse``, confiance **B**. Contrat :
``pluie_era5_journaliere_civ.CONTRAT_PLUIE_ERA5_JOURNALIERE``. Cumuls horaires
ERA5 (jeu ``reanalysis-era5-single-levels``, lus nœud par nœud dans
``reanalysis-era5-single-levels-timeseries``, identiques à l'octet près) sommés
sur le jour civil UTC, qui est le jour civil local (UTC+0) : un cumul daté HH
couvre l'heure qui finit à HH. Valeur au point de grille 0,25° le plus proche,
**même maille que le mensuel 0036** (110 mailles pour 142 localités). Aucune
nouvelle source, grandeur, unité ni valeur d'énumération.

La moyenne des jours du mois redonne le mensuel 0036 à 0,0036 mm/jour près,
sauf dans 13 mois de raccord entre expériences de production ERA5 (1993-08 à
2019-03, ``MOIS_TRANSITION_ERA5``) où le mensuel du CDS s'écarte de la somme
des cumuls horaires, jusqu'à 0,39 mm/jour : incohérence de la source, non
corrigée, citée par la note publique.

Valeurs lues hors-ligne dans le CSV gzip committé
(``seeds/donnees/ecmwf_era5_precipitation_journalier_civ142.csv.gz``, généré par
``scripts/ingest_era5_cds_journalier.py``) et validées par
``series_csv.lire_series_journalieres`` (tous les jours civils, bornes, doublons,
localités). Insertion par ``COPY`` avec l'**audit par série**
(``audit_par_serie``, ADR-0031) : audit ligne à ligne de ``mesures_ressource``
suspendu le temps de l'insertion, puis une entrée d'audit par série (code,
nombre de mesures, bornes, fichier et empreinte SHA-256, révision) ; les séries
elles-mêmes (``series_metadonnees``) gardent l'audit ligne à ligne.

Garde-fous : identité de la source, unité ``mm_par_jour`` de la grandeur au
référentiel, 142 localités, **aucune série journalière ERA5 préexistante** (ni
ces codes, ni série journalière de pluie ``ecmwf_era5``), couverture exacte du
CSV, 142 séries et 1 815 328 mesures. ``ANALYZE`` en fin de migration.
``downgrade`` écrit l'audit par série de la suppression, puis supprime les
mesures (audit ligne à ligne suspendu) et les séries.
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
from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.pluie_era5_journaliere_civ import (
    CONTRAT_PLUIE_ERA5_JOURNALIERE,
    LOT_PLUIE_ERA5_JOURNALIERE,
    UNITE_REFERENTIEL,
)
from kuma_data_core.db.seeds.series_csv import lire_series_journalieres, nb_jours

# revision identifiers, used by Alembic.
revision: str = "0050"
down_revision: str | Sequence[str] | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVISION: str = "0050"
NB_POINTS: int = 142
NB_JOURS: int = 12_784  # 1991-01-01 → 2025-12-31
NB_MESURES_ATTENDU: int = 1_815_328  # 142 × 12 784

NOTE: str = (
    "Précipitations journalières ERA5 (réanalyse ECMWF, Copernicus C3S ; cumuls "
    "horaires du CDS, jeu reanalysis-era5-single-levels) : cumul du jour civil UTC, "
    "somme des cumuls horaires datés de 01 h le jour même à 00 h le lendemain, en "
    "mm/jour (converti des mètres d'eau) ; la Côte d'Ivoire est en UTC+0. Point de "
    "grille 0,25° le plus proche, 1991-2025, même maille que la série mensuelle ERA5 "
    "(0036) : la moyenne des jours du mois la redonne à 0,004 mm/jour près, sauf dans "
    "13 mois de raccord entre expériences de production ERA5 (de 1993-08 à 2019-03) "
    "où le mensuel du CDS s'écarte de la somme des cumuls horaires, jusqu'à "
    "0,39 mm/jour (incohérence de la source, non corrigée). Confiance B (réanalyse). "
    "Deuxième source journalière de la pluie, à côté de NASA POWER (réanalyse "
    "MERRA-2), pour en recouper les fortes pluies ; jamais une mesure au sol "
    "(ADR-0021, ADR-0032). Attribution : contient des informations modifiées du "
    "Copernicus Climate Change Service (2026)."
)


def _codes_localites() -> list[str]:
    return sorted(code for code, _, _, _ in points_nationaux())


def _fichiers() -> dict[str, tuple[str, str]]:
    """Code de série → (CSV, empreinte SHA-256), pour l'audit par série."""
    contrat, lot = CONTRAT_PLUIE_ERA5_JOURNALIERE, LOT_PLUIE_ERA5_JOURNALIERE
    fichier = (contrat.nom_fichier(lot), empreinte_fichier(contrat, lot))
    return {contrat.code_serie(code): fichier for code in _codes_localites()}


def upgrade() -> None:
    bind = op.get_bind()
    contrat, lot = CONTRAT_PLUIE_ERA5_JOURNALIERE, LOT_PLUIE_ERA5_JOURNALIERE

    # 0. Garde-fous : source, unité du référentiel, localités, séries préexistantes.
    code_source = bind.execute(
        sa.text("SELECT code FROM sources WHERE id = :i"), {"i": contrat.source_id}
    ).scalar_one_or_none()
    if code_source != contrat.source_code:
        raise RuntimeError(
            f"Migration {REVISION} : source id {contrat.source_id} = {code_source!r}, "
            f"{contrat.source_code!r} attendue."
        )
    unite = bind.execute(
        sa.text(
            "SELECT u.code FROM grandeurs_referentiel g JOIN unites u ON u.id = g.unite_id "
            "WHERE g.code = :g AND g.actif"
        ),
        {"g": contrat.grandeur_code},
    ).scalar_one_or_none()
    if unite != UNITE_REFERENTIEL:
        raise RuntimeError(
            f"Migration {REVISION} : grandeur {contrat.grandeur_code!r} en {unite!r}, "
            f"{UNITE_REFERENTIEL!r} attendue par la conversion."
        )
    if nb_jours(contrat) != NB_JOURS:
        raise RuntimeError(f"Migration {REVISION} : contrat de {nb_jours(contrat)} jours.")
    codes_loc = _codes_localites()
    if len(codes_loc) != NB_POINTS or len(set(codes_loc)) != NB_POINTS:
        raise RuntimeError(
            f"Migration {REVISION} : {len(codes_loc)} localités, {NB_POINTS} attendues."
        )
    loc = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:c)"), {"c": codes_loc}
        ).all()
    }
    manquants = [c for c in codes_loc if c not in loc]
    if manquants:
        raise RuntimeError(f"Migration {REVISION} : localité(s) introuvable(s) : {manquants!r}.")
    codes_series = [contrat.code_serie(code) for code in codes_loc]
    preexistantes = bind.execute(
        sa.text(
            """
            SELECT code FROM series_metadonnees
            WHERE code = ANY(:codes)
               OR (source_id = :src AND granularite = 'journalier' AND grandeur_code = :g)
            """
        ),
        {"codes": codes_series, "src": contrat.source_id, "g": contrat.grandeur_code},
    ).all()
    if preexistantes:
        raise RuntimeError(
            f"Migration {REVISION} : séries déjà présentes : {[r.code for r in preexistantes]!r}."
        )

    # 1. Lecture validée du CSV (tous les jours civils, bornes, doublons, localités).
    series = lire_series_journalieres(contrat, lot)
    if [s["localite_code"] for s in series] != codes_loc:
        raise RuntimeError(
            f"Migration {REVISION} : {contrat.nom_fichier(lot)} ne couvre pas les "
            f"{NB_POINTS} localités."
        )

    # 2. Séries journalières (audit ligne à ligne de ``series_metadonnees`` conservé).
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
                "code": s["code"],
                "libelle": s["libelle"],
                "localite_id": loc[s["localite_code"]],
                "grandeur_code": contrat.grandeur_code,
                "source_id": contrat.source_id,
                "periode_debut": contrat.periode_debut,
                "periode_fin": contrat.periode_fin,
                "methode_collecte": contrat.methode_collecte,
                "granularite": contrat.granularite,
                "note_publique": NOTE,
            }
            for s in series
        ],
    )
    serie_id = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": codes_series},
        ).all()
    }
    if len(serie_id) != NB_POINTS:
        raise RuntimeError(f"Migration {REVISION} : {len(serie_id)} séries, {NB_POINTS} attendues.")

    # 3. Mesures journalières par COPY, audit ligne à ligne de ``mesures_ressource``
    #    suspendu le temps de l'insertion.
    connexion = bind.connection.driver_connection  # psycopg 3 : COPY pour le volume
    with audit_ligne_suspendu(bind):
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
        del series
        nb = bind.execute(
            sa.text("SELECT COUNT(*) FROM mesures_ressource WHERE serie_id = ANY(:ids)"),
            {"ids": list(serie_id.values())},
        ).scalar_one()
    if nb != NB_MESURES_ATTENDU:
        raise RuntimeError(f"Migration {REVISION} : {nb} mesures, {NB_MESURES_ATTENDU} attendues.")

    # 4. Une entrée d'audit par série (142), après l'insertion.
    auditer_series(bind, "I", REVISION, _fichiers())
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource"))


def downgrade() -> None:
    bind = op.get_bind()
    contrat = CONTRAT_PLUIE_ERA5_JOURNALIERE
    presentes = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": [contrat.code_serie(code) for code in _codes_localites()]},
        ).all()
    }
    if presentes:
        fichiers = _fichiers()
        # Audit par série de la suppression, avant elle (comptes et bornes lus en base).
        auditer_series(bind, "D", REVISION, {c: fichiers[c] for c in presentes})
        ids = list(presentes.values())
        with audit_ligne_suspendu(bind):
            bind.execute(
                sa.text("DELETE FROM mesures_ressource WHERE serie_id = ANY(:ids)"), {"ids": ids}
            )
        bind.execute(sa.text("DELETE FROM series_metadonnees WHERE id = ANY(:ids)"), {"ids": ids})
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource"))
