"""Génération du SQL de construction d'une édition publique (ADR-0003, WP1).

Le script d'export (``scripts/publication/exporter-edition.ps1``) n'encode
aucune règle de filtre : il consomme le SQL produit ici, qui dérive
entièrement du manifeste (``publication/manifeste.py``). Une seule source
de vérité, testable.

Trois commandes, exécutées dans cet ordre sur la base d'édition
intermédiaire LOCALE (copie de la référence, cf. ADR-0003 D5) :

1. ``construction`` : purge de l'audit (fonction + triggers, AVANT tout
   UPDATE, sinon les triggers rejoueraient sur l'assainissement), drop
   des tables exclues, puis assainissement des tables classées ainsi.
2. ``controles`` : garde anti-fuite exécutable - un bloc ``DO`` qui lève
   si un objet exclu subsiste ou si une règle d'assainissement n'a pas
   été appliquée (l'expression est recalculée et comparée ligne à ligne).
   Un échec fait échouer ``psql`` (``ON_ERROR_STOP``), donc l'export.
3. ``metadonnees`` : table ``edition_metadonnees`` (une ligne), produite
   au moment de la publication (ADR-0003 D7). Cette table n'existe QUE
   dans l'édition - elle est hors schéma de référence et hors lignée
   Alembic ; l'endpoint ``GET /v1/edition`` (WP5) la lira.

Usage : ``python -m kuma_data_core.publication.sql_edition <commande>``,
le SQL est écrit sur stdout.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence

from kuma_data_core.publication.manifeste import (
    ASSAINISSEMENTS,
    FONCTION_AUDIT,
    PREFIXE_TRIGGERS_AUDIT,
    TABLES_EXCLUES,
)

# Formats imposés aux métadonnées d'édition. Les valeurs sont interpolées
# dans du SQL : tout ce qui ne matche pas est rejeté (pas d'échappement,
# un format strict suffit puisque c'est nous qui produisons ces valeurs).
_RE_EDITION_ID = re.compile(r"^edition_\d{8}$")
_RE_DATE_PUBLICATION = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RE_REVISION_SOURCE = re.compile(r"^[0-9a-f]{7,40}$")


def instructions_construction() -> list[str]:
    """Instructions de purge + assainissement, une par élément.

    Exposées individuellement pour les exécuteurs qui ne savent pas
    découper un script multi-instructions (psycopg n'accepte qu'une
    instruction par ``execute``, et le bloc ``DO`` contient des ``;``
    internes) : le test de non-fuite (WP9) les rejoue une à une dans
    une transaction annulée.
    """
    morceaux: list[str] = []

    # 1. Fonction d'audit : le CASCADE emporte tous les triggers qui la
    #    référencent. Le bloc DO qui suit ramasse d'éventuels triggers
    #    du préfixe d'audit non liés à la fonction (ceinture et bretelles).
    morceaux.append(f"DROP FUNCTION IF EXISTS {FONCTION_AUDIT}() CASCADE;")
    morceaux.append(
        f"""\
DO $purge_triggers$
DECLARE
    t RECORD;
BEGIN
    FOR t IN
        SELECT tg.tgname, cl.relname
        FROM pg_trigger tg
        JOIN pg_class cl ON tg.tgrelid = cl.oid
        WHERE NOT tg.tgisinternal
          AND tg.tgname LIKE '{PREFIXE_TRIGGERS_AUDIT}%'
    LOOP
        EXECUTE format('DROP TRIGGER %I ON %I', t.tgname, t.relname);
    END LOOP;
