"""Tests d'intégration de la grandeur ``kt`` (indice de clarté, migration 0041).

Indice de clarté ``kt = Σ GHI / Σ H0`` aux **142 localités**, pour les 4
sources de GHI mensuel (ADR-0026) : NASA POWER 1991-2025, CAMS 2005-2025,
SARAH-3 et ERA5 2005-2023, mensuel et annuel, matérialisé dans
``grandeurs_metier``. Vérifie le contrat (grandeur ``stockee`` sans dimension,
séries ``calcul_derive`` de ``kuma_calculs``, mise en garde ERA5), la
complétude (13 lignes par année et par série), le domaine ``0 < kt < 1`` et la
**fidélité** : chaque valeur gravée est recalculée indépendamment, depuis les
sources brutes (seeds pilotes, CSV des lots et de l'extension) et la latitude
du référentiel, avec un ``H0`` reconstruit par pvlib (déclinaison et
excentricité de Spencer 1971) — sans passer par ``services/grandeurs/kt.py``.
"""

from __future__ import annotations

import calendar
from functools import cache
from types import ModuleType
from typing import NamedTuple

import numpy as np
import pvlib  # type: ignore[import-untyped]
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds import series_cams_ghi_mensuel_civ as cams_ghi
from kuma_data_core.db.seeds import series_nasa_power_ghi_mensuel_civ as np_ghi
from kuma_data_core.db.seeds import series_pvgis_era5_ghi_mensuel_civ as era5_ghi
from kuma_data_core.db.seeds import series_pvgis_sarah3_ghi_mensuel_civ as sarah3_ghi
from kuma_data_core.db.seeds.lots_civ import points_nationaux
from tests.integration.db.mesures_brutes import mesures_mensuelles

pytestmark = pytest.mark.integration

GRANDEUR_CODE = "kt"
CONSTANTE_SOLAIRE = 1361.0  # W/m², fiche kt.md § 5


class Source(NamedTuple):
    seed: ModuleType
    jeton: str
    debut: int
    fin: int


SOURCES: tuple[Source, ...] = (
    Source(np_ghi, "nasa_power", 1991, 2025),
    Source(cams_ghi, "cams", 2005, 2025),
    Source(sarah3_ghi, "sarah3", 2005, 2023),
    Source(era5_ghi, "era5", 2005, 2023),
)
LATITUDES: dict[str, float] = {code: lat for code, _, lat, _ in points_nationaux()}
NB_MENSUEL = sum(12 * (s.fin - s.debut + 1) for s in SOURCES) * len(LATITUDES)
NB_ANNUEL = sum(s.fin - s.debut + 1 for s in SOURCES) * len(LATITUDES)


@cache
def _h0_mois(latitude: float, bissextile: bool) -> tuple[float, ...]:
    """Σ H0 journaliers (kWh/m²) de chaque mois, recalculés avec pvlib (Spencer 1971)."""
    annee = 2024 if bissextile else 2023
    rangs = np.arange(1, (366 if bissextile else 365) + 1)
    delta = pvlib.solarposition.declination_spencer71(rangs)
    g_on = pvlib.irradiance.get_extra_radiation(
        rangs, solar_constant=CONSTANTE_SOLAIRE, method="spencer"
    )
    phi = np.radians(latitude)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(delta), -1.0, 1.0))
    h0 = (
        24.0
        / np.pi
        * g_on
        * (np.cos(phi) * np.cos(delta) * np.sin(ws) + ws * np.sin(phi) * np.sin(delta))
        / 1000.0
    )
    bornes = np.cumsum([0] + [calendar.monthrange(annee, m)[1] for m in range(1, 13)])
    return tuple(float(h0[bornes[m] : bornes[m + 1]].sum()) for m in range(12))


def _attendu(
    source: Source,
) -> tuple[dict[tuple[str, int, int], float], dict[tuple[str, int], float]]:
    """kt mensuel (GHI·n / Σ H0) et annuel (Σ GHI·n / Σ H0), depuis les sources brutes."""
    mensuel: dict[tuple[str, int, int], float] = {}
    annuel: dict[tuple[str, int], float] = {}
    for loc, ghi_loc in mesures_mensuelles(source.seed).items():
        sommes: dict[int, list[float]] = {}
        for (annee, mois), ghi in ghi_loc.items():
            h0 = _h0_mois(LATITUDES[loc], calendar.isleap(annee))[mois - 1]
            n = calendar.monthrange(annee, mois)[1]
            mensuel[(loc, annee, mois)] = ghi * n / h0
            s = sommes.setdefault(annee, [0.0, 0.0, 0])
            s[0] += ghi * n
            s[1] += h0
            s[2] += 1
        for annee, (s_ghi, s_h0, nb_mois) in sommes.items():
            assert nb_mois == 12
            annuel[(loc, annee)] = s_ghi / s_h0
    return mensuel, annuel


def test_grandeur_referentiel(db_session: Session) -> None:
    """Grandeur seedée en 0002 : id 2, F1, stockee, sans dimension."""
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
        2,
        "F1",
        "stockee",
        "sans_unite",
    )


