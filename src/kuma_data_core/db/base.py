"""Classe ``Base`` SQLAlchemy déclarative pour Kuma Data Core.

La ``MetaData`` est associée à une convention de nommage stricte qui
préfixe systématiquement les contraintes et index générés par
SQLAlchemy. Cette convention rend les noms reproductibles entre
``Base.metadata.create_all()`` et les migrations Alembic, et reflète
les règles consignées dans ``docs/conventions/01-naming.md``.

Préfixes :
  * ``pk_`` - clé primaire
  * ``fk_`` - clé étrangère
  * ``uq_`` - contrainte d'unicité
  * ``ck_`` - contrainte de vérification (CHECK)
  * ``idx_`` - index
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION: dict[str, str] = {
    "ix": "idx_%(table_name)s_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s__%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Classe de base pour tous les modèles SQLAlchemy du projet."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
