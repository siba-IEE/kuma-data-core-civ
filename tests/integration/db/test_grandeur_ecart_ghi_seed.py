"""Tests d'intégration des grandeurs dérivées d'écart inter-source GHI.

Deux écarts inter-source du GHI mensuel, matérialisés dans ``grandeurs_metier``
sur la fenêtre commune 2005-2020, tous deux référés à NASA POWER (dénominateur
commun → triangulation, ADR-0009 et ADR-0010) :

- ``ecart_relatif_ghi_sarah3_nasa`` (SARAH-3 vs NASA, migration 0011) ;
- ``ecart_relatif_ghi_era5_nasa`` (ERA5 vs NASA, migration 0013).

Vérifie, pour chacun, les trois pièges tranchés (classification ``stockee``,
fenêtre commune stricte 2005-2020 / 576 lignes, confiance B / statut brut) et la
**fidélité** : la valeur gravée est recalculée indépendamment depuis les deux
seeds bruts (source comparée + NASA POWER), même formule ``(x - nasa)/nasa*100``.
"""

from __future__ import annotations

from types import ModuleType
from typing import NamedTuple

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds import series_nasa_power_ghi_mensuel_civ as np_ghi
from kuma_data_core.db.seeds import series_pvgis_era5_ghi_mensuel_civ as era5_ghi
from kuma_data_core.db.seeds import series_pvgis_sarah3_ghi_mensuel_civ as sarah3_ghi

pytestmark = pytest.mark.integration

ANNEE_DEBUT_COMMUN = 2005
ANNEE_FIN_COMMUN = 2020
NB_LIGNES_ATTENDU = 576  # 192 mois * 3 points
_LOCALITES = {s["localite_code"] for s in np_ghi.SERIES}  # les 3 points (référence commune)


class Ecart(NamedTuple):
    """Un écart inter-source : grandeur, préfixe de série, seed de la source comparée."""

    grandeur_code: str
    prefixe_serie: str
    seed_compare: ModuleType  # source au numérateur (SARAH-3 ou ERA5)


_ECARTS = [
    Ecart("ecart_relatif_ghi_sarah3_nasa", "ecart_ghi_sarah3_nasa", sarah3_ghi),
    Ecart("ecart_relatif_ghi_era5_nasa", "ecart_ghi_era5_nasa", era5_ghi),
]


def _id(e: Ecart) -> str:
    return e.grandeur_code


def _mesures_par_localite(seed: ModuleType) -> dict[str, dict[tuple[int, int], float]]:
    """Indexe les mesures d'un seed brut par localité puis (année, mois)."""
    out: dict[str, dict[tuple[int, int], float]] = {}
    for s in seed.SERIES:
        out[s["localite_code"]] = {(a, m): v for a, m, v in s["mesures"]}
    return out


def _ecart_attendu(seed_compare: ModuleType) -> dict[tuple[str, int, int], float]:
    """Recalcule l'écart attendu (compare - nasa)/nasa*100 sur l'intersection."""
    nasa = _mesures_par_localite(np_ghi)
    compare = _mesures_par_localite(seed_compare)
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
        assert str(r.periode_debut) == "2005-01-01" and str(r.periode_fin) == "2020-12-31"


@pytest.mark.parametrize("ecart", _ECARTS, ids=_id)
def test_completude_et_fenetre_commune(db_session: Session, ecart: Ecart) -> None:
    """576 lignes mensuelles, strictement sur la fenêtre commune 2005-2020."""
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
    assert len(rows) == NB_LIGNES_ATTENDU
    for r in rows:
        assert r.periode_type == "mensuel"
        assert r.annee_debut == r.annee_fin  # ligne mensuelle : année unique
        assert r.mois is not None and 1 <= r.mois <= 12
    annees = {r.annee_debut for r in rows}
    assert annees == set(range(ANNEE_DEBUT_COMMUN, ANNEE_FIN_COMMUN + 1))
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
    assert len(rows) == NB_LIGNES_ATTENDU
    for r in rows:
        assert r.niveau_confiance_derive == "B"
        assert r.statut == "brut"
        assert r.version_formule == 1


@pytest.mark.parametrize("ecart", _ECARTS, ids=_id)
def test_valeurs_fideles_au_calcul(db_session: Session, ecart: Ecart) -> None:
    """Chaque écart gravé = recalcul indépendant depuis les deux seeds bruts."""
    attendu = _ecart_attendu(ecart.seed_compare)
    assert len(attendu) == NB_LIGNES_ATTENDU  # les seeds eux-mêmes donnent 576
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
    assert len(rows) == NB_LIGNES_ATTENDU
    for r in rows:
        cle = (r.localite, r.annee, r.mois)
        assert cle in attendu, cle
        assert r.valeur == pytest.approx(attendu[cle]), cle
