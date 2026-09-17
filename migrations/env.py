"""Environnement Alembic pour Kuma Data Core.

Ce module est exécuté par Alembic à chaque commande (``upgrade``,
``downgrade``, ``revision``, etc.). Il :

  1. Charge la configuration centrale via ``kuma_data_core.core.config``,
     elle-même alimentée par le fichier ``.env`` à la racine.
  2. Importe ``Base.metadata`` (cible des comparaisons d'autogénération).
  3. Importe les modèles SQLAlchemy pour qu'ils s'enregistrent dans la
     metadata avant qu'Alembic ne la lise.
  4. Configure l'exécution en mode online (avec connexion) ou offline
     (génération de SQL pur).

Activations notables :
  * ``compare_type = True`` : détecte les changements de type de colonne.
  * ``compare_server_default = True`` : détecte les changements de
    valeurs par défaut côté serveur.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from kuma_data_core.core.config import get_settings

# -----------------------------------------------------------------------------
# Import des modèles SQLAlchemy.
#
# Tout modèle doit être importé ici (directement ou via un module qui les
# importe en cascade) pour qu'Alembic le voie via ``Base.metadata``.
# L'import ci-dessous tire la chaîne complète des modèles via
# ``models/__init__.py``.
# -----------------------------------------------------------------------------
from kuma_data_core.db import models  # noqa: F401
from kuma_data_core.db.base import Base

# -----------------------------------------------------------------------------
# Configuration de logging Alembic (lue depuis alembic.ini).
# -----------------------------------------------------------------------------
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# -----------------------------------------------------------------------------
# Injection dynamique de la chaîne de connexion : on ne stocke pas
# ``sqlalchemy.url`` dans alembic.ini (jamais de secret dans un fichier
# versionné). On la calcule à partir des Settings.
# -----------------------------------------------------------------------------
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

# -----------------------------------------------------------------------------
# Cible des comparaisons d'autogénération.
# -----------------------------------------------------------------------------
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Exécute les migrations en mode hors-ligne.

    Aucune connexion n'est ouverte : Alembic émet le SQL sur stdout. Ce
    mode est utile pour produire des scripts de migration à appliquer
    manuellement.
    """
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Exécute les migrations en mode connecté."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
