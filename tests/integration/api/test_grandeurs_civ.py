"""Tests d'intégration des routes ``/v1/grandeurs/*`` sur les données réelles gravées.

Chaque route disponible est appelée sur des séries et localités réelles de la
base (résolues par requête, aucun code de localité figé) et son résultat est
**recalculé indépendamment** depuis les mesures brutes :

- POA paramétrable à inclinaison nulle : Perez (DNI/DHI compagnes, même source,
  profondeur différente du GHI) = ``DNI cos(z_midi) + DHI`` ; Liu-Jordan (avant
  le début des DNI/DHI) = GHI exactement ;
- POA bifacial : compagnes DNI/DHI trouvées, gain de face arrière positif ;
- productible PR fourni : ``P_STC/1000 x H x PR`` (journalier et mensuel) ;
- ghi_exceedance : P50/P90 recalculés depuis les 30 totaux annuels 1991-2020
  (série prolongée au-delà de 2020 : la normale reste 1991-2020), jumeaux de
  pixel cités ;
- incertitude inter-source : médiane |écart| et moyenne signée 2021-2023
  recalculées depuis ``grandeurs_metier`` ; dégénérescence lue telle quelle si
  la grandeur est gravée, sinon = taille du groupe de séries GHI NASA
  identiques - 1.

Les routes dont les séries d'entrée ne sont pas (encore) gravées — T2M,
précipitation, albédo journaliers NASA POWER, PM2.5/PM10 journaliers CAMS EAC4 —
sont testées des deux côtés : erreur 400 explicite tant que la série manque
(``skip`` sinon), calcul vérifié numériquement dès qu'elle existe (``skip`` tant
qu'elle manque).
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pvlib import soiling, solarposition  # type: ignore[import-untyped]
from sqlalchemy import Connection, text

from kuma_data_core.api.codes_erreur import CodeErreur
from kuma_data_core.db.session import get_engine

pytestmark = pytest.mark.integration

_BASE = "/v1/grandeurs"
_FENETRE = {"periode_debut": "2022-01-01", "periode_fin": "2022-01-10"}
_NOCT = 45.0
_GAMMA = -0.4


# === Accès base (lecture seule) ============================================


@pytest.fixture(scope="module")
def conn() -> Iterator[Connection]:
    with get_engine().connect() as connexion:
        yield connexion


def _code_serie(
    conn: Connection,
    localite: str,
    grandeur: str,
    granularite: str = "journalier",
    source: str = "nasa_power",
) -> str | None:
    return conn.execute(
        text(
            """
            SELECT sm.code FROM series_metadonnees sm
            JOIN localites l ON l.id = sm.localite_id
            JOIN sources s ON s.id = sm.source_id
            WHERE l.code = :loc AND sm.grandeur_code = :g AND s.code = :src
              AND sm.granularite = :gran AND sm.actif
            ORDER BY sm.periode_debut DESC, sm.id
            LIMIT 1
            """
        ),
        {"loc": localite, "g": grandeur, "src": source, "gran": granularite},
    ).scalar()


def _journalier(conn: Connection, code_serie: str, debut: date, fin: date) -> dict[date, float]:
    rows = conn.execute(
        text(
            """
            SELECT m.instant_mesure, m.valeur FROM mesures_ressource m
            JOIN series_metadonnees sm ON sm.id = m.serie_id
            WHERE sm.code = :c AND m.valide_au IS NULL
              AND m.instant_mesure BETWEEN :d AND :f
            """
        ),
        {"c": code_serie, "d": debut, "f": fin},
    ).all()
    return {r.instant_mesure: float(r.valeur) for r in rows}


def _mensuel(conn: Connection, code_serie: str) -> dict[tuple[int, int], float]:
    rows = conn.execute(
        text(
            """
            SELECT m.annee, m.mois, m.valeur FROM mesures_ressource_mensuelles m
            JOIN series_metadonnees sm ON sm.id = m.serie_id
            WHERE sm.code = :c AND m.valide_au IS NULL
            """
        ),
        {"c": code_serie},
    ).all()
    return {(int(r.annee), int(r.mois)): float(r.valeur) for r in rows}


def _periode(conn: Connection, code_serie: str) -> tuple[date, date]:
    row = conn.execute(
        text("SELECT periode_debut, periode_fin FROM series_metadonnees WHERE code = :c"),
        {"c": code_serie},
    ).one()
    return row.periode_debut, row.periode_fin


@pytest.fixture(scope="module")
def pilote(conn: Connection) -> str:
    """Localité portant GHI, DNI et DHI journaliers NASA POWER (premier code)."""
    code = conn.execute(
        text(
            """
            SELECT l.code FROM localites l
            WHERE (SELECT count(DISTINCT sm.grandeur_code) FROM series_metadonnees sm
                   JOIN sources s ON s.id = sm.source_id
                   WHERE sm.localite_id = l.id AND s.code = 'nasa_power'
                     AND sm.granularite = 'journalier' AND sm.actif
                     AND sm.grandeur_code IN ('ghi', 'dni', 'dhi')) = 3
            ORDER BY l.code LIMIT 1
            """
        )
    ).scalar()
    if code is None:
        pytest.skip("Aucune localité avec GHI/DNI/DHI journaliers NASA POWER en base.")
    return str(code)


@pytest.fixture(scope="module")
def mensuel_seul(conn: Connection) -> str:
    """Localité à GHI NASA POWER mensuel seulement (pas de journalier)."""
    code = conn.execute(
        text(
            """
            SELECT l.code FROM localites l
            JOIN series_metadonnees sm ON sm.localite_id = l.id
            JOIN sources s ON s.id = sm.source_id
            WHERE s.code = 'nasa_power' AND sm.grandeur_code = 'ghi'
              AND sm.granularite = 'mensuel' AND sm.actif
              AND NOT EXISTS (SELECT 1 FROM series_metadonnees j
                              WHERE j.localite_id = l.id AND j.granularite = 'journalier')
            ORDER BY l.code LIMIT 1
            """
        )
    ).scalar()
    if code is None:
        pytest.skip("Aucune localité à GHI NASA POWER mensuel seul en base.")
    return str(code)


def _coordonnees(conn: Connection, localite: str) -> tuple[float, float]:
    row = conn.execute(
        text("SELECT latitude, longitude FROM localites WHERE code = :c"), {"c": localite}
    ).one()
    return float(row.latitude), float(row.longitude)


def _groupes_jumeaux(conn: Connection) -> dict[str, list[str]]:
    """Groupes de localités à séries GHI NASA mensuelles 1991-2020 identiques (SQL pur)."""
    rows = conn.execute(
        text(
            """
            WITH vecteurs AS (
                SELECT l.code, array_agg(m.valeur ORDER BY m.annee, m.mois) AS v
                FROM series_metadonnees sm
                JOIN sources s ON s.id = sm.source_id
                JOIN localites l ON l.id = sm.localite_id
                JOIN mesures_ressource_mensuelles m ON m.serie_id = sm.id
                WHERE s.code = 'nasa_power' AND sm.grandeur_code = 'ghi'
                  AND sm.granularite = 'mensuel' AND sm.actif
                  AND m.valide_au IS NULL AND m.annee BETWEEN 1991 AND 2020
                GROUP BY l.code
            )
            SELECT array_agg(code ORDER BY code) AS membres FROM vecteurs GROUP BY v
            """
        )
    ).all()
    groupes: dict[str, list[str]] = {}
    for r in rows:
        for code in r.membres:
            groupes[code] = [m for m in r.membres if m != code]
    return groupes


# === Appels =================================================================


def _get(client: TestClient, headers: dict[str, str], route: str, **params: Any) -> Any:
    return client.get(f"{_BASE}/{route}", headers=headers, params=params)


def _ok(reponse: Any) -> Any:
    assert reponse.status_code == 200, reponse.text
    return reponse.json()


def _erreur(reponse: Any, statut: int, code: CodeErreur) -> str:
    assert reponse.status_code == statut, reponse.text
    erreur = reponse.json()["erreur"]
    assert erreur["code"] == code.value
    return str(erreur["message"])


def _valeurs_journalieres(corps: dict[str, Any]) -> dict[date, float]:
    return {date.fromisoformat(r["instant"]): r["valeur"] for r in corps["resultats"]}


def _midi_solaire(jour: date, longitude: float) -> datetime:
    return datetime(jour.year, jour.month, jour.day, 12, tzinfo=UTC) - timedelta(
        hours=longitude / 15.0
    )


# === POA paramétrable =======================================================


def test_poa_parametrable_perez_avec_compagnes_de_profondeur_differente(
    client: TestClient, headers_auth: dict[str, str], conn: Connection, pilote: str
) -> None:
    """GHI depuis 1991, DNI/DHI depuis 2001 : les compagnes sont trouvées (Perez).

    À inclinaison nulle, Perez se réduit à ``DNI cos(z) + DHI`` au midi solaire
    (diffus isotrope intégral, sol invisible).
    """
    ghi = _code_serie(conn, pilote, "ghi")
    dni, dhi = _code_serie(conn, pilote, "dni"), _code_serie(conn, pilote, "dhi")
    assert ghi and dni and dhi
    corps = _ok(
        _get(
            client,
            headers_auth,
            "poa_parametrable",
            code_serie_source=ghi,
            inclinaison_deg=0,
            orientation_deg=180,
            **_FENETRE,
        )
    )
    poa = _valeurs_journalieres(corps)
    debut, fin = date(2022, 1, 1), date(2022, 1, 10)
    dni_j, dhi_j = _journalier(conn, dni, debut, fin), _journalier(conn, dhi, debut, fin)
    assert len(poa) == 10 and set(poa) == set(dni_j)
    latitude, longitude = _coordonnees(conn, pilote)
    for jour, valeur in poa.items():
        instant = pd.DatetimeIndex([_midi_solaire(jour, longitude)])
        position = solarposition.get_solarposition(instant, latitude, longitude)
        zenith = float(position["zenith"].iloc[0])
        attendu = dni_j[jour] * np.cos(np.radians(zenith)) + dhi_j[jour]
        assert valeur == pytest.approx(attendu, rel=1e-9)


def test_poa_parametrable_liu_jordan_avant_dni_egal_ghi(
    client: TestClient, headers_auth: dict[str, str], conn: Connection, pilote: str
) -> None:
    """Avant le début des DNI/DHI, repli Liu-Jordan : POA(inclinaison 0) = GHI exactement."""
    ghi, dni = _code_serie(conn, pilote, "ghi"), _code_serie(conn, pilote, "dni")
    assert ghi and dni
    debut_ghi, _ = _periode(conn, ghi)
    debut_dni, _ = _periode(conn, dni)
    if debut_ghi >= debut_dni:
        pytest.skip("GHI et DNI journaliers débutent ensemble : pas de fenêtre Liu-Jordan.")
    debut = debut_ghi + timedelta(days=60)
    fin = debut + timedelta(days=4)
    corps = _ok(
        _get(
            client,
            headers_auth,
            "poa_parametrable",
            code_serie_source=ghi,
            inclinaison_deg=0,
            orientation_deg=180,
            periode_debut=debut.isoformat(),
            periode_fin=fin.isoformat(),
        )
    )
    poa = _valeurs_journalieres(corps)
    ghi_j = _journalier(conn, ghi, debut, fin)
    assert len(poa) == 5
    for jour, valeur in poa.items():
        assert valeur == pytest.approx(ghi_j[jour], abs=1e-9)


def test_poa_parametrable_serie_mensuelle_refusee(
    client: TestClient, headers_auth: dict[str, str], conn: Connection, mensuel_seul: str
) -> None:
    """Une série mensuelle n'est plus lue dans la table journalière (liste vide) : 400."""
    code = _code_serie(conn, mensuel_seul, "ghi", "mensuel")
    message = _erreur(
        _get(
            client,
            headers_auth,
            "poa_parametrable",
            code_serie_source=code,
            inclinaison_deg=10,
            orientation_deg=180,
            **_FENETRE,
        ),
        400,
        CodeErreur.VALIDATION_VALEUR_INVALIDE,
    )
    assert "'mensuel'" in message


