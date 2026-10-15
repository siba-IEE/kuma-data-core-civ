"""Tests d'intégration de la grandeur ``humidex`` (migration 0045, ADR-0030).

Humidex moyen (Masterton & Richardson 1979, constantes de Magnus de la fiche)
aux **34 localités** du journalier NASA POWER (3 pilotes + 31 régions,
ADR-0016), 1991-2025, matérialisé dans ``grandeurs_metier`` depuis la T2M et la
RH2M journalières (migration 0035, ADR-0020). Vérifie le contrat (grandeur
``stockee`` en °C, séries ``calcul_derive`` de ``kuma_calculs``, mensuel et
annuel), la complétude (420 mois et 35 ans par localité), le domaine et la
**fidélité** : chaque valeur gravée est recalculée indépendamment depuis les CSV
journaliers committés — humidex jour par jour, puis moyenne des jours du mois ou
de l'année — et coïncide avec la fonction pure du service hérité ; une série se
lit par l'API. Fige enfin les chiffres de la mise en garde 2024-2025 (note
publique) et les constats de l'ADR. Requêtes limitées aux 34 localités : l'humidex
des 108 départements (migration 0049, ADR-0031) a ses propres tests.
"""

from __future__ import annotations

import calendar
import math
import statistics
from collections import Counter, defaultdict
from datetime import date
from functools import cache

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds.lots_civ import points_journalier
from kuma_data_core.db.seeds.meteo_civ import CONTRATS_METEO_NASA_JOURNALIERS, LOT_METEO_JOURNALIER
from kuma_data_core.db.seeds.series_csv import lire_series_journalieres
from kuma_data_core.services.grandeurs.humidex import _agreger_humidex

pytestmark = pytest.mark.integration

GRANDEUR_CODE = "humidex"
_POINTS = {code: (nom, lat) for code, nom, lat, _ in points_journalier()}
_LOCALITES = set(_POINTS)
_LOCS = sorted(_LOCALITES)  # lot pilotes + régions ; les départements ont leurs tests (0049)
ANNEES = range(1991, 2026)
NB_MENSUEL = len(ANNEES) * 12 * len(_LOCALITES)  # 420 mois x 34 localités = 14 280
NB_ANNUEL = len(ANNEES) * len(_LOCALITES)  # 35 ans x 34 localités = 1 190
# Tolérance relative : la base calcule en numeric sur les valeurs décimales du CSV,
# le test en flottants ; l'écart reste de l'ordre de 1e-15.
REL = 1e-12

_Cle = tuple[str, str, int, int | None]  # (localité, periode_type, année, mois)


@cache
def _meteo_journaliere() -> dict[str, list[tuple[date, float, float]]]:
    """``{localité: [(jour, T2M, RH2M)]}`` 1991-2025 depuis les CSV committés, lus une fois."""
    series = {
        g: {
            s["localite_code"]: s["mesures"]
            for s in lire_series_journalieres(
                CONTRATS_METEO_NASA_JOURNALIERS[g], LOT_METEO_JOURNALIER
            )
        }
        for g in ("t2m", "rh2m")
    }
    out: dict[str, list[tuple[date, float, float]]] = {}
    for loc, t2m in series["t2m"].items():
        rh2m = dict(series["rh2m"][loc])
        assert len(rh2m) == len(t2m), loc  # mêmes jours civils (contrats complets)
        out[loc] = [(jour, t, rh2m[jour]) for jour, t in t2m]
    return out


def _humidex(t: float, rh: float) -> float:
    """Humidex d'un jour, écrit ici sans passer par le service (fiche, § 2)."""
    e = rh / 100.0 * 6.112 * math.exp(17.67 * t / (t + 243.5))
    return t + 5.0 / 9.0 * (e - 10.0)


@cache
def _humidex_journalier() -> dict[str, list[tuple[date, float]]]:
    return {
        loc: [(jour, _humidex(t, rh)) for jour, t, rh in jours]
        for loc, jours in _meteo_journaliere().items()
    }


