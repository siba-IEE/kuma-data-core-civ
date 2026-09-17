"""Tests d'intégration du seed des localités Côte d'Ivoire (migrations 0003-0004).

Vérifie le premier lot « localités seules » : 1 continent + 1 pays + 14
districts (dont 2 autonomes), la cohérence hiérarchique et les invariants
du lot (fuseau, ISO3, sourçage ISO 3166-2 en notes), puis la densification
sourcée des 14 districts (migration 0004 : coordonnées Wikidata, population
RGPH 2021, chef-lieu).
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

# Attendus de densification (migration 0004) : population RGPH 2021 (INS) et
# chef-lieu par district. Coordonnées = point Wikidata (bornes CIV vérifiées).
_DISTRICTS_DENSIFIES = {
    "civ_abidjan": {"pop": 6_321_017, "chef_lieu": "Abidjan"},
    "civ_bas_sassandra": {"pop": 2_687_176, "chef_lieu": "San-Pédro"},
    "civ_comoe": {"pop": 1_501_336, "chef_lieu": "Abengourou"},
    "civ_denguele": {"pop": 436_015, "chef_lieu": "Odienné"},
    "civ_goh_djiboua": {"pop": 2_088_440, "chef_lieu": "Gagnoa"},
    "civ_lacs": {"pop": 1_488_531, "chef_lieu": "Dimbokro"},
    "civ_lagunes": {"pop": 2_042_623, "chef_lieu": "Dabou"},
    "civ_montagnes": {"pop": 3_027_023, "chef_lieu": "Man"},
    "civ_sassandra_marahoue": {"pop": 2_720_877, "chef_lieu": "Daloa"},
    "civ_savanes": {"pop": 2_159_435, "chef_lieu": "Korhogo"},
    "civ_vallee_du_bandama": {"pop": 1_964_929, "chef_lieu": "Bouaké"},
    "civ_woroba": {"pop": 1_184_813, "chef_lieu": "Séguéla"},
    "civ_yamoussoukro": {"pop": 422_072, "chef_lieu": "Yamoussoukro"},
    "civ_zanzan": {"pop": 1_344_865, "chef_lieu": "Bondoukou"},
}

# Enveloppe géographique de la Côte d'Ivoire (bornes larges, marge incluse).
_CIV_LAT_MIN, _CIV_LAT_MAX = 4.0, 11.0
_CIV_LON_MIN, _CIV_LON_MAX = -9.0, -2.0


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


def test_densification_coordonnees_dans_bornes_civ(db_session: Session) -> None:
    """Après densification, chaque district a des coordonnées dans l'enveloppe CIV."""
    lignes = db_session.execute(
        text(
            "SELECT code, latitude, longitude "
            "FROM localites WHERE type_localite = 'region_administrative'"
        )
    ).all()
    assert {row.code for row in lignes} == set(_DISTRICTS_ISO)
    for row in lignes:
        assert row.latitude is not None, row.code
        assert row.longitude is not None, row.code
        assert _CIV_LAT_MIN <= float(row.latitude) <= _CIV_LAT_MAX, row.code
        assert _CIV_LON_MIN <= float(row.longitude) <= _CIV_LON_MAX, row.code


def test_densification_population_rgph_2021(db_session: Session) -> None:
    """Chaque district porte sa population RGPH 2021 (INS), année = 2021."""
    for code, attendu in _DISTRICTS_DENSIFIES.items():
        row = db_session.execute(
            text("SELECT population_estimee, annee_population FROM localites WHERE code = :c"),
            {"c": code},
        ).one()
        assert row.population_estimee == attendu["pop"], code
        assert row.annee_population == 2021, code


def test_densification_chef_lieu_en_notes(db_session: Session) -> None:
    """Le chef-lieu de chaque district figure dans ``notes`` (avec la source RGPH)."""
    for code, attendu in _DISTRICTS_DENSIFIES.items():
        notes = db_session.execute(
            text("SELECT notes FROM localites WHERE code = :c"), {"c": code}
        ).scalar_one()
        assert f"Chef-lieu : {attendu['chef_lieu']}" in notes, code
        assert "RGPH 2021" in notes, code