# === POA bifacial ===========================================================


def _bifacial(
    client: TestClient, headers: dict[str, str], code: str, **params: Any
) -> dict[date, float]:
    corps = _ok(
        _get(
            client,
            headers,
            "poa_bifacial",
            code_serie_source=code,
            inclinaison_deg=10,
            orientation_deg=180,
            gcr=0.4,
            hauteur_m=1.5,
            pitch_m=5.0,
            **_FENETRE,
            **params,
        )
    )
    return _valeurs_journalieres(corps)


def test_poa_bifacial_compagnes_trouvees_et_gain_arriere(
    client: TestClient, headers_auth: dict[str, str], conn: Connection, pilote: str
) -> None:
    """Compagnes DNI/DHI trouvées (plus de 400) ; la face arrière n'ajoute que du positif."""
    ghi = _code_serie(conn, pilote, "ghi")
    assert ghi
    bifacial = _bifacial(client, headers_auth, ghi, bifacialite=0.8)
    face_avant = _bifacial(client, headers_auth, ghi, bifacialite=0.0)
    assert len(bifacial) == 10 and bifacial.keys() == face_avant.keys()
    assert all(v > 0 for v in face_avant.values())
    assert all(bifacial[j] >= face_avant[j] for j in bifacial)
    assert any(bifacial[j] > face_avant[j] for j in bifacial)