@cache
def _attendu() -> dict[_Cle, float]:
    """Recalcul indépendant : moyenne des humidex journaliers, périodes civiles complètes."""
    attendu: dict[_Cle, float] = {}
    for loc, jours in _humidex_journalier().items():
        par_mois: dict[tuple[int, int], list[float]] = defaultdict(list)
        par_annee: dict[int, list[float]] = defaultdict(list)
        for jour, h in jours:
            par_mois[(jour.year, jour.month)].append(h)
            par_annee[jour.year].append(h)
        for (annee, mois), valeurs in par_mois.items():
            assert len(valeurs) == calendar.monthrange(annee, mois)[1], (loc, annee, mois)
            attendu[(loc, "mensuel", annee, mois)] = statistics.fmean(valeurs)
        for annee, valeurs in par_annee.items():
            assert len(valeurs) == (366 if calendar.isleap(annee) else 365), (loc, annee)
            attendu[(loc, "annuel", annee, None)] = statistics.fmean(valeurs)
    return attendu


def _gravees(db_session: Session) -> dict[_Cle, float]:
    rows = db_session.execute(
        text(
            """
            SELECT loc.code AS localite, gm.periode_type, gm.annee_debut AS annee, gm.mois,
                   gm.valeur
            FROM grandeurs_metier gm JOIN localites loc ON loc.id = gm.localite_id
            WHERE gm.grandeur_code = :c AND loc.code = ANY(:locs)
            """
        ),
        {"c": GRANDEUR_CODE, "locs": _LOCS},
    ).all()
    return {(r.localite, r.periode_type, r.annee, r.mois): r.valeur for r in rows}


def _moyenne_nationale(par_localite_annee: dict[tuple[str, int], float]) -> dict[int, float]:
    """Moyenne des localités, par année."""
    par_annee: dict[int, list[float]] = defaultdict(list)
    for (_, annee), valeur in par_localite_annee.items():
        par_annee[annee].append(valeur)
    return {annee: statistics.fmean(v) for annee, v in par_annee.items()}


def _ecart_2024_2025(nationale: dict[int, float]) -> float:
    """Moyenne 2024-2025 moins moyenne 2016-2023."""
    recent = statistics.fmean(nationale[a] for a in (2024, 2025))
    return recent - statistics.fmean(nationale[a] for a in range(2016, 2024))


def test_grandeur_referentiel(db_session: Session) -> None:
    """Grandeur seedée en 0002 : id 15, F1, stockee, °C (apparents), version 1."""
    row = db_session.execute(
        text(
            """
            SELECT g.id, g.famille, g.strategie_calcul, g.version_formule_actuelle,
                   u.code AS unite
            FROM grandeurs_referentiel g JOIN unites u ON u.id = g.unite_id
            WHERE g.code = :c
            """
        ),
        {"c": GRANDEUR_CODE},
    ).one()
    assert (row.id, row.famille, row.strategie_calcul, row.version_formule_actuelle) == (
        15,
        "F1",
        "stockee",
        1,
    )
    assert row.unite == "degree_celsius"


def test_series_calculees(db_session: Session) -> None:
    """34 séries calcul_derive, source kuma_calculs, période 1991-2025, mise en garde."""
    rows = db_session.execute(
        text(
            """
            SELECT s.code, loc.code AS localite, loc.nom, s.methode_collecte, s.granularite,
                   src.code AS source, s.periode_debut, s.periode_fin, s.libelle,
                   s.note_publique
            FROM series_metadonnees s
            JOIN sources src ON src.id = s.source_id
            JOIN localites loc ON loc.id = s.localite_id
            WHERE s.grandeur_code = :c AND loc.code = ANY(:locs)
            """
        ),
        {"c": GRANDEUR_CODE, "locs": _LOCS},
    ).all()
    assert len(rows) == len(_LOCALITES) == 34
    assert {r.localite for r in rows} == _LOCALITES
    for r in rows:
        assert r.code == f"humidex_nasa_power_{r.localite}"
        assert r.source == "kuma_calculs" and r.methode_collecte == "calcul_derive"
        assert r.granularite is None
        assert str(r.periode_debut) == "1991-01-01" and str(r.periode_fin) == "2025-12-31"
        assert r.libelle == f"Humidex moyen NASA POWER — {r.nom} (1991-2025)"
        assert "ADR-0030" in r.note_publique and "Confiance B" in r.note_publique
        assert "Mise en garde" in r.note_publique and "ADR-0021" in r.note_publique


