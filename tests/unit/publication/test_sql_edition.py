"""Tests unitaires du générateur SQL d'édition (ADR-0003, WP1).

Tests sans DB, sur les chaînes SQL produites. Couvrent :

1. Construction : ordre purge-avant-assainissement (les triggers d'audit
   ne doivent pas rejouer sur les UPDATE d'assainissement), CASCADE sur
   la fonction, drop de chaque table exclue, un UPDATE par table
   assainie couvrant chaque règle du manifeste.
2. Contrôles : chaque objet exclu et chaque règle d'assainissement a sa
   vérification (recalcul de l'expression, IS DISTINCT FROM).
3. Métadonnées : formats stricts, rejet des valeurs hors format (les
   valeurs sont interpolées dans du SQL, le format EST la protection).
4. CLI : chaque commande écrit son SQL sur stdout.
"""

from __future__ import annotations

import pytest

from kuma_data_core.publication.manifeste import (
    ASSAINISSEMENTS,
    FONCTION_AUDIT,
    TABLES_EXCLUES,
)
from kuma_data_core.publication.sql_edition import (
    principal,
    sql_construction,
    sql_controles,
    sql_metadonnees,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------- construction


def test_construction_purge_fonction_audit_en_cascade() -> None:
    sql = sql_construction()
    assert f"DROP FUNCTION IF EXISTS {FONCTION_AUDIT}() CASCADE;" in sql


def test_construction_drop_chaque_table_exclue() -> None:
    sql = sql_construction()
    for table in TABLES_EXCLUES:
        assert f"DROP TABLE IF EXISTS {table} CASCADE;" in sql


def test_construction_purge_avant_assainissement() -> None:
    """Les UPDATE d'assainissement ne doivent jamais rejouer l'audit."""
    sql = sql_construction()
    position_purge = sql.index("DROP FUNCTION")
    position_update = sql.index("UPDATE ")
    assert position_purge < position_update


def test_construction_assainit_chaque_regle_du_manifeste() -> None:
    sql = sql_construction()
    for table, regles in ASSAINISSEMENTS.items():
        assert f"UPDATE {table} SET" in sql
        for colonne, expression in regles.items():
            assert f"{colonne} = {expression}" in sql


# ------------------------------------------------------------------- contrôles


def test_controles_couvrent_tables_exclues_fonction_et_triggers() -> None:
    sql = sql_controles()
    for table in TABLES_EXCLUES:
        assert f"tablename = '{table}'" in sql
    assert f"proname = '{FONCTION_AUDIT}'" in sql
    assert "pg_trigger" in sql


def test_controles_recalculent_chaque_expression_d_assainissement() -> None:
    sql = sql_controles()
    for table, regles in ASSAINISSEMENTS.items():
        for colonne, expression in regles.items():
            assert f"{colonne} IS DISTINCT FROM ({expression})" in sql, (
                f"Contrôle manquant pour {table}.{colonne}"
            )


def test_controles_forment_un_bloc_do_qui_leve() -> None:
    sql = sql_controles()
    assert sql.startswith("DO ")
    assert "RAISE EXCEPTION" in sql


# ---------------------------------------------------------------- métadonnées


def test_metadonnees_valides() -> None:
    sql = sql_metadonnees("edition_20260702", "2026-07-02", "e97f681abcd")
    assert "CREATE TABLE edition_metadonnees" in sql
    assert "pk_edition_metadonnees" in sql
    assert "VALUES ('edition_20260702', '2026-07-02', 'e97f681abcd');" in sql


@pytest.mark.parametrize(
    ("edition_id", "date_publication", "revision_source"),
    [
        ("edition_2026", "2026-07-02", "e97f681abcd"),  # id trop court
        ("edition_20260702'; DROP TABLE x;--", "2026-07-02", "e97f681abcd"),
        ("edition_20260702", "02/07/2026", "e97f681abcd"),  # date hors format
        ("edition_20260702", "2026-07-02", "pas-un-hash"),
        ("edition_20260702", "2026-07-02", "E97F681"),  # hex majuscule refusé
    ],
)
def test_metadonnees_rejettent_les_formats_invalides(
    edition_id: str, date_publication: str, revision_source: str
) -> None:
    with pytest.raises(ValueError):
        sql_metadonnees(edition_id, date_publication, revision_source)


# ------------------------------------------------------------------------ CLI


def test_cli_construction(capsys: pytest.CaptureFixture[str]) -> None:
    assert principal(["construction"]) == 0
    assert "DROP FUNCTION" in capsys.readouterr().out


def test_cli_controles(capsys: pytest.CaptureFixture[str]) -> None:
    assert principal(["controles"]) == 0
    assert "RAISE EXCEPTION" in capsys.readouterr().out


def test_cli_metadonnees(capsys: pytest.CaptureFixture[str]) -> None:
    code = principal(
        [
            "metadonnees",
            "--edition-id",
            "edition_20260702",
            "--date-publication",
            "2026-07-02",
            "--revision-source",
            "e97f681abcd",
        ]
    )
    assert code == 0
    assert "edition_metadonnees" in capsys.readouterr().out