def test_poa_bifacial_albedo_surface_reel(
    client: TestClient, headers_auth: dict[str, str], conn: Connection, pilote: str
) -> None:
    """Avec la série ``albedo_surface`` journalière, ``albedo_sol`` n'est qu'un repli inutilisé."""
    if _code_serie(conn, pilote, "albedo_surface") is None:
        pytest.skip("Série albedo_surface journalière NASA POWER absente (gravure en cours).")
    ghi = _code_serie(conn, pilote, "ghi")
    assert ghi
    repli_bas = _bifacial(client, headers_auth, ghi, albedo_sol=0.05)
    repli_haut = _bifacial(client, headers_auth, ghi, albedo_sol=0.9)
    assert repli_bas == pytest.approx(repli_haut, rel=1e-12)


def test_poa_bifacial_sans_albedo_utilise_le_repli(
    client: TestClient, headers_auth: dict[str, str], conn: Connection, pilote: str
) -> None:
    """Sans série d'albédo, ``albedo_sol`` est appliqué (le résultat en dépend)."""
    if _code_serie(conn, pilote, "albedo_surface") is not None:
        pytest.skip("Série albedo_surface présente : le repli n'est pas exercé.")
    ghi = _code_serie(conn, pilote, "ghi")
    assert ghi
    repli_bas = _bifacial(client, headers_auth, ghi, albedo_sol=0.05)
    repli_haut = _bifacial(client, headers_auth, ghi, albedo_sol=0.9)
    assert all(repli_haut[j] > repli_bas[j] for j in repli_bas)


# === Productible PR fourni =================================================


def test_productible_pr_fourni_journalier(
    client: TestClient, headers_auth: dict[str, str], conn: Connection, pilote: str
) -> None:
    """``E = P_STC/1000 x H x PR`` jour par jour (H = irradiation de la série source)."""
    ghi = _code_serie(conn, pilote, "ghi")
    assert ghi
    corps = _ok(
        _get(
            client,
            headers_auth,
            "productible_pr_fourni",
            code_serie_source=ghi,
            pr_fourni=0.8,
            puissance_stc_wc=2500,
            **_FENETRE,
        )
    )
    produit = _valeurs_journalieres(corps)
    h = _journalier(conn, ghi, date(2022, 1, 1), date(2022, 1, 10))
    assert len(produit) == 10
    for jour, valeur in produit.items():
        assert valeur == pytest.approx(2.5 * h[jour] * 0.8, rel=1e-12)
    assert {r["unite"] for r in corps["resultats"]} == {"kWh"}