def test_completude_domaine_confiance(db_session: Session) -> None:
    """14 280 lignes mensuelles et 1 190 annuelles (420 mois, 35 ans par localité)."""
    rows = db_session.execute(
        text(
            """
            SELECT localite_id, periode_type, mois, valeur, niveau_confiance_derive, statut,
                   version_formule, annee_debut, annee_fin, valide_au
            FROM grandeurs_metier WHERE grandeur_code = :c AND localite_id IN
                (SELECT id FROM localites WHERE code = ANY(:locs))
            """
        ),
        {"c": GRANDEUR_CODE, "locs": _LOCS},
    ).all()
    assert len(rows) == NB_MENSUEL + NB_ANNUEL
    mois_par_localite: dict[int, set[tuple[int, int]]] = defaultdict(set)
    annees_par_localite: dict[int, set[int]] = defaultdict(set)
    for r in rows:
        assert r.annee_debut == r.annee_fin and r.valide_au is None
        assert 10.0 < r.valeur < 50.0  # borne de sanité de la migration
        assert r.niveau_confiance_derive == "B" and r.statut == "brut"
        assert r.version_formule == 1
        if r.periode_type == "mensuel":
            mois_par_localite[r.localite_id].add((r.annee_debut, r.mois))
        else:
            assert r.periode_type == "annuel" and r.mois is None
            annees_par_localite[r.localite_id].add(r.annee_debut)
    tous_les_mois = {(a, m) for a in ANNEES for m in range(1, 13)}
    assert len(mois_par_localite) == len(annees_par_localite) == 34
    assert all(m == tous_les_mois for m in mois_par_localite.values())
    assert all(a == set(ANNEES) for a in annees_par_localite.values())


def test_valeurs_fideles_au_calcul(db_session: Session) -> None:
    """Chaque valeur gravée = recalcul indépendant depuis les CSV journaliers NASA."""
    attendu = _attendu()
    gravees = _gravees(db_session)
    assert len(attendu) == NB_MENSUEL + NB_ANNUEL
    assert set(gravees) == set(attendu)
    for cle, valeur in gravees.items():
        assert valeur == pytest.approx(attendu[cle], rel=REL), cle


def test_definition_heritee_du_service(db_session: Session) -> None:
    """La migration reproduit la fonction pure du service hérité (mensuel et annuel).

    Contre-épreuves : l'annuel n'est pas la moyenne des 12 mois (mois inégaux), et
    l'humidex des moyennes mensuelles de T et RH n'est pas la moyenne des humidex
    journaliers (formule non linéaire) ; la tolérance les rejette.
    """
    gravees = _gravees(db_session)
    for loc, jours in _meteo_journaliere().items():
        resultat = _agreger_humidex(
            [(jour, t) for jour, t, _ in jours], [(jour, rh) for jour, _, rh in jours]
        )
        assert resultat["annees_skip_completude"] == ()
        assert resultat["mois_skip_completude"] == ()
        assert len(resultat["lignes_mensuelles"]) == len(ANNEES) * 12
        assert len(resultat["lignes_annuelles"]) == len(ANNEES)
        for ligne in resultat["lignes_mensuelles"] + resultat["lignes_annuelles"]:
            cle = (loc, ligne["periode_type"], ligne["annee_debut"], ligne["mois"])
            assert gravees[cle] == pytest.approx(ligne["valeur"], rel=REL), cle

    # Abidjan 2005 : l'annuel s'écarte de -0,029 °C de la moyenne des 12 mois.
    abidjan = "civ_dep_abidjan"
    moyenne_des_mois = statistics.fmean(
        gravees[(abidjan, "mensuel", 2005, m)] for m in range(1, 13)
    )
    assert gravees[(abidjan, "annuel", 2005, None)] != pytest.approx(moyenne_des_mois, rel=REL)
    # Korhogo, janvier 2005 (Harmattan) : l'humidex des moyennes s'écarte de -0,29 °C.
    korhogo = "civ_dep_korhogo"
    debut, fin = date(2005, 1, 1), date(2005, 1, 31)
    janvier = [(t, rh) for jour, t, rh in _meteo_journaliere()[korhogo] if debut <= jour <= fin]
    assert len(janvier) == 31
    h_des_moyennes = _humidex(
        statistics.fmean(t for t, _ in janvier), statistics.fmean(rh for _, rh in janvier)
    )
    assert gravees[(korhogo, "mensuel", 2005, 1)] != pytest.approx(h_des_moyennes, abs=0.01)


