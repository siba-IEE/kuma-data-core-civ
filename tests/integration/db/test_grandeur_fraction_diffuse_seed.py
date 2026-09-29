"""Tests d'intégration de la grandeur ``fraction_diffuse`` (migration 0024, ADR-0014).

Fraction diffuse DHI/GHI NASA POWER aux 3 points, mensuelle et annuelle
2001-2020 (couverture du DHI NASA), matérialisée dans ``grandeurs_metier``.
Vérifie le contrat (grandeur ``stockee`` sans dimension, séries
``calcul_derive`` de ``kuma_calculs``), la
complétude (720 mensuelles, 60 annuelles), le domaine physique [0, 1] et la
**fidélité** : chaque valeur gravée est recalculée indépendamment depuis les
seeds bruts NASA (DHI 0021, GHI 0008) — ``Σ DHI / Σ GHI`` sur les jours de la
période, reconstruit depuis les moyennes journalières mensuelles.
"""

from __future__ import annotations

import calendar
from types import ModuleType

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds import series_nasa_power_dhi_mensuel_civ as np_dhi
from kuma_data_core.db.seeds import series_nasa_power_ghi_mensuel_civ as np_ghi

pytestmark = pytest.mark.integration

GRANDEUR_CODE = "fraction_diffuse"
NB_MENSUEL = 720  # 240 mois x 3 points
NB_ANNUEL = 60  # 20 ans x 3 points
_LOCALITES = {s["localite_code"] for s in np_ghi.SERIES}


def _par_localite(seed: ModuleType) -> dict[str, dict[tuple[int, int], float]]:
    return {s["localite_code"]: {(a, m): v for a, m, v in s["mesures"]} for s in seed.SERIES}


def _attendu() -> tuple[dict[tuple[str, int, int], float], dict[tuple[str, int], float]]:
    """Recalcule mensuel (moy DHI / moy GHI) et annuel (pondéré par les jours).

    Intersection des deux seeds : le DHI NASA couvre 2001-2020, le GHI 1991-2020.
    """
    dhi, ghi = _par_localite(np_dhi), _par_localite(np_ghi)
    mensuel: dict[tuple[str, int, int], float] = {}
    annuel: dict[tuple[str, int], float] = {}
    for loc, dhi_loc in dhi.items():
        sommes: dict[int, list[float]] = {}
        for (annee, mois), v_dhi in dhi_loc.items():
            v_ghi = ghi[loc][(annee, mois)]
            mensuel[(loc, annee, mois)] = v_dhi / v_ghi
            n = calendar.monthrange(annee, mois)[1]
            s = sommes.setdefault(annee, [0.0, 0.0, 0.0])
            s[0] += v_dhi * n
            s[1] += v_ghi * n
            s[2] += 1
        for annee, (s_dhi, s_ghi, nb_mois) in sommes.items():
            assert nb_mois == 12
            annuel[(loc, annee)] = s_dhi / s_ghi
    return mensuel, annuel


def test_grandeur_referentiel(db_session: Session) -> None:
    """Grandeur seedée en 0002 : id 3, F1, stockee, sans dimension."""
    row = db_session.execute(
        text(
            """
            SELECT g.id, g.famille, g.strategie_calcul, u.code AS unite
            FROM grandeurs_referentiel g JOIN unites u ON u.id = g.unite_id
            WHERE g.code = :c
            """
        ),
        {"c": GRANDEUR_CODE},
    ).one()
    assert (row.id, row.famille, row.strategie_calcul, row.unite) == (
        3,
        "F1",
        "stockee",
        "sans_unite",
    )


def test_series_calculees(db_session: Session) -> None:
    """3 séries calcul_derive, source kuma_calculs, période 2001-2020."""
    rows = db_session.execute(
        text(
            """
            SELECT s.code, s.methode_collecte, s.granularite, src.code AS source,
                   s.periode_debut, s.periode_fin
            FROM series_metadonnees s JOIN sources src ON src.id = s.source_id
            WHERE s.grandeur_code = :c
            """
        ),
        {"c": GRANDEUR_CODE},
    ).all()
    assert {r.code for r in rows} == {f"fraction_diffuse_nasa_power_{loc}" for loc in _LOCALITES}
    for r in rows:
        assert r.source == "kuma_calculs" and r.methode_collecte == "calcul_derive"
        assert r.granularite is None
        assert str(r.periode_debut) == "2001-01-01" and str(r.periode_fin) == "2020-12-31"


def test_completude_domaine_confiance(db_session: Session) -> None:
    """720 mensuelles + 60 annuelles, valeurs dans [0, 1], confiance B, statut brut."""
    rows = db_session.execute(
        text(
            """
            SELECT periode_type, mois, valeur, niveau_confiance_derive, statut,
                   version_formule, annee_debut, annee_fin
            FROM grandeurs_metier WHERE grandeur_code = :c
            """
        ),
        {"c": GRANDEUR_CODE},
    ).all()
    assert sum(r.periode_type == "mensuel" for r in rows) == NB_MENSUEL
    assert sum(r.periode_type == "annuel" for r in rows) == NB_ANNUEL
    for r in rows:
        assert 0.0 <= r.valeur <= 1.0
        assert r.niveau_confiance_derive == "B" and r.statut == "brut"
        assert r.version_formule == 1 and r.annee_debut == r.annee_fin
        assert (r.mois is None) == (r.periode_type == "annuel")
    assert {r.annee_debut for r in rows} == set(range(2001, 2021))


def test_valeurs_fideles_au_calcul(db_session: Session) -> None:
    """Chaque valeur gravée = recalcul indépendant depuis les seeds NASA DHI et GHI."""
    mensuel, annuel = _attendu()
    assert len(mensuel) == NB_MENSUEL and len(annuel) == NB_ANNUEL
    rows = db_session.execute(
        text(
            """
            SELECT loc.code AS localite, gm.periode_type, gm.annee_debut AS annee,
                   gm.mois, gm.valeur
            FROM grandeurs_metier gm JOIN localites loc ON loc.id = gm.localite_id
            WHERE gm.grandeur_code = :c
            """
        ),
        {"c": GRANDEUR_CODE},
    ).all()
    for r in rows:
        if r.periode_type == "mensuel":
            attendu = mensuel[(r.localite, r.annee, r.mois)]
        else:
            attendu = annuel[(r.localite, r.annee)]
        assert r.valeur == pytest.approx(attendu), (r.localite, r.annee, r.mois)