def test_productible_pr_fourni_mensuel(
    client: TestClient, headers_auth: dict[str, str], conn: Connection, mensuel_seul: str
) -> None:
    """Série mensuelle : productible quotidien moyen du mois = P_STC/1000 x H x PR."""
    ghi = _code_serie(conn, mensuel_seul, "ghi", "mensuel")
    assert ghi
    corps = _ok(
        _get(
            client,
            headers_auth,
            "productible_pr_fourni",
            code_serie_source=ghi,
            pr_fourni=0.75,
            puissance_stc_wc=1000,
            periode_debut="2023-01-01",
            periode_fin="2023-12-31",
        )
    )
    h = _mensuel(conn, ghi)
    assert [r["instant"] for r in corps["resultats"]] == [f"2023-{m:02d}" for m in range(1, 13)]
    for r in corps["resultats"]:
        annee, mois = map(int, r["instant"].split("-"))
        assert r["valeur"] == pytest.approx(h[(annee, mois)] * 0.75, rel=1e-12)


def _t2m(conn: Connection, localite: str) -> str | None:
    return _code_serie(conn, localite, "t2m")


def test_productible_pr_fourni_temperature_sans_t2m_400(
    client: TestClient, headers_auth: dict[str, str], conn: Connection, pilote: str
) -> None:
    if _t2m(conn, pilote) is not None:
        pytest.skip("Série T2M journalière présente : cas d'absence non exerçable.")
    message = _erreur(
        _get(
            client,
            headers_auth,
            "productible_pr_fourni",
            code_serie_source=_code_serie(conn, pilote, "ghi"),
            pr_fourni=0.8,
            puissance_stc_wc=1000,
            correction="temperature",
            noct_degc=_NOCT,
            coeff_temp_pourcent_par_degc=_GAMMA,
            **_FENETRE,
        ),
        400,
        CodeErreur.INCOMPATIBILITE_SOURCE_GRANDEUR,
    )
    assert "T2M" in message


def _ratio_thermique(h_kwh: float, t_amb: float) -> float:
    t_cell = t_amb + (_NOCT - 20.0) * (h_kwh * 1000.0 / 24.0) / 800.0
    return 1.0 + _GAMMA / 100.0 * (t_cell - 25.0)


def test_productible_pr_fourni_temperature_avec_t2m(
    client: TestClient, headers_auth: dict[str, str], conn: Connection, pilote: str
) -> None:
    t2m = _t2m(conn, pilote)
    if t2m is None:
        pytest.skip("Série T2M journalière NASA POWER absente (gravure en cours).")
    ghi = _code_serie(conn, pilote, "ghi")
    assert ghi
    corps = _ok(
        _get(
            client,
            headers_auth,
            "productible_pr_fourni",
            code_serie_source=ghi,
            pr_fourni=0.8,
            puissance_stc_wc=1000,
            correction="temperature",
            noct_degc=_NOCT,
            coeff_temp_pourcent_par_degc=_GAMMA,
            **_FENETRE,
        )
    )
    debut, fin = date(2022, 1, 1), date(2022, 1, 10)
    h, t = _journalier(conn, ghi, debut, fin), _journalier(conn, t2m, debut, fin)
    produit = _valeurs_journalieres(corps)
    assert len(produit) == 10
    for jour, valeur in produit.items():
        assert valeur == pytest.approx(h[jour] * 0.8 * _ratio_thermique(h[jour], t[jour]))


# === Productible correction thermique ======================================


def _thermique(client: TestClient, headers: dict[str, str], code: str | None) -> Any:
    return _get(
        client,
        headers,
        "productible_correction_thermique",
        code_serie_source=code,
        noct_degc=_NOCT,
        coeff_temp_pourcent_par_degc=_GAMMA,
        puissance_stc_wc=1000,
        **_FENETRE,
    )


def test_productible_correction_thermique_sans_t2m_400(
    client: TestClient, headers_auth: dict[str, str], conn: Connection, pilote: str
) -> None:
    if _t2m(conn, pilote) is not None:
        pytest.skip("Série T2M journalière présente : cas d'absence non exerçable.")
    reponse = _thermique(client, headers_auth, _code_serie(conn, pilote, "ghi"))
    assert "T2M" in _erreur(reponse, 400, CodeErreur.INCOMPATIBILITE_SOURCE_GRANDEUR)


def test_productible_correction_thermique_avec_t2m(
    client: TestClient, headers_auth: dict[str, str], conn: Connection, pilote: str
) -> None:
    t2m = _t2m(conn, pilote)
    if t2m is None:
        pytest.skip("Série T2M journalière NASA POWER absente (gravure en cours).")
    ghi = _code_serie(conn, pilote, "ghi")
    assert ghi
    produit = _valeurs_journalieres(_ok(_thermique(client, headers_auth, ghi)))
    debut, fin = date(2022, 1, 1), date(2022, 1, 10)
    h, t = _journalier(conn, ghi, debut, fin), _journalier(conn, t2m, debut, fin)
    assert len(produit) == 10
    for jour, valeur in produit.items():
        assert valeur == pytest.approx(h[jour] * _ratio_thermique(h[jour], t[jour]))


