"""Tests d'intégration du seed des référentiels génériques (migration 0002).

Vérifie le peuplement des tables de référence indépendantes du pays et la
curation propre à l'instance Côte d'Ivoire : la source guinéenne
``anm_guinee_stations`` est absente, l'amont générique est présent.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


def test_contributeur_editeur_present(db_session: Session) -> None:
    """L'éditeur principal (auteur applicatif des seeds) est présent."""
    total = db_session.execute(text("SELECT count(*) FROM contributeurs")).scalar_one()
    assert total >= 1


def test_unites_et_grandeurs_peuplees(db_session: Session) -> None:
    """Les référentiels d'unités et de grandeurs sont peuplés (génériques)."""
    unites = db_session.execute(text("SELECT count(*) FROM unites")).scalar_one()
    grandeurs = db_session.execute(text("SELECT count(*) FROM grandeurs_referentiel")).scalar_one()
    assert unites == 160
    # 34 grandeurs seedees en 0002 + 4 grandeurs derivees d'ecart inter-source :
    # ecart_relatif_ghi_sarah3_nasa (0011), ecart_relatif_ghi_era5_nasa (0013),
    # ecart_relatif_ghi_cams_nasa (0015) et ecart_relatif_dni_cams_nasa (0016).
    assert grandeurs == 38


def test_source_guineenne_retiree(db_session: Session) -> None:
    """La source verrouillée sur la Guinée n'est pas versée dans l'instance CIV."""
    presente = db_session.execute(
        text("SELECT count(*) FROM sources WHERE code = 'anm_guinee_stations'")
    ).scalar_one()
    assert presente == 0


def test_amont_generique_present(db_session: Session) -> None:
    """Les sources amont génériques réutilisées par tout pays sont présentes."""
    codes = {row[0] for row in db_session.execute(text("SELECT code FROM sources")).all()}
    attendus = {"nasa_power", "ecmwf_era5", "sarah3_monthly", "cams_radiation", "kuma_calculs"}
    assert attendus <= codes
    # 14 sources amont génériques (seed 0002) + era5_pvgis ajoutée en 0012
    # (ERA5 via PVGIS, 3ᵉ source GHI pour la triangulation). CAMS (0014)
    # réutilise cams_radiation (id 13, seed 0002) : aucune source ajoutée.
    assert "era5_pvgis" in codes
    assert len(codes) == 15
