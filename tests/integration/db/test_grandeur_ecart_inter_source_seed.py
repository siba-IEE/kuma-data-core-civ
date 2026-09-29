"""Tests d'intégration des grandeurs dérivées d'écart inter-source (GHI et DNI).

Écarts inter-source mensuels, matérialisés dans ``grandeurs_metier`` sur la
fenêtre commune 2005-2020, tous référés à NASA POWER (dénominateur commun →
triangulation, ADR-0009 à ADR-0013) :

- ``ecart_relatif_ghi_sarah3_nasa`` (GHI SARAH-3 vs NASA, migration 0011) ;
- ``ecart_relatif_ghi_era5_nasa`` (GHI ERA5 vs NASA, migration 0013) ;
- ``ecart_relatif_ghi_cams_nasa`` (GHI CAMS vs NASA, migration 0015) ;
- ``ecart_relatif_dni_cams_nasa`` (DNI CAMS vs NASA, migration 0016) — premier
  écart DNI ; la référence NASA DNI couvre 2001-2020, la fenêtre commune reste
  2005-2020 ;
- ``ecart_relatif_dni_sarah3_nasa`` (DNI SARAH-3 vs NASA, migration 0019) ;
- ``ecart_relatif_dni_era5_nasa`` (DNI ERA5 vs NASA, migration 0020) ;
- ``ecart_relatif_dhi_cams_nasa`` (DHI CAMS vs NASA, migration 0023) — premier
  écart DHI ; la référence NASA DHI couvre 2001-2020.

Gravés aux 3 pilotes par ces migrations, puis étendus aux 139 localités des lots
nationaux par la migration 0028 (ADR-0017) : **142 localités** au total. Prolongés
au-delà de 2020 par la migration 0032 (ADR-0018), jusqu'à la dernière année
commune avec NASA : 2023 pour SARAH-3 et ERA5, 2025 pour CAMS.

Vérifie, pour chacun, les trois pièges tranchés (classification ``stockee``,
fenêtre commune stricte depuis 2005 / 12 mois par an et par localité, confiance B / statut
brut) et la **fidélité** : la valeur gravée est recalculée indépendamment depuis
les sources brutes (seeds pilotes et CSV des lots, source comparée + NASA POWER
de la même grandeur), même formule ``(x - nasa)/nasa*100``.
"""

from __future__ import annotations

from types import ModuleType
from typing import NamedTuple

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds import series_cams_dhi_mensuel_civ as cams_dhi
from kuma_data_core.db.seeds import series_cams_dni_mensuel_civ as cams_dni
from kuma_data_core.db.seeds import series_cams_ghi_mensuel_civ as cams_ghi
from kuma_data_core.db.seeds import series_nasa_power_dhi_mensuel_civ as np_dhi
from kuma_data_core.db.seeds import series_nasa_power_dni_mensuel_civ as np_dni
from kuma_data_core.db.seeds import series_nasa_power_ghi_mensuel_civ as np_ghi
from kuma_data_core.db.seeds import series_pvgis_era5_dni_mensuel_civ as era5_dni
from kuma_data_core.db.seeds import series_pvgis_era5_ghi_mensuel_civ as era5_ghi
from kuma_data_core.db.seeds import series_pvgis_sarah3_dni_mensuel_civ as sarah3_dni
from kuma_data_core.db.seeds import series_pvgis_sarah3_ghi_mensuel_civ as sarah3_ghi
from kuma_data_core.db.seeds.lots_civ import FIN_EXTENSION
from tests.integration.db.mesures_brutes import mesures_mensuelles

pytestmark = pytest.mark.integration

ANNEE_DEBUT_COMMUN = 2005
# 3 pilotes + 139 localités des lots nationaux (ADR-0017).
_LOCALITES = set(mesures_mensuelles(np_ghi))


def _fin(ecart: Ecart) -> int:
    """Dernière année commune avec NASA : 2023 (SARAH-3, ERA5) ou 2025 (CAMS)."""
    return min(FIN_EXTENSION[ecart.seed_compare.SOURCE_CODE], FIN_EXTENSION["nasa_power"])


def _nb_lignes(ecart: Ecart) -> int:
    return (_fin(ecart) - ANNEE_DEBUT_COMMUN + 1) * 12 * len(_LOCALITES)