# === Énergie utile ECS ======================================================

_ECS = {
    "rendement_optique_eta0": 0.75,
    "pertes_lineaires_a1": 3.5,
    "pertes_quadratiques_a2": 0.015,
    "temperature_fluide_entree_degc": 40.0,
}


def test_energie_utile_ecs_sans_t2m_400(
    client: TestClient, headers_auth: dict[str, str], conn: Connection, pilote: str
) -> None:
    if _t2m(conn, pilote) is not None:
        pytest.skip("Série T2M journalière présente : cas d'absence non exerçable.")
    reponse = _get(
        client,
        headers_auth,
        "energie_utile_ecs",
        code_serie_source=_code_serie(conn, pilote, "ghi"),
        **_ECS,
        **_FENETRE,
    )
    assert "T2M" in _erreur(reponse, 400, CodeErreur.INCOMPATIBILITE_SOURCE_GRANDEUR)


def test_energie_utile_ecs_avec_t2m(
    client: TestClient, headers_auth: dict[str, str], conn: Connection, pilote: str
) -> None:
    t2m = _t2m(conn, pilote)
    if t2m is None:
        pytest.skip("Série T2M journalière NASA POWER absente (gravure en cours).")
    ghi = _code_serie(conn, pilote, "ghi")
    assert ghi
    corps = _ok(
        _get(client, headers_auth, "energie_utile_ecs", code_serie_source=ghi, **_ECS, **_FENETRE)
    )
    debut, fin = date(2022, 1, 1), date(2022, 1, 10)
    h, t = _journalier(conn, ghi, debut, fin), _journalier(conn, t2m, debut, fin)
    for jour, valeur in _valeurs_journalieres(corps).items():
        g_w = h[jour] * 1000.0 / 24.0
        dt = _ECS["temperature_fluide_entree_degc"] - t[jour]
        eta = max(
            0.0,
            _ECS["rendement_optique_eta0"]
            - _ECS["pertes_lineaires_a1"] * dt / g_w
            - _ECS["pertes_quadratiques_a2"] * dt**2 / g_w,
        )
        assert valeur == pytest.approx(eta * h[jour])


# === Degrés-jours de climatisation ==========================================


def test_degre_jour_climatisation_serie_ghi_refusee(
    client: TestClient, headers_auth: dict[str, str], conn: Connection, pilote: str
) -> None:
    reponse = _get(
        client,
        headers_auth,
        "degre_jour_climatisation",
        code_serie_source=_code_serie(conn, pilote, "ghi"),
        base_temperature_degc=26,
        **_FENETRE,
    )
    assert "'t2m'" in _erreur(reponse, 400, CodeErreur.INCOMPATIBILITE_SOURCE_GRANDEUR)


def test_degre_jour_climatisation_journalier(
    client: TestClient, headers_auth: dict[str, str], conn: Connection, pilote: str
) -> None:
    """DJC(mois) = somme des max(0, T_jour - T_b)."""
    t2m = _t2m(conn, pilote)
    if t2m is None:
        pytest.skip("Série T2M journalière NASA POWER absente (gravure en cours).")
    corps = _ok(
        _get(
            client,
            headers_auth,
            "degre_jour_climatisation",
            code_serie_source=t2m,
            base_temperature_degc=26,
            periode_debut="2022-01-01",
            periode_fin="2022-03-31",
        )
    )
    attendu: dict[str, float] = defaultdict(float)
    for jour, t in _journalier(conn, t2m, date(2022, 1, 1), date(2022, 3, 31)).items():
        attendu[f"{jour.year:04d}-{jour.month:02d}"] += max(0.0, t - 26.0)
    obtenu = {r["instant"]: r["valeur"] for r in corps["resultats"]}
    assert obtenu == pytest.approx(dict(attendu))


def test_degre_jour_climatisation_serie_mensuelle_refusee(
    client: TestClient, headers_auth: dict[str, str], conn: Connection, mensuel_seul: str
) -> None:
    t2m = _code_serie(conn, mensuel_seul, "t2m", "mensuel")
    if t2m is None:
        pytest.skip("Série T2M mensuelle NASA POWER absente (gravure en cours).")
    reponse = _get(
        client,
        headers_auth,
        "degre_jour_climatisation",
        code_serie_source=t2m,
        base_temperature_degc=26,
        **_FENETRE,
    )
    assert "'mensuel'" in _erreur(reponse, 400, CodeErreur.VALIDATION_VALEUR_INVALIDE)


# === ghi_exceedance =========================================================


def _p50_p90_attendus(conn: Connection, code_serie: str) -> tuple[float, float]:
    mesures = _mensuel(conn, code_serie)
    totaux = [
        sum(mesures[(annee, mois)] * calendar.monthrange(annee, mois)[1] for mois in range(1, 13))
        for annee in range(1991, 2021)
    ]
    return float(np.percentile(totaux, 50)), float(np.percentile(totaux, 10))


