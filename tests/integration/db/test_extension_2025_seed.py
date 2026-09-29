"""Tests d'intégration de l'extension temporelle 2021-2025 (migrations 0030-0032).

ADR-0018 : les séries déjà gravées sont **prolongées** (mêmes codes) jusqu'à la
dernière année servie par chaque source — NASA POWER et CAMS jusqu'en 2025,
SARAH-3 et ERA5 jusqu'en 2023. Vérifie, pour toutes les séries concernées
(brutes mensuelles, journalières NASA, écarts, fraction diffuse) : fin de
période, libellé « (AAAA-fin) », phrase ajoutée à la note publique, et absence
de toute valeur au-delà de la fin servie. Vérifie aussi la mise en garde sur le
saut ERA5 de 2021 (migration 0033), portée par les notes des seules séries ERA5.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds.lots_civ import (
    CONTRATS_ERA5,
    CONTRATS_EXTENSION,
    CONTRATS_NASA_JOURNALIERS_EXTENSION,
    ECARTS_INTER_SOURCES,
    FIN_EXTENSION,
    EcartInterSource,
    points_journalier,
    points_nationaux,
)
from kuma_data_core.db.seeds.series_csv import ContratSerie

pytestmark = pytest.mark.integration

_LOCALITES = [code for code, _, _, _ in points_nationaux()]


def _verifier_series(db_session: Session, codes: list[str], fin: int) -> None:
    rows = db_session.execute(
        text(
            "SELECT code, periode_fin, libelle, note_publique FROM series_metadonnees "
            "WHERE code = ANY(:c)"
        ),
        {"c": codes},
    ).all()
    assert len(rows) == len(codes)
    for r in rows:
        assert str(r.periode_fin) == f"{fin}-12-31", r.code
        assert r.libelle.endswith(f"-{fin})"), r.libelle
        assert f" Prolongée jusqu'en {fin} (ADR-0018)." in r.note_publique, r.code


def _id(contrat: ContratSerie) -> str:
    return contrat.prefixe_code


def test_142_localites() -> None:
    """L'extension couvre les 3 pilotes et les 139 localités des lots."""
    assert len(_LOCALITES) == 142


@pytest.mark.parametrize("contrat", CONTRATS_EXTENSION, ids=_id)
def test_series_mensuelles_prolongees(db_session: Session, contrat: ContratSerie) -> None:
    """Séries brutes : métadonnées prolongées, aucune mesure au-delà de la fin servie."""
    codes = [contrat.code_serie(code) for code in _LOCALITES]
    _verifier_series(db_session, codes, contrat.annee_fin)
    row = db_session.execute(
        text(
            """
            SELECT MAX(m.annee) AS derniere, COUNT(*) FILTER (WHERE m.annee > 2020) AS ajout
            FROM mesures_ressource_mensuelles m JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": codes},
    ).one()
    assert row.derniere == contrat.annee_fin == FIN_EXTENSION[contrat.source_code]
    assert row.ajout == 142 * contrat.nb_mois


def test_series_journalieres_prolongees(db_session: Session) -> None:
    """Journalier NASA : 34 localités, 3 grandeurs, prolongées jusqu'au 31/12/2025."""
    codes = [
        c.code_serie(code)
        for c in CONTRATS_NASA_JOURNALIERS_EXTENSION.values()
        for code, _, _, _ in points_journalier()
    ]
    _verifier_series(db_session, codes, 2025)
    derniere = db_session.execute(
        text(
            "SELECT MAX(m.instant_mesure) FROM mesures_ressource m "
            "JOIN series_metadonnees s ON s.id = m.serie_id WHERE s.code = ANY(:c)"
        ),
        {"c": codes},
    ).scalar_one()
    assert str(derniere) == "2025-12-31"


@pytest.mark.parametrize("ecart", ECARTS_INTER_SOURCES, ids=lambda e: e.grandeur_code)
def test_ecarts_prolonges(db_session: Session, ecart: EcartInterSource) -> None:
    """Écarts : fin = dernière année commune avec NASA (2023 PVGIS, 2025 CAMS)."""
    fin = min(FIN_EXTENSION[ecart.source_comparee], FIN_EXTENSION["nasa_power"])
    codes = [ecart.code_serie(code) for code in _LOCALITES]
    _verifier_series(db_session, codes, fin)


def test_fraction_diffuse_prolongee(db_session: Session) -> None:
    """Fraction diffuse NASA prolongée jusqu'en 2025 aux 142 localités."""
    _verifier_series(
        db_session, [f"fraction_diffuse_nasa_power_{code}" for code in _LOCALITES], 2025
    )


def test_mise_en_garde_era5(db_session: Session) -> None:
    """Le saut ERA5 de 2021 est signalé sur les 568 séries ERA5, et sur elles seules."""
    attendues = {c.code_serie(code) for c in CONTRATS_ERA5.values() for code in _LOCALITES} | {
        e.code_serie(code)
        for e in ECARTS_INTER_SOURCES
        if e.source_comparee == "era5_pvgis"
        for code in _LOCALITES
    }
    assert len(attendues) == 568
    annotees = {
        row.code
        for row in db_session.execute(
            text(
                "SELECT code FROM series_metadonnees "
                "WHERE strpos(note_publique, 'saut probable du produit PVGIS-ERA5 en 2021') > 0"
            )
        ).all()
    }
    assert annotees == attendues