def test_lecture_par_l_api(
    client: TestClient, headers_auth: dict[str, str], db_session: Session
) -> None:
    """Une série se lit par ``/v1/series/{code}`` (séries ``kuma_calculs``, ADR-0029)."""
    r = client.get(
        "/v1/series/humidex_nasa_power_civ_dep_abidjan",
        params={"from": "2024-01", "to": "2024-12"},
        headers=headers_auth,
    )
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["granularite"] is None
    assert Counter(m["periode_type"] for m in corps["mesures"]) == {"annuel": 1, "mensuel": 12}
    gravees = _gravees(db_session)
    for m in corps["mesures"]:
        cle = ("civ_dep_abidjan", m["periode_type"], m["annee_debut"], m["mois"])
        assert m["valeur"] == gravees[cle], cle


def test_mise_en_garde_2024_2025(db_session: Session) -> None:
    """Les chiffres de la note publique sont ceux de la base.

    Humidex (34 localités) et T2M journalière NASA : 2024-2025 contre 2016-2023 ;
    T2M mensuelle NASA et ERA5 (142 localités) : chiffres de l'ADR-0021.
    """
    note = db_session.execute(
        text(
            "SELECT DISTINCT s.note_publique FROM series_metadonnees s "
            "JOIN localites loc ON loc.id = s.localite_id "
            "WHERE s.grandeur_code = :c AND loc.code = ANY(:locs)"
        ),
        {"c": GRANDEUR_CODE, "locs": _LOCS},
    ).scalar_one()
    humidex = {
        (r.localite, r.annee): r.valeur
        for r in db_session.execute(
            text(
                """
                SELECT localite_id AS localite, annee_debut AS annee, valeur
                FROM grandeurs_metier WHERE grandeur_code = :c AND periode_type = 'annuel'
                  AND localite_id IN (SELECT id FROM localites WHERE code = ANY(:locs))
                """
            ),
            {"c": GRANDEUR_CODE, "locs": _LOCS},
        )
    }
    t2m_journaliere = {
        (r.localite, r.annee): r.valeur
        for r in db_session.execute(
            text(
                """
                SELECT s.localite_id AS localite,
                       EXTRACT(YEAR FROM m.instant_mesure)::int AS annee, AVG(m.valeur) AS valeur
                FROM mesures_ressource m JOIN series_metadonnees s ON s.id = m.serie_id
                WHERE s.code = ANY(:c) AND m.valide_au IS NULL
                GROUP BY 1, 2
                """
            ),
            {"c": [CONTRATS_METEO_NASA_JOURNALIERS["t2m"].code_serie(loc) for loc in _LOCALITES]},
        )
    }
    t2m_mensuelle: dict[str, dict[tuple[str, int], float]] = defaultdict(dict)
    for r in db_session.execute(
        text(
            """
            SELECT src.code AS source, s.localite_id AS localite, mm.annee,
                   AVG(mm.valeur) AS valeur
            FROM mesures_ressource_mensuelles mm
            JOIN series_metadonnees s ON s.id = mm.serie_id
            JOIN sources src ON src.id = s.source_id
            WHERE s.grandeur_code = 't2m' AND s.granularite = 'mensuel'
              AND src.code IN ('nasa_power', 'ecmwf_era5') AND mm.valide_au IS NULL
            GROUP BY 1, 2, 3
            """
        )
    ):
        t2m_mensuelle[r.source][(r.localite, r.annee)] = r.valeur
    assert len(humidex) == len(t2m_journaliere) == NB_ANNUEL
    assert {s: len(v) for s, v in t2m_mensuelle.items()} == {
        "nasa_power": 142 * 35,
        "ecmwf_era5": 142 * 35,
    }

    ecarts = {
        "humidex": _ecart_2024_2025(_moyenne_nationale(humidex)),
        "t2m_nasa_journaliere": _ecart_2024_2025(_moyenne_nationale(t2m_journaliere)),
        "t2m_nasa_mensuelle": _ecart_2024_2025(_moyenne_nationale(t2m_mensuelle["nasa_power"])),
        "t2m_era5_mensuelle": _ecart_2024_2025(_moyenne_nationale(t2m_mensuelle["ecmwf_era5"])),
    }
    arrondis = {k: round(v, 2) for k, v in ecarts.items()}
    assert arrondis == {
        "humidex": 0.81,
        "t2m_nasa_journaliere": 0.87,
        "t2m_nasa_mensuelle": 0.85,
        "t2m_era5_mensuelle": 0.21,
    }
    for valeur in arrondis.values():
        assert f"{valeur:.2f}".replace(".", ",") in note