@pytest.mark.parametrize("cas", ["pilote", "mensuel_seul"])
def test_ghi_exceedance_recalcule_sur_la_normale(
    client: TestClient,
    headers_auth: dict[str, str],
    conn: Connection,
    cas: str,
    request: pytest.FixtureRequest,
) -> None:
    """Série mensuelle résolue (même si une journalière débute aussi en 1991) ;
    P50/P90 sur les 30 années 1991-2020, la série allant au-delà de 2020."""
    localite = request.getfixturevalue(cas)
    attendue = _code_serie(conn, localite, "ghi", "mensuel")
    assert attendue
    assert max(a for a, _ in _mensuel(conn, attendue)) > 2020  # série prolongée
    corps = _ok(_get(client, headers_auth, f"ghi_exceedance/{localite}"))
    assert corps["code_serie_source"] == attendue
    assert corps["periode"] == "1991-2020" and corps["base_annees"] == 30
    p50, p90 = _p50_p90_attendus(conn, attendue)
    assert corps["p50"] == pytest.approx(p50, rel=1e-12)
    assert corps["p90"] == pytest.approx(p90, rel=1e-12)
    assert corps["p90"] < corps["p50"]


def test_ghi_exceedance_jumeaux_de_pixel_cites(
    client: TestClient, headers_auth: dict[str, str], conn: Connection
) -> None:
    """Les localités à série NASA identique sont citées et ont les mêmes P50/P90."""
    groupes = _groupes_jumeaux(conn)
    localite = min((c for c, j in groupes.items() if j), default=None)
    if localite is None:
        pytest.skip("Aucun jumeau de pixel NASA POWER en base.")
    jumeaux = groupes[localite]
    corps = _ok(_get(client, headers_auth, f"ghi_exceedance/{localite}"))
    assert f"{len(jumeaux)} autre(s) localite(s) ({', '.join(jumeaux)})" in corps["limite"]
    jumelle = _ok(_get(client, headers_auth, f"ghi_exceedance/{jumeaux[0]}"))
    assert (jumelle["p50"], jumelle["p90"]) == (corps["p50"], corps["p90"])
    resolue = min((c for c, j in groupes.items() if not j), default=None)
    if resolue is not None:
        assert (
            "Jumeaux" not in _ok(_get(client, headers_auth, f"ghi_exceedance/{resolue}"))["limite"]
        )


def test_ghi_exceedance_localite_sans_serie_404(
    client: TestClient, headers_auth: dict[str, str]
) -> None:
    message = _erreur(
        _get(client, headers_auth, "ghi_exceedance/localite_inexistante"),
        404,
        CodeErreur.RESSOURCE_LOCALITE_INCONNUE,
    )
    assert "pilote" not in message.lower()


# === Proxy de salissure et PR réaliste ======================================


def _serie_pm2_5(conn: Connection) -> tuple[str, str] | None:
    """(code série PM2.5 EAC4 journalière, localité), de préférence avec pluie NASA."""
    row = conn.execute(
        text(
            """
            SELECT sm.code, l.code AS localite FROM series_metadonnees sm
            JOIN sources s ON s.id = sm.source_id
            JOIN localites l ON l.id = sm.localite_id
            WHERE s.code = 'cams_eac4' AND sm.grandeur_code = 'pm2_5'
              AND sm.granularite = 'journalier' AND sm.actif
            ORDER BY EXISTS (SELECT 1 FROM series_metadonnees p
                             JOIN sources ps ON ps.id = p.source_id
                             WHERE p.localite_id = l.id AND ps.code = 'nasa_power'
                               AND p.grandeur_code = 'precipitation'
                               AND p.granularite = 'journalier') DESC,
                     l.code
            LIMIT 1
            """
        )
    ).first()
    return (str(row.code), str(row.localite)) if row else None


def test_taux_salissure_proxy_serie_non_pm_refusee(
    client: TestClient, headers_auth: dict[str, str], conn: Connection, pilote: str
) -> None:
    reponse = _get(client, headers_auth, f"taux_salissure_proxy/{_code_serie(conn, pilote, 'ghi')}")
    assert "'pm2_5'" in _erreur(reponse, 400, CodeErreur.INCOMPATIBILITE_SOURCE_GRANDEUR)


def test_taux_salissure_proxy_recalcule_hsu(
    client: TestClient, headers_auth: dict[str, str], conn: Connection
) -> None:
    """Pertes = (1 - ratio HSU pvlib) x 100 sur l'intersection PM2.5 / PM10 / pluie."""
    trouve = _serie_pm2_5(conn)
    if trouve is None:
        pytest.skip("Séries PM2.5/PM10 journalières CAMS EAC4 absentes (gravure en cours).")
    code_pm2_5, localite = trouve
    code_pm10 = _code_serie(conn, localite, "pm10", source="cams_eac4")
    code_pluie = _code_serie(conn, localite, "precipitation")
    reponse = _get(client, headers_auth, f"taux_salissure_proxy/{code_pm2_5}")
    if code_pm10 is None or code_pluie is None:
        _erreur(reponse, 400, CodeErreur.INCOMPATIBILITE_SOURCE_GRANDEUR)
        pytest.skip("Compagne PM10 ou précipitation journalière absente (gravure en cours).")
    corps = _ok(reponse)
    large = (date(1900, 1, 1), date(2100, 1, 1))
    pm2_5, pm10, pluie = (_journalier(conn, c, *large) for c in (code_pm2_5, code_pm10, code_pluie))
    dates = sorted(pm2_5.keys() & pm10.keys() & pluie.keys())
    index = pd.DatetimeIndex(dates)
    ratio = soiling.hsu(
        rainfall=pd.Series([pluie[d] for d in dates], index=index),
        cleaning_threshold=corps["cleaning_threshold_mm"],
        surface_tilt=corps["surface_tilt_deg"],
        pm2_5=pd.Series([pm2_5[d] * 1e-6 for d in dates], index=index),
        pm10=pd.Series([pm10[d] * 1e-6 for d in dates], index=index),
        rain_accum_period=pd.Timedelta("1D"),
    )
    attendu = ((1.0 - ratio) * 100.0).clip(lower=0.0, upper=100.0).tolist()
    assert corps["periode"] == f"{dates[0].isoformat()}/{dates[-1].isoformat()}"
    assert [m["perte_pct"] for m in corps["mesures"]] == pytest.approx(attendu)


