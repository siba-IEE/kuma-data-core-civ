"""Tests d'intégration des séries météo ERA5 du CDS (migration 0036, ADR-0021).

Trois grandeurs (``t2m``, ``vent_10m``, ``precipitation``) aux 142 localités,
1991-2025, source ``ecmwf_era5`` (id 2), méthode ``reanalyse``, confiance B.
Vérifie, par grandeur : contrat et métadonnées, complétude, bornes physiques et
**fidélité intégrale** — chaque mesure en base égale le CSV gzip committé, relu
ici **indépendamment** (``gzip`` + ``csv``, sans ``series_csv``).

Cohérence de l'extraction au point de grille 0,25° le plus proche : deux
localités de la même maille portent exactement la même série, et il y a autant
de séries distinctes que de mailles (110).

Triangulation ERA5 - NASA POWER : ignorée (``skip``) tant que les séries
``nasa_power_<grandeur>_mensuel_<localité>`` ne sont pas en base.
"""

from __future__ import annotations

import csv
import gzip
import math
from collections import defaultdict

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.meteo_civ import CONTRATS_METEO_NASA_MENSUELS
from kuma_data_core.db.seeds.meteo_era5_civ import (
    CONTRATS_METEO_ERA5_MENSUELS,
    LOT_METEO_ERA5,
    VARIABLES_ERA5,
    maille_era5,
)
from kuma_data_core.db.seeds.series_csv import DOSSIER_DONNEES, ContratSerie

pytestmark = pytest.mark.integration

_POINTS = {code: (lat, lon) for code, _, lat, lon in points_nationaux()}
_GRANDEURS = list(CONTRATS_METEO_ERA5_MENSUELS)
_NB_MOIS = 420  # 1991-2025

# Plages physiques plausibles en Côte d'Ivoire (moyennes mensuelles), plus
# étroites que les bornes de sanité du contrat : garde-fou indépendant.
_PLAGES: dict[str, tuple[float, float]] = {
    "t2m": (15.0, 38.0),  # °C
    "vent_10m": (0.3, 10.0),  # m/s
    "precipitation": (0.0, 30.0),  # mm/jour
}


def _contrat(grandeur: str) -> ContratSerie:
    return CONTRATS_METEO_ERA5_MENSUELS[grandeur]


def _codes(grandeur: str) -> list[str]:
    return [_contrat(grandeur).code_serie(code) for code in _POINTS]


def _csv_brut(grandeur: str) -> dict[tuple[str, int, int], tuple[float, float, float]]:
    """``(localité, année, mois) -> (latitude, longitude, valeur)``, lu sans ``series_csv``."""
    chemin = DOSSIER_DONNEES / f"ecmwf_era5_{grandeur}_mensuel_{LOT_METEO_ERA5}.csv.gz"
    sortie: dict[tuple[str, int, int], tuple[float, float, float]] = {}
    with gzip.open(chemin, "rt", encoding="utf-8", newline="") as f:
        lecteur = csv.DictReader(f)
        for r in lecteur:
            cle = (r["localite_code"], int(r["annee"]), int(r["mois"]))
            assert cle not in sortie, cle
            sortie[cle] = (float(r["latitude"]), float(r["longitude"]), float(r["valeur"]))
    return sortie


def test_contrats() -> None:
    """Trois contrats ERA5 (CDS), mêmes conventions que la météo NASA POWER."""
    assert set(_GRANDEURS) == {"t2m", "vent_10m", "precipitation"}
    for grandeur, contrat in CONTRATS_METEO_ERA5_MENSUELS.items():
        assert contrat.source_code == "ecmwf_era5" and contrat.source_id == 2
        assert contrat.methode_collecte == "reanalyse" and contrat.niveau_confiance == "B"
        assert contrat.prefixe_code == f"ecmwf_era5_{grandeur}_mensuel"
        assert (contrat.annee_debut, contrat.annee_fin, contrat.nb_mois) == (1991, 2025, _NB_MOIS)
        assert contrat.granularite == "mensuel"
        # Même borne de sanité que le contrat NASA POWER de la grandeur.
        assert contrat.borne_max == CONTRATS_METEO_NASA_MENSUELS[grandeur].borne_max


def test_conversions() -> None:
    """Conversions affines documentées : K → °C, m/jour → mm/jour, vent inchangé."""
    assert math.isclose(VARIABLES_ERA5["t2m"].convertir(273.15), 0.0, abs_tol=1e-12)
    assert math.isclose(VARIABLES_ERA5["precipitation"].convertir(0.0052), 5.2)
    assert VARIABLES_ERA5["vent_10m"].convertir(2.5) == 2.5


