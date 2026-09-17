"""baseline_schema_civ

Revision ID: 0001
Revises:
Create Date: 2026-09-17

Baseline schéma unique du moteur dédié Côte d'Ivoire.

Ce fichier remplace, par un **squash**, la chaîne historique des 121
migrations de l'instance Guinée. Le schéma est capturé fidèlement par
``pg_dump --schema-only`` de la base construite par cette chaîne complète
(tables, vues, contraintes, index, fonctions PL/pgSQL et triggers d'audit
et de validation hiérarchique, extension ``btree_gist``), **sans aucune
donnée**. Le SQL brut est stocké dans ``migrations/sql/0001_baseline_schema.sql``
et rejoué tel quel : les objets non capturables par autogénération
(triggers, fonctions ``SECURITY DEFINER``, vues) sont ainsi préservés à
l'identique.

Le peuplement (référentiels génériques, localités) suit dans des
migrations dédiées (0002, 0003).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL_BASELINE = Path(__file__).resolve().parent.parent / "sql" / "0001_baseline_schema.sql"


def _exec_script(sql: str) -> None:
    """Exécute un script SQL multi-instructions via la connexion psycopg brute.

    On passe par ``driver_connection`` **sans paramètres** : psycopg3 emploie
    alors le protocole simple (plusieurs instructions séparées par ``;``
    autorisées) et ne tente pas d'interpréter les ``%`` du corps des fonctions
    PL/pgSQL (``RAISE EXCEPTION '... %'``) comme des placeholders. La connexion
    brute est celle de la transaction Alembic en cours.
    """
    raw = op.get_bind().connection.driver_connection
    with raw.cursor() as cur:
        cur.execute(sql)


# Objets créés par la baseline, à retirer au downgrade (ordre indifférent
# grâce à CASCADE ; alembic_version, hors baseline, n'est jamais touchée).
_TABLES = (
    "audit_log",
    "calage_couverture",
    "contributeurs",
    "grandeurs_metier",
    "grandeurs_referentiel",
    "localites",
    "mesures_ressource",
    "mesures_ressource_horaires",
    "mesures_ressource_mensuelles",
    "referentiels_calage",
    "series_metadonnees",
    "sources",
    "unites",
)
_VUES = (
    "v_mesures_avec_niveau_effectif",
    "v_grandeurs_metier_courantes",
)
_FONCTIONS = (
    "kuma_log_audit()",
    "valider_hierarchie_localites()",
)


def upgrade() -> None:
    _exec_script(_SQL_BASELINE.read_text(encoding="utf-8"))


def downgrade() -> None:
    conn = op.get_bind()
    for vue in _VUES:
        conn.exec_driver_sql(f"DROP VIEW IF EXISTS public.{vue} CASCADE;")
    for table in _TABLES:
        conn.exec_driver_sql(f"DROP TABLE IF EXISTS public.{table} CASCADE;")
    for fonction in _FONCTIONS:
        conn.exec_driver_sql(f"DROP FUNCTION IF EXISTS public.{fonction} CASCADE;")
    conn.exec_driver_sql("DROP EXTENSION IF EXISTS btree_gist;")
