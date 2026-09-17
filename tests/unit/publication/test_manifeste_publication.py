"""Tests unitaires du manifeste de publication (ADR-0003, D5 / WP0).

Tests sans DB, sur le module Python et ``Base.metadata``. Couvrent :

1. Complétude : toute table de ``Base.metadata`` est classée dans
   exactement une catégorie (publiée, assainie, exclue). Une table
   ajoutée au schéma sans classement explicite casse ce test : c'est
   la garde anti-fuite mécanique de l'ADR-0003.
2. Disjonction : les trois catégories sont deux à deux disjointes.
3. Pas de table fantôme : le manifeste ne classe aucune table absente
   du schéma (protège contre les coquilles de nommage).
4. Ancres : ``audit_log`` est exclue, ``contributeurs`` est assainie.
5. Règles d'assainissement : chaque table assainie a des règles, chaque
   règle vise une colonne existante du modèle.
6. Cohérence NOT NULL : une colonne non nullable ne reçoit jamais
   l'expression ``NULL``.
7. Cohérence UNIQUE : ``email_principal`` (NOT NULL UNIQUE) reçoit une
   expression dérivée de ``id`` (valeur distincte par ligne).
"""

from __future__ import annotations

import pytest

import kuma_data_core.db.models  # noqa: F401  (enregistre les modèles)
from kuma_data_core.db.base import Base
from kuma_data_core.publication.manifeste import (
    ASSAINISSEMENTS,
    TABLES_ASSAINIES,
    TABLES_EXCLUES,
    TABLES_PUBLIEES,
    tables_classees,
    tables_dumpees,
)

pytestmark = pytest.mark.unit


def _tables_du_schema() -> frozenset[str]:
    return frozenset(Base.metadata.tables.keys())


def test_toute_table_du_schema_est_classee() -> None:
    """Garde anti-fuite : une table non classée fait échouer la CI."""
    non_classees = _tables_du_schema() - tables_classees()
    assert not non_classees, (
        f"Tables du schéma non classées dans le manifeste de publication : "
        f"{sorted(non_classees)}. Classer chaque table dans TABLES_PUBLIEES, "
        f"TABLES_ASSAINIES ou TABLES_EXCLUES (cf. ADR-0003, D5)."
    )


def test_categories_deux_a_deux_disjointes() -> None:
    assert not TABLES_PUBLIEES & TABLES_ASSAINIES
    assert not TABLES_PUBLIEES & TABLES_EXCLUES
    assert not TABLES_ASSAINIES & TABLES_EXCLUES


def test_aucune_table_fantome() -> None:
    """Le manifeste ne classe rien qui n'existe pas dans le schéma ORM."""
    fantomes = tables_classees() - _tables_du_schema()
    assert not fantomes, f"Tables classées mais absentes du schéma : {sorted(fantomes)}"


def test_ancres_de_classification() -> None:
    assert "audit_log" in TABLES_EXCLUES
    assert "contributeurs" in TABLES_ASSAINIES
    assert "audit_log" not in tables_dumpees()


def test_chaque_table_assainie_a_des_regles() -> None:
    assert set(ASSAINISSEMENTS.keys()) == set(TABLES_ASSAINIES)
    for table, regles in ASSAINISSEMENTS.items():
        assert regles, f"Table assainie sans règle : {table}"


def test_regles_visent_des_colonnes_existantes() -> None:
    for nom_table, regles in ASSAINISSEMENTS.items():
        colonnes = set(Base.metadata.tables[nom_table].columns.keys())
        inconnues = set(regles) - colonnes
        assert not inconnues, (
            f"Règles d'assainissement sur des colonnes absentes de "
            f"{nom_table} : {sorted(inconnues)}"
        )


def test_pas_de_null_sur_colonne_not_null() -> None:
    for nom_table, regles in ASSAINISSEMENTS.items():
        table = Base.metadata.tables[nom_table]
        for colonne, expression in regles.items():
            if not table.columns[colonne].nullable:
                assert expression.strip().upper() != "NULL", (
                    f"{nom_table}.{colonne} est NOT NULL : l'expression "
                    f"d'assainissement ne peut pas être NULL."
                )


def test_email_principal_assaini_par_ligne() -> None:
    """email_principal est NOT NULL UNIQUE : l'expression doit dériver de id."""
    expression = ASSAINISSEMENTS["contributeurs"]["email_principal"]
    assert "id" in expression, (
        "email_principal est UNIQUE : l'expression d'assainissement doit "
        "produire une valeur distincte par ligne (dérivée de id)."
    )