def test_mailles() -> None:
    """142 localités, 110 mailles 0,25° ; chaque nœud à moins d'un demi-pas du point."""
    assert len(_POINTS) == 142
    mailles = {code: maille_era5(lat, lon) for code, (lat, lon) in _POINTS.items()}
    assert len(set(mailles.values())) == 110
    for code, (lat_n, lon_n) in mailles.items():
        lat, lon = _POINTS[code]
        assert abs(lat - lat_n) < 0.125 and abs(lon - lon_n) < 0.125, code
        assert (lat_n * 4).is_integer() and (lon_n * 4).is_integer(), code
    with pytest.raises(ValueError):
        maille_era5(5.125, -4.0)  # à égale distance de deux nœuds : refusé


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_series_metadonnees(db_session: Session, grandeur: str) -> None:
    """Une série par localité, source/grandeur/méthode/période du contrat, note publique."""
    contrat = _contrat(grandeur)
    rows = db_session.execute(
        text(
            """
            SELECT s.code, s.libelle, s.grandeur_code, s.methode_collecte, s.granularite,
                   s.periode_debut, s.periode_fin, s.note_publique, s.actif,
                   src.code AS source, loc.code AS localite, u.code AS unite
            FROM series_metadonnees s
            JOIN sources src ON src.id = s.source_id
            JOIN localites loc ON loc.id = s.localite_id
            JOIN grandeurs_referentiel g ON g.code = s.grandeur_code
            JOIN unites u ON u.id = g.unite_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": _codes(grandeur)},
    ).all()
    assert {r.localite for r in rows} == set(_POINTS)
    assert len(rows) == 142
    for r in rows:
        assert r.code == contrat.code_serie(r.localite)
        assert r.source == "ecmwf_era5" and r.grandeur_code == grandeur and r.actif
        assert r.methode_collecte == "reanalyse" and r.granularite == "mensuel"
        assert (str(r.periode_debut), str(r.periode_fin)) == ("1991-01-01", "2025-12-31")
        assert r.unite == VARIABLES_ERA5[grandeur].unite_referentiel
        assert r.libelle.startswith(f"{VARIABLES_ERA5[grandeur].libelle} mensuel ERA5 (CDS) — ")
        assert r.libelle.endswith("(1991-2025)")
        assert "ADR-0021" in r.note_publique
        assert "Copernicus Climate Change Service" in r.note_publique  # attribution
        assert "saut" not in r.note_publique  # aucun saut constaté sur ces grandeurs


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_completude(db_session: Session, grandeur: str) -> None:
    """420 mois distincts par série, 12 mois par an, 1991-2025, sans trou."""
    rows = db_session.execute(
        text(
            """
            SELECT s.code, COUNT(*) AS n, COUNT(DISTINCT (m.annee, m.mois)) AS distincts,
                   MIN(m.annee) AS debut, MAX(m.annee) AS fin,
                   MIN(m.mois) AS mois_min, MAX(m.mois) AS mois_max
            FROM mesures_ressource_mensuelles m
            JOIN series_metadonnees s ON s.id = m.serie_id
            WHERE s.code = ANY(:c)
            GROUP BY s.code
            """
        ),
        {"c": _codes(grandeur)},
    ).all()
    assert len(rows) == 142
    for r in rows:
        assert r.n == r.distincts == _NB_MOIS, r.code
        assert (r.debut, r.fin, r.mois_min, r.mois_max) == (1991, 2025, 1, 12), r.code


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_mesures_fideles_au_csv(db_session: Session, grandeur: str) -> None:
    """Chaque mesure en base = CSV committé, relu indépendamment ; brut, confiance B."""
    attendu = _csv_brut(grandeur)
    assert len(attendu) == 142 * _NB_MOIS
    for (code, _, _), (lat, lon, _) in attendu.items():
        assert (lat, lon) == _POINTS[code], code  # coordonnées du référentiel
    contrat = _contrat(grandeur)
    rows = db_session.execute(
        text(
            """
            SELECT loc.code AS localite, m.annee, m.mois, m.valeur, m.statut,
                   m.niveau_confiance_derive
            FROM mesures_ressource_mensuelles m
            JOIN series_metadonnees s ON s.id = m.serie_id
            JOIN localites loc ON loc.id = s.localite_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": _codes(grandeur)},
    ).all()
    assert len(rows) == len(attendu)
    for r in rows:
        assert r.valeur == attendu[(r.localite, r.annee, r.mois)][2], (r.localite, r.annee, r.mois)
        assert r.statut == "brut" and r.niveau_confiance_derive == contrat.niveau_confiance


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_bornes_et_coherence_par_maille(db_session: Session, grandeur: str) -> None:
    """Valeurs dans les plages physiques ; une maille = une série, 110 séries distinctes."""
    rows = db_session.execute(
        text(
            """
            SELECT loc.code AS localite, m.annee, m.mois, m.valeur
            FROM mesures_ressource_mensuelles m
            JOIN series_metadonnees s ON s.id = m.serie_id
            JOIN localites loc ON loc.id = s.localite_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": _codes(grandeur)},
    ).all()
    bas, haut = _PLAGES[grandeur]
    hors_plage = [
        (r.localite, r.annee, r.mois, r.valeur) for r in rows if not bas <= r.valeur <= haut
    ]
    assert not hors_plage, hors_plage[:5]
    series: dict[str, dict[tuple[int, int], float]] = defaultdict(dict)
    for r in rows:
        series[r.localite][(r.annee, r.mois)] = r.valeur
    par_maille: dict[tuple[float, float], set[tuple[tuple[tuple[int, int], float], ...]]] = (
        defaultdict(set)
    )
    for code, valeurs in series.items():
        par_maille[maille_era5(*_POINTS[code])].add(tuple(sorted(valeurs.items())))
    assert all(len(v) == 1 for v in par_maille.values())  # même maille, même série
    assert len({next(iter(v)) for v in par_maille.values()}) == len(par_maille) == 110


@pytest.mark.parametrize("grandeur", _GRANDEURS)
def test_triangulation_era5_nasa(db_session: Session, grandeur: str) -> None:
    """ERA5 - NASA POWER sur la fenêtre commune : appariement complet, écarts plausibles.

    Garde-fou de cohérence, pas une validation : deux réanalyses (ERA5, MERRA-2)
    ne sont pas une vérité sol. Seuils larges autour des constats de l'ADR-0021
    (T2M de -0,5 à +1,6 °C par localité ; vent de -45 à +101 % ; pluie de -31 à
    +52 %).
    """
    nasa = CONTRATS_METEO_NASA_MENSUELS[grandeur]
    codes_nasa = [nasa.code_serie(code) for code in _POINTS]
    present = db_session.execute(
        text(
            "SELECT COUNT(*) FROM series_metadonnees WHERE code = ANY(:c) "
            "AND granularite = 'mensuel'"
        ),
        {"c": codes_nasa},
    ).scalar_one()
    if present == 0:
        pytest.skip(f"Séries NASA POWER {nasa.prefixe_code}_* absentes de la base.")
    assert present == 142
    rows = db_session.execute(
        text(
            """
            SELECT loc.code AS localite, src.code AS source, m.annee, m.mois, m.valeur
            FROM mesures_ressource_mensuelles m
            JOIN series_metadonnees s ON s.id = m.serie_id
            JOIN sources src ON src.id = s.source_id
            JOIN localites loc ON loc.id = s.localite_id
            WHERE s.code = ANY(:c) AND m.annee BETWEEN 1991 AND 2025
            """
        ),
        {"c": _codes(grandeur) + codes_nasa},
    ).all()
    valeurs: dict[str, dict[str, dict[tuple[int, int], float]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for r in rows:
        valeurs[r.source][r.localite][(r.annee, r.mois)] = r.valeur
    ecarts: list[float] = []
    for code in _POINTS:
        era5, nasa_loc = valeurs["ecmwf_era5"][code], valeurs["nasa_power"][code]
        assert set(era5) == set(nasa_loc), code  # fenêtre commune complète
        m_era5 = math.fsum(era5.values()) / len(era5)
        m_nasa = math.fsum(nasa_loc.values()) / len(nasa_loc)
        ecart = m_era5 - m_nasa if grandeur == "t2m" else (m_era5 / m_nasa - 1) * 100
        ecarts.append(ecart)
        bas, haut = {"t2m": (-3.0, 3.0), "vent_10m": (-70.0, 150.0)}.get(grandeur, (-70.0, 100.0))
        assert bas <= ecart <= haut, (code, ecart)
    if grandeur == "t2m":
        assert abs(math.fsum(ecarts) / len(ecarts)) < 1.0  # +0,27 °C en moyenne (ADR-0021)