class Ecart(NamedTuple):
    """Un écart inter-source : grandeur, préfixe de série, seeds comparé et référence."""

    grandeur_code: str
    prefixe_serie: str
    seed_compare: ModuleType  # source au numérateur (SARAH-3, ERA5 ou CAMS)
    seed_reference: ModuleType  # NASA POWER de la même grandeur brute (dénominateur)


_ECARTS = [
    Ecart("ecart_relatif_ghi_sarah3_nasa", "ecart_ghi_sarah3_nasa", sarah3_ghi, np_ghi),
    Ecart("ecart_relatif_ghi_era5_nasa", "ecart_ghi_era5_nasa", era5_ghi, np_ghi),
    Ecart("ecart_relatif_ghi_cams_nasa", "ecart_ghi_cams_nasa", cams_ghi, np_ghi),
    Ecart("ecart_relatif_dni_cams_nasa", "ecart_dni_cams_nasa", cams_dni, np_dni),
    Ecart("ecart_relatif_dni_sarah3_nasa", "ecart_dni_sarah3_nasa", sarah3_dni, np_dni),
    Ecart("ecart_relatif_dni_era5_nasa", "ecart_dni_era5_nasa", era5_dni, np_dni),
    Ecart("ecart_relatif_dhi_cams_nasa", "ecart_dhi_cams_nasa", cams_dhi, np_dhi),
]


def _id(e: Ecart) -> str:
    return e.grandeur_code


def _mesures_par_localite(seed: ModuleType) -> dict[str, dict[tuple[int, int], float]]:
    """Mesures brutes par localité puis (année, mois) : pilotes + lots nationaux."""
    return mesures_mensuelles(seed)


def _ecart_attendu(ecart: Ecart) -> dict[tuple[str, int, int], float]:
    """Recalcule l'écart attendu (compare - nasa)/nasa*100 sur l'intersection."""
    assert ecart.seed_compare.GRANDEUR_CODE == ecart.seed_reference.GRANDEUR_CODE
    assert ecart.seed_reference.SOURCE_CODE == "nasa_power"
    nasa = _mesures_par_localite(ecart.seed_reference)
    compare = _mesures_par_localite(ecart.seed_compare)
    attendu: dict[tuple[str, int, int], float] = {}
    for loc, compare_mesures in compare.items():
        nasa_mesures = nasa[loc]
        for (annee, mois), v_compare in compare_mesures.items():
            if (annee, mois) in nasa_mesures:
                v_nasa = nasa_mesures[(annee, mois)]
                attendu[(loc, annee, mois)] = (v_compare - v_nasa) / v_nasa * 100.0
    return attendu


@pytest.mark.parametrize("ecart", _ECARTS, ids=_id)
def test_grandeur_referentiel_stockee(db_session: Session, ecart: Ecart) -> None:
    """La grandeur est F1, unité pourcent, et stockee (pas calculee_volee)."""
    row = db_session.execute(
        text(
            """
            SELECT g.famille, g.strategie_calcul, u.code AS unite
            FROM grandeurs_referentiel g
            JOIN unites u ON u.id = g.unite_id
            WHERE g.code = :c
            """
        ),
        {"c": ecart.grandeur_code},
    ).one()
    assert row.famille == "F1"
    assert row.strategie_calcul == "stockee"  # ADR-0009 piège 1 : matérialisée, déterministe
    assert row.unite == "pourcent"


@pytest.mark.parametrize("ecart", _ECARTS, ids=_id)
def test_series_calculees(db_session: Session, ecart: Ecart) -> None:
    """3 séries calculées, source éditoriale kuma_calculs, calcul_derive, granularite NULL."""
    rows = db_session.execute(
        text(
            """
            SELECT s.code, s.methode_collecte, s.granularite, src.code AS source,
                   s.periode_debut, s.periode_fin
            FROM series_metadonnees s
            JOIN sources src ON src.id = s.source_id
            WHERE s.grandeur_code = :c
            """
        ),
        {"c": ecart.grandeur_code},
    ).all()
    assert {r.code for r in rows} == {f"{ecart.prefixe_serie}_{loc}" for loc in _LOCALITES}
    for r in rows:
        assert r.source == "kuma_calculs", r.code
        assert r.methode_collecte == "calcul_derive", r.code
        assert r.granularite is None, r.code
        assert str(r.periode_debut) == "2005-01-01"
        assert str(r.periode_fin) == f"{_fin(ecart)}-12-31"