def test_pr_realiste_sans_correction(
    client: TestClient, headers_auth: dict[str, str], conn: Connection, pilote: str
) -> None:
    """Mode ``aucune`` : PR constant sur toute la série GHI journalière (depuis son début)."""
    ghi = _code_serie(conn, pilote, "ghi")
    assert ghi
    debut, fin = _periode(conn, ghi)
    corps = _ok(
        _get(client, headers_auth, f"pr_realiste/{ghi}", pr_fourni=0.8, correction="aucune")
    )
    assert corps["periode"] == f"{debut.isoformat()}/{fin.isoformat()}"
    assert len(corps["mesures_journalier"]) == (fin - debut).days + 1
    assert {m["pr_realiste"] for m in corps["mesures_journalier"]} == {0.8}
    mois = (fin.year - debut.year) * 12 + fin.month - debut.month + 1
    assert len(corps["mesures_mensuel"]) == mois


def test_pr_realiste_serie_mensuelle_refusee(
    client: TestClient, headers_auth: dict[str, str], conn: Connection, mensuel_seul: str
) -> None:
    code = _code_serie(conn, mensuel_seul, "ghi", "mensuel")
    reponse = _get(client, headers_auth, f"pr_realiste/{code}", pr_fourni=0.8, correction="aucune")
    assert "journaliere" in _erreur(reponse, 400, CodeErreur.INCOMPATIBILITE_SOURCE_GRANDEUR)


def test_pr_realiste_temperature(
    client: TestClient, headers_auth: dict[str, str], conn: Connection, pilote: str
) -> None:
    """Mode ``temperature`` : PR x ratio_T(NOCT) ; 400 explicite tant que T2M manque."""
    ghi = _code_serie(conn, pilote, "ghi")
    assert ghi
    params = {
        "pr_fourni": 0.8,
        "correction": "temperature",
        "noct_degc": _NOCT,
        "coeff_temp_pourcent_par_degc": _GAMMA,
    }
    reponse = _get(client, headers_auth, f"pr_realiste/{ghi}", **params)
    t2m = _t2m(conn, pilote)
    if t2m is None:
        assert "T2M" in _erreur(reponse, 400, CodeErreur.INCOMPATIBILITE_SOURCE_GRANDEUR)
        pytest.skip("Série T2M journalière NASA POWER absente (gravure en cours).")
    corps = _ok(reponse)
    debut, fin = date(2022, 1, 1), date(2022, 1, 10)
    h, t = _journalier(conn, ghi, debut, fin), _journalier(conn, t2m, debut, fin)
    obtenu = {
        date.fromisoformat(m["instant"]): m["pr_realiste"] for m in corps["mesures_journalier"]
    }
    for jour in h:
        assert obtenu[jour] == pytest.approx(0.8 * _ratio_thermique(h[jour], t[jour]))


def test_pr_realiste_salissure(
    client: TestClient, headers_auth: dict[str, str], conn: Connection
) -> None:
    """Mode ``salissure`` : PR <= PR fourni, fenêtre bornée à l'overlap PM."""
    trouve = _serie_pm2_5(conn)
    if trouve is None:
        pytest.skip("Séries PM2.5/PM10 journalières CAMS EAC4 absentes (gravure en cours).")
    _, localite = trouve
    ghi = _code_serie(conn, localite, "ghi")
    if ghi is None or _code_serie(conn, localite, "precipitation") is None:
        pytest.skip("GHI ou précipitation journalière NASA POWER absente pour cette localité.")
    corps = _ok(
        _get(client, headers_auth, f"pr_realiste/{ghi}", pr_fourni=0.8, correction="salissure")
    )
    valeurs = [m["pr_realiste"] for m in corps["mesures_journalier"]]
    assert valeurs and all(0.0 <= v <= 0.8 for v in valeurs)


# === Incertitude inter-source ===============================================


def _ecarts_attendus(conn: Connection, localite: str, grandeur_ecart: str) -> list[float]:
    rows = conn.execute(
        text(
            """
            SELECT gm.valeur FROM grandeurs_metier gm
            JOIN localites l ON l.id = gm.localite_id
            WHERE l.code = :loc AND gm.grandeur_code = :g AND gm.valide_au IS NULL
              AND gm.periode_type = 'mensuel' AND gm.annee_debut BETWEEN 2021 AND 2023
              AND gm.valeur IS NOT NULL
            """
        ),
        {"loc": localite, "g": grandeur_ecart},
    ).all()
    return [float(r.valeur) for r in rows]


