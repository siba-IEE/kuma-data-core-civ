"""Gravure de séries journalières depuis les CSV gzip du dépôt (migrations 0053+).

Mêmes étapes que les migrations journalières 0046 à 0052, réunies ici :
lecture validée du CSV (``series_csv.lire_series_journalieres``), insertion des
séries (``series_metadonnees``, audit ligne à ligne conservé), insertion des
mesures par ``COPY`` (audit ligne à ligne de ``mesures_ressource`` suspendu,
ADR-0031), contrôle des comptes, puis une entrée d'audit par série
(``audit_par_serie``). Les garde-fous propres à chaque lot (source, unités,
séries préexistantes, chiffres cités dans les notes) restent dans la migration.

Les jours non servis par la source (contrat à ``lacunes_admises``) ne sont pas
gravés : le nombre de mesures attendu d'une série est son nombre de jours servis.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import sqlalchemy as sa

from kuma_data_core.db.seeds.audit_par_serie import (
    audit_ligne_suspendu,
    auditer_series,
    empreinte_fichier,
)
from kuma_data_core.db.seeds.series_csv import ContratSerie, lire_series_journalieres

TABLE_SERIES = sa.table(
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


def fichiers_lot(
    contrats: list[ContratSerie], lot: str, codes_localites: list[str]
) -> dict[str, tuple[str, str]]:
    """Code de série → (CSV, empreinte SHA-256), pour l'audit par série."""
    fichiers: dict[str, tuple[str, str]] = {}
    for contrat in contrats:
        fichier = (contrat.nom_fichier(lot), empreinte_fichier(contrat, lot))
        fichiers.update({contrat.code_serie(code): fichier for code in codes_localites})
    return fichiers


def graver_lot(
    bind: sa.Connection,
    revision: str,
    contrats: list[ContratSerie],
    lot: str,
    localites: dict[str, int],
    note: Callable[[ContratSerie, dict[str, Any]], str],
) -> int:
    """Grave les séries de ``contrats`` (un CSV par contrat) aux ``localites`` (code → id).

    ``note(contrat, serie)`` donne la note publique de chaque série. Renvoie le
    nombre de mesures gravées ; lève ``RuntimeError`` si un CSV ne couvre pas
    exactement les localités ou si les comptes en base diffèrent du CSV.
    """
    codes_loc = sorted(localites)
    connexion = bind.connection.driver_connection  # psycopg 3 : COPY pour le volume
    if connexion is None:
        raise RuntimeError(f"Migration {revision} : connexion psycopg indisponible pour COPY.")
    total = 0
    with audit_ligne_suspendu(bind):
        for contrat in contrats:
            series = lire_series_journalieres(contrat, lot)
            if [s["localite_code"] for s in series] != codes_loc:
                raise RuntimeError(
                    f"Migration {revision} : {contrat.nom_fichier(lot)} ne couvre pas le lot."
                )
            bind.execute(
                sa.insert(TABLE_SERIES),
                [
                    {
                        "code": s["code"],
                        "libelle": s["libelle"],
                        "localite_id": localites[s["localite_code"]],
                        "grandeur_code": contrat.grandeur_code,
                        "source_id": contrat.source_id,
                        "periode_debut": contrat.periode_debut,
                        "periode_fin": contrat.periode_fin,
                        "methode_collecte": contrat.methode_collecte,
                        "granularite": contrat.granularite,
                        "note_publique": note(contrat, s),
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
            attendu = sum(len(s["mesures"]) for s in series)
            if len(serie_id) != len(codes_loc) or nb != attendu:
                raise RuntimeError(
                    f"Migration {revision} : {contrat.prefixe_code} : {len(serie_id)} séries et "
                    f"{nb} mesures, {len(codes_loc)} et {attendu} attendues."
                )
            total += nb
            del series
    auditer_series(bind, "I", revision, fichiers_lot(contrats, lot, codes_loc))
    return total


def supprimer_lot(
    bind: sa.Connection,
    revision: str,
    contrats: list[ContratSerie],
    lot: str,
    codes_localites: list[str],
) -> None:
    """Supprime les séries du lot et leurs mesures, après leur audit par série."""
    codes = [c.code_serie(code) for c in contrats for code in codes_localites]
    presentes = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": codes},
        ).all()
    }
    if not presentes:
        return
    fichiers = fichiers_lot(contrats, lot, codes_localites)
    # Audit par série de la suppression, avant elle (comptes et bornes lus en base).
    auditer_series(bind, "D", revision, {c: fichiers[c] for c in presentes})
    ids = list(presentes.values())
    with audit_ligne_suspendu(bind):
        bind.execute(
            sa.text("DELETE FROM mesures_ressource WHERE serie_id = ANY(:ids)"), {"ids": ids}
        )
    bind.execute(sa.text("DELETE FROM series_metadonnees WHERE id = ANY(:ids)"), {"ids": ids})
