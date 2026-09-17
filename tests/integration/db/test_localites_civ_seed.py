"""Tests d'intégration du seed des localités Côte d'Ivoire (migration 0003).

Vérifie le premier lot « localités seules » : 1 continent + 1 pays + 14
districts (dont 2 autonomes), la cohérence hiérarchique et les invariants
du lot (fuseau, ISO3, sourçage ISO 3166-2 en notes, densification différée).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

# Les 14 districts attendus (code métier -> sous-code ISO 3166-2:CI).
_DISTRICTS_ISO = {
    "civ_abidjan": "CI-AB",
    "civ_bas_sassandra": "CI-BS",
    "civ_comoe": "CI-CM",
    "civ_denguele": "CI-DN",
    "civ_goh_djiboua": "CI-GD",
    "civ_lacs": "CI-LC",
    "civ_lagunes": "CI-LG",
    "civ_montagnes": "CI-MG",
    "civ_sassandra_marahoue": "CI-SM",
    "civ_savanes": "CI-SV",
    "civ_vallee_du_bandama": "CI-VB",
    "civ_woroba": "CI-WR",
    "civ_yamoussoukro": "CI-YM",
    "civ_zanzan": "CI-ZZ",
}
_DISTRICTS_AUTONOMES = {"civ_abidjan", "civ_yamoussoukro"}


def test_nombre_total_localites(db_session: Session) -> None:
    """16 localités : 1 continent + 1 pays + 14 districts."""
    total = db_session.execute(text("SELECT count(*) FROM localites")).scalar_one()
    assert total == 16


def test_racine_et_pays(db_session: Session) -> None:
    """``afrique`` est la racine ; ``civ`` est un pays rattaché à l'Afrique."""
    afrique = db_session.execute(
        text("SELECT type_localite, parent_id FROM localites WHERE code = 'afrique'")
    ).one()
    assert afrique.type_localite == "continent"
    assert afrique.parent_id is None

    civ = db_session.execute(
        text(
            "SELECT type_localite, pays_iso3, fuseau_horaire, parent_id "
            "FROM localites WHERE code = 'civ'"
        )
    ).one()
    assert civ.type_localite == "pays"
    assert civ.pays_iso3 == "CIV"
    assert civ.fuseau_horaire == "Africa/Abidjan"
    parent_code = db_session.execute(
        text("SELECT code FROM localites WHERE id = :pid"), {"pid": civ.parent_id}
    ).scalar_one()
    assert parent_code == "afrique"


def test_quatorze_districts_rattaches_au_pays(db_session: Session) -> None:
    """Les 14 districts sont des ``region_administrative`` enfants de ``civ``."""
    lignes = db_session.execute(
        text(
            """
            SELECT d.code, d.type_localite, d.pays_iso3, d.fuseau_horaire, p.code AS parent
            FROM localites d
            JOIN localites p ON p.id = d.parent_id
            WHERE d.type_localite = 'region_administrative'
            ORDER BY d.code
            """
        )
    ).all()
    assert {row.code for row in lignes} == set(_DISTRICTS_ISO)
    for row in lignes:
        assert row.type_localite == "region_administrative"
        assert row.pays_iso3 == "CIV"
        assert row.fuseau_horaire == "Africa/Abidjan"
        assert row.parent == "civ"


def test_codes_iso_3166_2_en_notes(db_session: Session) -> None:
    """Chaque district porte son sous-code ISO 3166-2:CI dans ``notes``."""
    for code, iso in _DISTRICTS_ISO.items():
        notes = db_session.execute(
            text("SELECT notes FROM localites WHERE code = :c"), {"c": code}
        ).scalar_one()
        assert iso in notes


def test_districts_autonomes_qualifies(db_session: Session) -> None:
    """Abidjan et Yamoussoukro sont marqués « District autonome » dans les notes."""
    for code in _DISTRICTS_AUTONOMES:
        notes = db_session.execute(
            text("SELECT notes FROM localites WHERE code = :c"), {"c": code}
        ).scalar_one()
        assert "District autonome" in notes


def test_densification_differee_coordonnees_nulles(db_session: Session) -> None:
    """Le premier lot n'invente aucune coordonnée : lat/lon/pop restent NULL."""
    lignes = db_session.execute(
        text(
            "SELECT latitude, longitude, population_estimee "
            "FROM localites WHERE type_localite = 'region_administrative'"
        )
    ).all()
    assert lignes  # non vide
    for row in lignes:
        assert row.latitude is None
        assert row.longitude is None
        assert row.population_estimee is None