@pytest.mark.parametrize("ecart", _ECARTS, ids=_id)
def test_completude_et_fenetre_commune(db_session: Session, ecart: Ecart) -> None:
    """Lignes mensuelles strictement sur la fenêtre commune 2005 → fin commune avec NASA."""
    rows = db_session.execute(
        text(
            """
            SELECT gm.annee_debut, gm.annee_fin, gm.mois, gm.periode_type
            FROM grandeurs_metier gm
            WHERE gm.grandeur_code = :c
            """
        ),
        {"c": ecart.grandeur_code},
    ).all()
    assert len(rows) == _nb_lignes(ecart)
    for r in rows:
        assert r.periode_type == "mensuel"
        assert r.annee_debut == r.annee_fin  # ligne mensuelle : année unique
        assert r.mois is not None and 1 <= r.mois <= 12
    annees = {r.annee_debut for r in rows}
    assert annees == set(range(ANNEE_DEBUT_COMMUN, _fin(ecart) + 1))
    # Aucun mois NASA-seul (1991-2004) n'a fui dans l'écart.
    assert min(annees) == ANNEE_DEBUT_COMMUN


@pytest.mark.parametrize("ecart", _ECARTS, ids=_id)
def test_invariants_confiance_statut(db_session: Session, ecart: Ecart) -> None:
    """Toutes les lignes : confiance B dérivée, statut brut, version 1."""
    rows = db_session.execute(
        text(
            """
            SELECT niveau_confiance_derive, statut, version_formule
            FROM grandeurs_metier WHERE grandeur_code = :c
            """
        ),
        {"c": ecart.grandeur_code},
    ).all()
    assert len(rows) == _nb_lignes(ecart)
    for r in rows:
        assert r.niveau_confiance_derive == "B"
        assert r.statut == "brut"
        assert r.version_formule == 1


@pytest.mark.parametrize("ecart", _ECARTS, ids=_id)
def test_valeurs_fideles_au_calcul(db_session: Session, ecart: Ecart) -> None:
    """Chaque écart gravé = recalcul indépendant depuis les deux seeds bruts."""
    attendu = _ecart_attendu(ecart)
    assert len(attendu) == _nb_lignes(ecart)  # les sources brutes elles-mêmes
    rows = db_session.execute(
        text(
            """
            SELECT loc.code AS localite, gm.annee_debut AS annee, gm.mois, gm.valeur
            FROM grandeurs_metier gm
            JOIN localites loc ON loc.id = gm.localite_id
            WHERE gm.grandeur_code = :c
            """
        ),
        {"c": ecart.grandeur_code},
    ).all()
    assert len(rows) == _nb_lignes(ecart)
    for r in rows:
        cle = (r.localite, r.annee, r.mois)
        assert cle in attendu, cle
        assert r.valeur == pytest.approx(attendu[cle]), cle


def test_grandeur_heritee_dni_cams_non_reemployee(db_session: Session) -> None:
    """L'héritée ``ecart_relatif_dni_cams`` (id 27, CAMS au dénominateur) reste vide.

    ADR-0011 : en CIV, NASA POWER est la référence uniforme ; l'écart DNI gravé est
    ``ecart_relatif_dni_cams_nasa`` (id 38), jamais l'héritée d'orientation inverse.
    """
    ids = dict(
        db_session.execute(
            text(
                """
                SELECT code, id FROM grandeurs_referentiel
                WHERE code IN ('ecart_relatif_dni_cams', 'ecart_relatif_dni_cams_nasa')
                """
            )
        ).all()
    )
    assert ids == {"ecart_relatif_dni_cams": 27, "ecart_relatif_dni_cams_nasa": 38}
    for table in ("grandeurs_metier", "series_metadonnees"):
        nb = db_session.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE grandeur_code = 'ecart_relatif_dni_cams'")
        ).scalar_one()
        assert nb == 0, table
