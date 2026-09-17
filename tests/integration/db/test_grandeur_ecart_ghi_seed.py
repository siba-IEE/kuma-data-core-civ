"""Tests d'intégration de la grandeur dérivée d'écart inter-source (migration 0011).

Première grandeur calculée de l'instance CIV : écart relatif du GHI mensuel
entre SARAH-3/PVGIS et NASA POWER, ``(sarah3 - nasa) / nasa * 100``, matérialisé
dans ``grandeurs_metier`` sur la fenêtre commune 2005-2020 (ADR-0009).

Vérifie les trois pièges tranchés :
- **classification** ``strategie_calcul='stockee'`` (pas ``calculee_volee``) ;
- **fenêtre commune** stricte 2005-2020, 576 lignes, pas de mois hors
  intersection ;
- **confiance** dérivée B, statut brut.
Et la **fidélité** : la valeur gravée est recalculée indépendamment depuis les
deux seeds bruts (NASA GHI + SARAH-3 GHI).
"""

from __future__ import annotations

from types import ModuleType

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds import series_nasa_power_ghi_mensuel_civ as np_ghi
from kuma_data_core.db.seeds import series_pvgis_sarah3_ghi_mensuel_civ as sarah3_ghi

pytestmark = pytest.mark.integration

GRANDEUR_CODE = "ecart_relatif_ghi_sarah3_nasa"
CODES_SERIES = (
    "ecart_ghi_sarah3_nasa_civ_dep_abidjan",
    "ecart_ghi_sarah3_nasa_civ_dep_yamoussoukro",
    "ecart_ghi_sarah3_nasa_civ_dep_korhogo",
)
ANNEE_DEBUT_COMMUN = 2005
ANNEE_FIN_COMMUN = 2020
NB_LIGNES_ATTENDU = 576  # 192 mois * 3 points


def _mesures_par_localite(seed: ModuleType) -> dict[str, dict[tuple[int, int], float]]:
    """Indexe les mesures d'un seed brut par localité puis (année, mois)."""
    out: dict[str, dict[tuple[int, int], float]] = {}
    for s in seed.SERIES:
        out[s["localite_code"]] = {(a, m): v for a, m, v in s["mesures"]}
    return out


def _ecart_attendu() -> dict[tuple[str, int, int], float]:
    """Recalcule l'écart attendu depuis les deux seeds, sur l'intersection."""
    nasa = _mesures_par_localite(np_ghi)
    sarah = _mesures_par_localite(sarah3_ghi)
    attendu: dict[tuple[str, int, int], float] = {}
    for loc, sarah_mesures in sarah.items():
        nasa_mesures = nasa[loc]
        for (annee, mois), v_sarah in sarah_mesures.items():
            if (annee, mois) in nasa_mesures:
                v_nasa = nasa_mesures[(annee, mois)]
                attendu[(loc, annee, mois)] = (v_sarah - v_nasa) / v_nasa * 100.0
    return attendu


def test_grandeur_referentiel_stockee(db_session: Session) -> None:
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
        {"c": GRANDEUR_CODE},
    ).one()
    assert row.famille == "F1"
    assert row.strategie_calcul == "stockee"  # ADR-0009 piège 1 : matérialisée, déterministe
    assert row.unite == "pourcent"


def test_series_calculees(db_session: Session) -> None:
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
        {"c": GRANDEUR_CODE},
    ).all()
    assert {r.code for r in rows} == set(CODES_SERIES)
    for r in rows:
        assert r.source == "kuma_calculs", r.code
        assert r.methode_collecte == "calcul_derive", r.code
        assert r.granularite is None, r.code
        assert str(r.periode_debut) == "2005-01-01" and str(r.periode_fin) == "2020-12-31"


def test_completude_et_fenetre_commune(db_session: Session) -> None:
    """576 lignes mensuelles, strictement sur la fenêtre commune 2005-2020."""
    rows = db_session.execute(
        text(
            """
            SELECT gm.annee_debut, gm.annee_fin, gm.mois, gm.periode_type
            FROM grandeurs_metier gm
            WHERE gm.grandeur_code = :c
            """
        ),
        {"c": GRANDEUR_CODE},
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


def test_invariants_confiance_statut(db_session: Session) -> None:
    """Toutes les lignes : confiance B dérivée, statut brut, version 1."""
    rows = db_session.execute(
        text(
            """
            SELECT niveau_confiance_derive, statut, version_formule
            FROM grandeurs_metier WHERE grandeur_code = :c
            """
        ),
        {"c": GRANDEUR_CODE},
    ).all()
    assert len(rows) == NB_LIGNES_ATTENDU
    for r in rows:
        assert r.niveau_confiance_derive == "B"
        assert r.statut == "brut"
        assert r.version_formule == 1


def test_valeurs_fideles_au_calcul(db_session: Session) -> None:
    """Chaque écart gravé = recalcul indépendant depuis les deux seeds bruts."""
    attendu = _ecart_attendu()
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
        {"c": GRANDEUR_CODE},
    ).all()
    assert len(rows) == NB_LIGNES_ATTENDU
    for r in rows:
        cle = (r.localite, r.annee, r.mois)
        assert cle in attendu, cle
        assert r.valeur == pytest.approx(attendu[cle]), cle