def test_latitudes_du_referentiel(db_session: Session) -> None:
    """La latitude lue en base par la migration est celle du seed des localités."""
    rows = db_session.execute(
        text("SELECT code, latitude FROM localites WHERE code = ANY(:c)"),
        {"c": list(LATITUDES)},
    ).all()
    assert len(LATITUDES) == len(rows) == 142
    for r in rows:
        assert float(r.latitude) == pytest.approx(LATITUDES[r.code], abs=1e-8), r.code


def test_series_calculees(db_session: Session) -> None:
    """568 séries calcul_derive de kuma_calculs, périodes par source, mise en garde ERA5."""
    rows = db_session.execute(
        text(
            """
            SELECT s.code, s.libelle, s.methode_collecte, s.granularite, src.code AS source,
                   s.periode_debut, s.periode_fin, s.note_publique, l.code AS localite
            FROM series_metadonnees s JOIN sources src ON src.id = s.source_id
            JOIN localites l ON l.id = s.localite_id
            WHERE s.grandeur_code = :c
            """
        ),
        {"c": GRANDEUR_CODE},
    ).all()
    periodes = {f"kt_{s.jeton}_{loc}": (s.debut, s.fin) for s in SOURCES for loc in LATITUDES}
    assert len(periodes) == 568
    assert {r.code for r in rows} == set(periodes)
    # Phrase de mise en garde portée par la série brute GHI ERA5 (migration 0033).
    note_era5 = db_session.execute(
        text("SELECT note_publique FROM series_metadonnees WHERE code = :c"),
        {"c": "era5_ghi_mensuel_civ_dep_abidjan"},
    ).scalar_one()
    caveat = note_era5[note_era5.index(" Mise en garde : ") :]
    for r in rows:
        debut, fin = periodes[r.code]
        assert r.source == "kuma_calculs" and r.methode_collecte == "calcul_derive"
        assert r.granularite is None and r.code.endswith(f"_{r.localite}")
        assert (str(r.periode_debut), str(r.periode_fin)) == (f"{debut}-01-01", f"{fin}-12-31")
        assert r.libelle.startswith("Indice de clarté ") and r.libelle.endswith(f"({debut}-{fin})")
        assert "ADR-0026" in r.note_publique and "1361 W/m²" in r.note_publique
        if r.code.startswith("kt_era5_"):
            assert r.note_publique.endswith(caveat), r.code
        else:
            assert "Mise en garde" not in r.note_publique, r.code


def test_completude_domaine_confiance(db_session: Session) -> None:
    """13 lignes par année et par série, 0 < kt < 1, confiance B, statut brut, version 1."""
    rows = db_session.execute(
        text(
            """
            SELECT s.code, gm.periode_type, gm.mois, gm.valeur, gm.niveau_confiance_derive,
                   gm.statut, gm.version_formule, gm.annee_debut, gm.annee_fin,
                   gm.localite_id = s.localite_id AS meme_localite
            FROM grandeurs_metier gm JOIN series_metadonnees s ON s.id = gm.series_metadonnees_id
            WHERE gm.grandeur_code = :c
            """
        ),
        {"c": GRANDEUR_CODE},
    ).all()
    assert sum(r.periode_type == "mensuel" for r in rows) == NB_MENSUEL == 160_176
    assert sum(r.periode_type == "annuel" for r in rows) == NB_ANNUEL == 13_348
    par_serie: dict[str, set[tuple[int, int | None]]] = {}
    for r in rows:
        assert 0.0 < r.valeur < 1.0, r.code
        assert r.niveau_confiance_derive == "B" and r.statut == "brut"
        assert r.version_formule == 1 and r.annee_debut == r.annee_fin and r.meme_localite
        assert (r.mois is None) == (r.periode_type == "annuel")
        par_serie.setdefault(r.code, set()).add((r.annee_debut, r.mois))
    for s in SOURCES:
        attendu = {(a, m) for a in range(s.debut, s.fin + 1) for m in [*range(1, 13), None]}
        for loc in LATITUDES:
            assert par_serie[f"kt_{s.jeton}_{loc}"] == attendu


@pytest.mark.parametrize("source", SOURCES, ids=lambda s: s.jeton)
def test_valeurs_fideles_au_calcul(db_session: Session, source: Source) -> None:
    """Chaque valeur gravée = recalcul indépendant (GHI brut, latitude, H0 pvlib)."""
    mensuel, annuel = _attendu(source)
    nb_annees = source.fin - source.debut + 1
    assert len(mensuel) == 142 * 12 * nb_annees and len(annuel) == 142 * nb_annees
    rows = db_session.execute(
        text(
            """
            SELECT loc.code AS localite, gm.periode_type, gm.annee_debut AS annee,
                   gm.mois, gm.valeur
            FROM grandeurs_metier gm JOIN localites loc ON loc.id = gm.localite_id
            JOIN series_metadonnees s ON s.id = gm.series_metadonnees_id
            WHERE gm.grandeur_code = :c AND s.code LIKE :prefixe
            """
        ),
        {"c": GRANDEUR_CODE, "prefixe": f"kt\\_{source.jeton}\\_%"},
    ).all()
    assert len(rows) == len(mensuel) + len(annuel)
    for r in rows:
        if r.periode_type == "mensuel":
            attendu = mensuel[(r.localite, r.annee, r.mois)]
        else:
            attendu = annuel[(r.localite, r.annee)]
        assert r.valeur == pytest.approx(attendu, rel=1e-9), (r.localite, r.annee, r.mois)