END
$purge_triggers$;"""
    )

    # 2. Tables exclues.
    for table in sorted(TABLES_EXCLUES):
        morceaux.append(f"DROP TABLE IF EXISTS {table} CASCADE;")

    # 3. Assainissement : un UPDATE par table, toutes colonnes d'un coup.
    for table in sorted(ASSAINISSEMENTS):
        regles = ASSAINISSEMENTS[table]
        affectations = ",\n    ".join(
            f"{colonne} = {expression}" for colonne, expression in sorted(regles.items())
        )
        morceaux.append(f"UPDATE {table} SET\n    {affectations};")

    return morceaux


def sql_construction() -> str:
    """Script complet de construction (pour ``psql``, qui sait le découper)."""
    return "\n\n".join(instructions_construction()) + "\n"


def sql_controles() -> str:
    """Garde anti-fuite : lève si la construction n'a pas tout appliqué."""
    verifications: list[str] = []

    for table in sorted(TABLES_EXCLUES):
        verifications.append(
            f"""\
    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public'
               AND tablename = '{table}') THEN
        RAISE EXCEPTION 'fuite : table exclue % présente', '{table}';
    END IF;"""
        )

    verifications.append(
        f"""\
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = '{FONCTION_AUDIT}') THEN
        RAISE EXCEPTION 'fuite : fonction d''audit {FONCTION_AUDIT} présente';
    END IF;"""
    )
    verifications.append(
        f"""\
    IF EXISTS (SELECT 1 FROM pg_trigger WHERE NOT tgisinternal
               AND tgname LIKE '{PREFIXE_TRIGGERS_AUDIT}%') THEN
        RAISE EXCEPTION 'fuite : triggers d''audit présents';
    END IF;"""
    )

    # Assainissement vérifié par recalcul : aucune ligne ne doit différer
    # de l'expression du manifeste (IS DISTINCT FROM couvre les NULL).
    for table in sorted(ASSAINISSEMENTS):
        for colonne, expression in sorted(ASSAINISSEMENTS[table].items()):
            verifications.append(
                f"""\
    IF EXISTS (SELECT 1 FROM {table}
               WHERE {colonne} IS DISTINCT FROM ({expression})) THEN
        RAISE EXCEPTION 'fuite : {table}.{colonne} non assainie';
    END IF;"""
            )

    corps = "\n".join(verifications)
    return f"""\
DO $controles_edition$
BEGIN
{corps}
END
$controles_edition$;
"""


def sql_metadonnees(edition_id: str, date_publication: str, revision_source: str) -> str:
    """Table ``edition_metadonnees`` (une ligne), injectée dans l'édition."""
    # fullmatch (et non match) : ancre la fin sans laisser passer un retour
    # ligne final, que ``$`` autoriserait. Ceinture-bretelle même si ces
    # valeurs viennent d'un contexte local de confiance (date, hash git).
    if not _RE_EDITION_ID.fullmatch(edition_id):
        raise ValueError(f"edition_id invalide (attendu edition_AAAAMMJJ) : {edition_id!r}")
    if not _RE_DATE_PUBLICATION.fullmatch(date_publication):
        raise ValueError(f"date_publication invalide (attendu AAAA-MM-JJ) : {date_publication!r}")
    if not _RE_REVISION_SOURCE.fullmatch(revision_source):
        raise ValueError(f"revision_source invalide (attendu hash git hex) : {revision_source!r}")

    return f"""\
CREATE TABLE edition_metadonnees (
    edition_id VARCHAR(40) NOT NULL,
    date_publication DATE NOT NULL,
    revision_source VARCHAR(40) NOT NULL,
    CONSTRAINT pk_edition_metadonnees PRIMARY KEY (edition_id)
);

INSERT INTO edition_metadonnees (edition_id, date_publication, revision_source)
VALUES ('{edition_id}', '{date_publication}', '{revision_source}');
"""


def principal(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée CLI : écrit le SQL de la commande demandée sur stdout."""
    parser = argparse.ArgumentParser(
        prog="python -m kuma_data_core.publication.sql_edition",
        description="Génère le SQL de construction d'une édition publique (ADR-0003).",
    )
    sous = parser.add_subparsers(dest="commande", required=True)
    sous.add_parser("construction", help="purge audit + tables exclues + assainissement")
    sous.add_parser("controles", help="garde anti-fuite (lève si la purge est incomplète)")
    p_meta = sous.add_parser("metadonnees", help="table edition_metadonnees (une ligne)")
    p_meta.add_argument("--edition-id", required=True)
    p_meta.add_argument("--date-publication", required=True)
    p_meta.add_argument("--revision-source", required=True)

    args = parser.parse_args(argv)
    if args.commande == "construction":
        print(sql_construction())
    elif args.commande == "controles":
        print(sql_controles())
    else:
        print(sql_metadonnees(args.edition_id, args.date_publication, args.revision_source))
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