def test_incertitude_inter_source_localite(
    client: TestClient, headers_auth: dict[str, str], conn: Connection, pilote: str
) -> None:
    """Écarts (comparée - nasa) / nasa lus et agrégés ; dégénérescence lue si gravée,
    sinon détectée (taille du groupe de séries GHI NASA identiques - 1)."""
    paires = {
        "ghi": ("ecart_relatif_ghi_sarah3_nasa", "PVGIS-SARAH3 vs NASA POWER"),
        "dni": ("ecart_relatif_dni_cams_nasa", "CAMS vs NASA POWER"),
    }
    if not _ecarts_attendus(conn, pilote, paires["ghi"][0]):
        pytest.skip("Écarts inter-sources 2021-2023 absents pour la localité.")
    corps = _ok(_get(client, headers_auth, f"incertitude_inter_source/{pilote}"))
    assert corps["fenetre"] == "2021-2023" and corps["niveau_confiance"] == "B"
    assert [e["grandeur"] for e in corps["ecarts"]] == ["ghi", "dni"]
    for ecart in corps["ecarts"]:
        code, libelle = paires[ecart["grandeur"]]
        valeurs = _ecarts_attendus(conn, pilote, code)
        assert ecart["paire"] == libelle
        assert ecart["n_mois"] == len(valeurs) == 36
        assert ecart["ecart_abs_pct"] == pytest.approx(float(np.median(np.abs(valeurs))), abs=1e-4)
        assert ecart["ecart_signe_pct"] == pytest.approx(float(np.mean(valeurs)), abs=1e-4)
    materialisee = _degenerescence_materialisee(conn, pilote)
    if materialisee is not None:
        # Grandeur gravée : lue telle quelle (valeur + commentaire éditorial).
        assert corps["degenerescence"]["n_jumeaux"] == int(materialisee[0])
        assert corps["degenerescence"]["note"] == materialisee[1]
        return
    jumeaux = _groupes_jumeaux(conn)[pilote]
    assert corps["degenerescence"]["n_jumeaux"] == len(jumeaux)
    if jumeaux:
        assert ", ".join(jumeaux) in corps["degenerescence"]["note"]


def _degenerescence_materialisee(conn: Connection, localite: str) -> tuple[float, str] | None:
    """(valeur, commentaire) de ``degenerescence_pixel`` gravée sur la série GHI NASA mensuelle."""
    row = conn.execute(
        text(
            """
            SELECT gm.valeur, coalesce(gm.commentaire_editorial, '') AS note
            FROM grandeurs_metier gm
            JOIN localites l ON l.id = gm.localite_id
            JOIN series_metadonnees sm ON sm.id = gm.series_metadonnees_id
            JOIN sources s ON s.id = sm.source_id
            WHERE l.code = :loc AND gm.grandeur_code = 'degenerescence_pixel'
              AND s.code = 'nasa_power' AND sm.grandeur_code = 'ghi'
              AND sm.granularite = 'mensuel' AND gm.valide_au IS NULL
              AND gm.valeur IS NOT NULL
            ORDER BY sm.periode_debut DESC, sm.id, gm.id
            LIMIT 1
            """
        ),
        {"loc": localite},
    ).first()
    return (float(row.valeur), str(row.note)) if row else None


def test_incertitude_inter_source_collection(
    client: TestClient, headers_auth: dict[str, str], conn: Connection
) -> None:
    """Périmètre data-driven (localités portant un écart 2021-2023), paginé, avec lat/lon."""
    attendu = conn.execute(
        text(
            """
            SELECT count(DISTINCT gm.localite_id) FROM grandeurs_metier gm
            WHERE gm.grandeur_code IN ('ecart_relatif_ghi_sarah3_nasa',
                                       'ecart_relatif_dni_cams_nasa',
                                       'ecart_relatif_referentiel', 'ecart_relatif_dni_cams')
              AND gm.periode_type = 'mensuel' AND gm.annee_debut BETWEEN 2021 AND 2023
              AND gm.valeur IS NOT NULL AND gm.valide_au IS NULL
            """
        )
    ).scalar_one()
    if attendu == 0:
        pytest.skip("Aucun écart inter-source 2021-2023 en base.")
    page = _ok(_get(client, headers_auth, "incertitude_inter_source", limit=5, offset=2))
    assert page["total"] == attendu and page["limit"] == 5 and page["offset"] == 2
    assert len(page["items"]) == min(5, attendu - 2)
    for item in page["items"]:
        lat, lon = _coordonnees(conn, item["code_localite"])
        assert (item["latitude_deg"], item["longitude_deg"]) == pytest.approx((lat, lon))
        assert item["niveau_confiance"] == "B" and item["ecarts"]


def test_incertitude_inter_source_localite_sans_ecart_404(
    client: TestClient, headers_auth: dict[str, str]
) -> None:
    message = _erreur(
        _get(client, headers_auth, "incertitude_inter_source/localite_inexistante"),
        404,
        CodeErreur.RESSOURCE_LOCALITE_INCONNUE,
    )
    assert "prefecture" not in message.lower()
