"""referentiels_generiques

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-17

Peuplement des **référentiels génériques** du moteur, indépendants du pays :

* ``contributeurs`` : l'éditeur principal (auteur applicatif des seeds) ;
* ``unites`` : le référentiel d'unités (base + compléments + PSP) ;
* ``grandeurs_referentiel`` : le catalogue des grandeurs (GHI, DNI, POA, …) ;
* ``sources`` : le catalogue des sources amont et normes.

Les données sont capturées depuis la base de référence de l'instance
Guinée (``pg_dump --data-only --column-inserts``), puis **curées pour
l'instance Côte d'Ivoire** : la source ``anm_guinee_stations`` (Agence
Nationale de la Météorologie de Guinée, verrouillée sur la Guinée) est
retirée. Les autres sources (NASA POWER, ERA5(-Land), SARAH-3/PVGIS, CAMS,
ESMAP/WAPP, ``kuma_calculs``, normes IEC/WMO) sont l'amont générique
réutilisé par tout pays.

Les inserts fixent explicitement les identifiants ; les séquences
d'identité sont recalées en fin de script (``setval``) conformément au
dump. Le trigger d'audit se déclenche mais tolère l'absence d'auteur
applicatif (``current_setting('kuma.auteur_applicatif', true)``) ; comme
sur l'instance Guinée, aucun ``set_config`` n'est posé pour les seeds.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL_REFERENTIELS = Path(__file__).resolve().parent.parent / "sql" / "0002_referentiels.sql"

# Tables peuplées ici, vidées au downgrade (CASCADE : purge aussi l'audit lié).
_TABLES = ("sources", "grandeurs_referentiel", "unites", "contributeurs")


def upgrade() -> None:
    # Connexion psycopg brute sans paramètres (protocole simple) : les notes
    # des sources contiennent des ``%`` (pourcentages) qui ne doivent pas être
    # lus comme des placeholders, et le script est multi-instructions.
    raw = op.get_bind().connection.driver_connection
    with raw.cursor() as cur:
        cur.execute(_SQL_REFERENTIELS.read_text(encoding="utf-8"))


def downgrade() -> None:
    conn = op.get_bind()
    tables = ", ".join(f"public.{t}" for t in _TABLES)
    conn.exec_driver_sql(f"TRUNCATE {tables} RESTART IDENTITY CASCADE;")
