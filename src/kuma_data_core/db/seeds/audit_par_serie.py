"""Audit **par série** des gravures journalières massives (ADR-0031).

Le trigger ``trg_audit_mesures_ressource`` recopie chaque ligne insérée ou
supprimée dans ``audit_log`` (``to_jsonb`` de la ligne entière). Pour les seeds
massifs — des millions de mesures dont chaque valeur est déjà versionnée dans un
CSV gzip committé et rejouable — cet audit ligne à ligne pesait 76 % de la base
(5,4 Go sur 7,1 Go à la révision 0045) sans apporter de traçabilité
supplémentaire.

Les migrations qui l'adoptent :

1. suspendent le trigger d'audit de ``mesures_ressource`` **le temps de leur
   insertion ou suppression** (``audit_ligne_suspendu``), dans la transaction de
   migration — un échec annule tout, trigger compris ;
2. écrivent **une entrée d'audit par série** (``auditer_series``) : opération
   ``I`` ou ``D``, ``id_ligne_auditee = 'serie:<id>'``, et dans
   ``valeurs_apres`` (ou ``valeurs_avant``) le code de série, le nombre de
   mesures, le premier et le dernier jour, le fichier CSV et son empreinte
   SHA-256, la révision de la migration.

Les migrations antérieures, et toute écriture applicative, gardent l'audit
ligne à ligne.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal

import sqlalchemy as sa

from kuma_data_core.db.seeds.series_csv import DOSSIER_DONNEES, ContratSerie

TABLE_MESURES: str = "mesures_ressource"
TRIGGER_AUDIT_MESURES: str = "trg_audit_mesures_ressource"


def empreinte_fichier(contrat: ContratSerie, lot: str) -> str:
    """SHA-256 du CSV gzip committé (écriture déterministe : empreinte stable)."""
    return hashlib.sha256((DOSSIER_DONNEES / contrat.nom_fichier(lot)).read_bytes()).hexdigest()


@contextmanager
def audit_ligne_suspendu(bind: sa.Connection) -> Iterator[None]:
    """Suspend l'audit ligne à ligne de ``mesures_ressource`` dans la transaction.

    Pas de ``finally`` : si le bloc échoue, la transaction de migration est
    annulée et la suspension avec elle ; réactiver le trigger dans une
    transaction en échec masquerait l'erreur d'origine.
    """
    bind.execute(sa.text(f"ALTER TABLE {TABLE_MESURES} DISABLE TRIGGER {TRIGGER_AUDIT_MESURES}"))
    yield
    bind.execute(sa.text(f"ALTER TABLE {TABLE_MESURES} ENABLE TRIGGER {TRIGGER_AUDIT_MESURES}"))


def auditer_series(
    bind: sa.Connection,
    operation: Literal["I", "D"],
    revision: str,
    fichiers: dict[str, tuple[str, str]],
) -> int:
    """Écrit une entrée d'audit par série ; renvoie le nombre d'entrées.

    ``fichiers`` : code de série → (nom du CSV, empreinte SHA-256). À appeler
    **après** l'insertion (``I``) ou **avant** la suppression (``D``) : le nombre
    de mesures et les bornes sont lus en base.
    """
    lignes = [
        {"code": code, "fichier": fichier, "sha256": empreinte}
        for code, (fichier, empreinte) in sorted(fichiers.items())
    ]
    colonne = "valeurs_apres" if operation == "I" else "valeurs_avant"
    n = bind.execute(
        sa.text(
            f"""
            INSERT INTO audit_log (
                table_auditee, schema_audite, type_operation, id_ligne_auditee,
                {colonne}, utilisateur_pg, auteur_applicatif, adresse_client
            )
            SELECT :table, 'public', :op, 'serie:' || s.id,
                   jsonb_build_object(
                       'audit', 'par_serie',
                       'revision', CAST(:revision AS text),
                       'serie_code', s.code,
                       'nb_mesures', m.nb,
                       'premier_instant', m.premier,
                       'dernier_instant', m.dernier,
                       'fichier', f.fichier,
                       'sha256', f.sha256
                   ),
                   current_user,
                   NULLIF(current_setting('kuma.auteur_applicatif', true), ''),
                   inet_client_addr()
            FROM jsonb_to_recordset(CAST(:fichiers AS jsonb))
                 AS f(code text, fichier text, sha256 text)
            JOIN series_metadonnees s ON s.code = f.code
            JOIN (
                SELECT serie_id, COUNT(*) AS nb, MIN(instant_mesure) AS premier,
                       MAX(instant_mesure) AS dernier
                FROM {TABLE_MESURES}
                WHERE serie_id IN (
                    SELECT id FROM series_metadonnees WHERE code = ANY(:codes)
                )
                GROUP BY serie_id
            ) m ON m.serie_id = s.id
            """
        ),
        {
            "table": TABLE_MESURES,
            "op": operation,
            "revision": revision,
            "fichiers": json.dumps(lignes),
            "codes": [ligne["code"] for ligne in lignes],
        },
    ).rowcount
    if n != len(lignes):
        raise RuntimeError(
            f"Audit par série ({revision}) : {n} entrées écrites, {len(lignes)} attendues."
        )
    return n