def test_constats_adr(db_session: Session) -> None:
    """Constats chiffrés de l'ADR-0030 : plages, gradient, saisons, jours d'inconfort."""
    gravees = _gravees(db_session)
    annuel = {(loc, a): v for (loc, p, a, _), v in gravees.items() if p == "annuel"}
    mensuel = {(loc, a, m): v for (loc, p, a, m), v in gravees.items() if p == "mensuel"}
    # Plages gravées : annuel dans la plage théorique de la fiche [27, 40].
    assert 31.0 < min(annuel.values()) < 31.1 and 38.0 < max(annuel.values()) < 38.1
    assert 21.6 < min(mensuel.values()) < 21.7 and 41.0 < max(mensuel.values()) < 41.1

    # Normale 1991-2020 : moyenne nationale, gradient nord-sud.
    normale = {
        loc: statistics.fmean(annuel[(loc, a)] for a in range(1991, 2021)) for loc in _LOCALITES
    }
    assert round(statistics.fmean(normale.values()), 2) == 34.54
    assert min(normale, key=normale.__getitem__) == "civ_tonkpi"
    assert max(normale, key=normale.__getitem__) == "civ_grands_ponts"
    latitudes = [_POINTS[loc][1] for loc in sorted(_LOCALITES)]
    r_lat = statistics.correlation(latitudes, [normale[loc] for loc in sorted(_LOCALITES)])
    assert -0.86 < r_lat < -0.83

    # Saisons : avril le plus inconfortable, janvier le moins (moyenne nationale).
    climatologie = [
        statistics.fmean(mensuel[(loc, a, m)] for loc in _LOCALITES for a in range(1991, 2021))
        for m in range(1, 13)
    ]
    assert climatologie.index(max(climatologie)) + 1 == 4
    assert climatologie.index(min(climatologie)) + 1 == 1

    # Jours d'inconfort (seuils de la fiche, H >= 40 et H >= 45), non stockés.
    jours = _humidex_journalier()
    au_dela_40 = {loc: sum(1 for _, h in j if h >= 40.0) for loc, j in jours.items()}
    assert sum(au_dela_40.values()) == 3998
    assert au_dela_40["civ_grands_ponts"] == 435 and au_dela_40["civ_tonkpi"] == 0
    assert sum(1 for j in jours.values() for _, h in j if h >= 45.0) == 0
    en_2024 = sum(1 for j in jours.values() for jour, h in j if h >= 40.0 and jour.year == 2024)
    assert en_2024 == 1130
    maximum = max((h, loc, jour) for loc, j in jours.items() for jour, h in j)
    assert (round(maximum[0], 2), maximum[1], maximum[2]) == (
        43.09,
        "civ_bounkani",
        date(2024, 4, 2),
    )
