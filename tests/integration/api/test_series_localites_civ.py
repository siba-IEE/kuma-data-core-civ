"""Tests d'intégration des endpoints de données sur le référentiel ivoirien réel.

Chaque endpoint du périmètre « données » est appelé au moins une fois sur
les données réelles de la base (instance Côte d'Ivoire, migrations
0001-0033) et sa réponse est confrontée à la base, jamais à une valeur
recopiée :

- ``/v1/localites`` : hiérarchie complète (1 pays, 14 districts, 31 régions,
  111 départements), recherche, fiche, résolution au point ;
- ``/v1/series`` : catalogue filtré (source, grandeur, granularité), série
  mensuelle (420 mois) et journalière (12 784 jours) relues à l'identique,
  pagination sans perte ni doublon, fenêtres, grandeurs dérivées
  (écarts inter-sources, fraction diffuse), CSV ;
- ``/v1/edition``, ``/v1/horaire``, ``/v1/calage``, ``/v1/etudes`` : réponse
  utile quand la donnée existe, erreur propre quand elle n'existe pas
  (aucune donnée horaire ni sol dans cette instance).

Les comptes de séries sont lus en base au moment du test : d'autres lots
(météo) peuvent s'ajouter sans casser ces tests. Aucun appel réseau : le
relais horaire amont n'est jamais atteint (profil édition figée ou
localité sans coordonnées).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.api.codes_erreur import CodeErreur
from kuma_data_core.api.main import app
from kuma_data_core.core.config import get_settings
from kuma_data_core.db.session import get_engine, obtenir_session
from kuma_data_core.publication.sql_edition import sql_metadonnees

pytestmark = pytest.mark.integration

PAYS = "civ"
DEPARTEMENT = "civ_dep_abidjan"
SERIE_MENSUELLE = "nasa_power_ghi_mensuel_civ_dep_abidjan"
SERIE_JOURNALIERE = "nasa_power_ghi_journalier_civ_dep_abidjan"
SERIE_ECART = "ecart_ghi_cams_nasa_civ_dep_abidjan"
SERIE_FRACTION_DIFFUSE = "fraction_diffuse_nasa_power_civ_dep_abidjan"


def _lignes(sql: str, **params: Any) -> list[Any]:
    with get_engine().connect() as connexion:
        return list(connexion.execute(text(sql), params).all())


def _scalaire(sql: str, **params: Any) -> Any:
    with get_engine().connect() as connexion:
        return connexion.execute(text(sql), params).scalar_one()


def _get(client: TestClient, url: str, headers: dict[str, str], **params: Any) -> Any:
    r = client.get(url, params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# === Localités ============================================================


def test_hierarchie_complete_pays_districts_regions_departements(
    client: TestClient, headers_auth: dict[str, str]
) -> None:
    """Un seul appel suffit à reconstruire l'arborescence (``parent_code``)."""
    page = _get(client, "/v1/localites", headers_auth, pays_iso3="CIV", limit=1000)
    items = page["items"]
    assert page["total"] == len(items) == 157

    par_code = {i["code"]: i for i in items}
    assert Counter(i["type_localite"] for i in items) == {
        "pays": 1,
        "region_administrative": 14,  # districts
        "prefecture": 31,  # régions
        "commune": 111,  # départements
    }
    assert par_code[PAYS]["parent_code"] == "afrique"

    attendu_parent = {
        "region_administrative": {"pays"},
        "prefecture": {"region_administrative"},
        # Districts autonomes (Abidjan, Yamoussoukro) : département
        # directement sous le district, sans région intermédiaire.
        "commune": {"prefecture", "region_administrative"},
    }
    for item in items:
        if item["type_localite"] == "pays":
            continue
        parent = par_code[item["parent_code"]]
        assert parent["type_localite"] in attendu_parent[item["type_localite"]], item["code"]
        # Chaque localité remonte jusqu'au pays.
        noeud, profondeur = item, 0
        while noeud["code"] != PAYS:
            noeud = par_code[noeud["parent_code"]]
            profondeur += 1
            assert profondeur <= 3
        assert item["pays_iso3"] == "CIV"

    # Descente en cascade : pays -> 14 districts.
    districts = _get(client, "/v1/localites", headers_auth, parent_code=PAYS)
    assert districts["total"] == 14
    assert {d["type_localite"] for d in districts["items"]} == {"region_administrative"}


def test_recherche_insensible_aux_accents_et_a_la_ponctuation(
    client: TestClient, headers_auth: dict[str, str]
) -> None:
    def codes(q: str, **filtres: Any) -> set[str]:
        page = _get(client, "/v1/localites", headers_auth, q=q, **filtres)
        assert page["total"] == len(page["items"])
        return {i["code"] for i in page["items"]}

    assert codes("san pedro") == {"civ_san_pedro", "civ_dep_san_pedro"}
    assert codes("San-Pédro") == codes("san pedro")
    assert codes("Agnéby") == codes("agneby") == {"civ_agneby_tiassa"}
    assert codes("Côte") == {PAYS}
    assert codes("korhogo", type_localite="commune") == {"civ_dep_korhogo"}
    # Les métacaractères LIKE sont littéraux.
    assert codes("%") == set()
    assert codes("_") == set()


def test_fiche_localite_conforme_a_la_base(
    client: TestClient, headers_auth: dict[str, str]
) -> None:
    fiche = _get(client, "/v1/localites/civ_dep_korhogo", headers_auth)
    (ligne,) = _lignes(
        """
        SELECT l.nom, l.type_localite, p.code AS parent_code, l.latitude, l.longitude,
               l.fuseau_horaire
        FROM localites l JOIN localites p ON p.id = l.parent_id
        WHERE l.code = 'civ_dep_korhogo'
        """
    )
    assert fiche["nom"] == ligne.nom
    assert fiche["type_localite"] == ligne.type_localite
    assert fiche["parent_code"] == ligne.parent_code
    assert fiche["latitude"] == pytest.approx(float(ligne.latitude))
    assert fiche["longitude"] == pytest.approx(float(ligne.longitude))
    assert fiche["fuseau_horaire"] == ligne.fuseau_horaire

    r = client.get("/v1/localites/civ_inexistante", headers=headers_auth)
    assert r.status_code == 404
    assert r.json()["erreur"]["code"] == CodeErreur.RESSOURCE_LOCALITE_INCONNUE.value


def test_resolution_au_point_sur_series_prolongees(
    client: TestClient, headers_auth: dict[str, str]
) -> None:
    """Les séries 1991-2025 couvrent la normale 1991-2020 : elles sont candidates.

    Avant ADR-0029, l'égalité stricte ``periode = 1991-2020`` ne trouvait
    aucune candidate et la résolution répondait 404 sur toute l'instance.
    """
    res = _get(client, "/v1/localites/resolution", headers_auth, lat=9.45, lon=-5.63)
    assert res["localite"]["code"] == "civ_dep_korhogo"
    assert res["meme_cellule"] is True
    assert res["cellule"] == {"lat_min": 9.0, "lat_max": 10.0, "lon_min": -6.0, "lon_max": -5.0}
    assert res["distance_km"] < 10

    (serie,) = _lignes(
        """
        SELECT l.code AS localite, sm.grandeur_code, sm.granularite,
               sm.periode_debut, sm.periode_fin
        FROM series_metadonnees sm JOIN localites l ON l.id = sm.localite_id
        WHERE sm.code = :code
        """,
        code=res["serie_climatologie"],
    )
    assert serie.localite == res["localite"]["code"]
    assert (serie.grandeur_code, serie.granularite) == ("ghi", "mensuel")
    assert serie.periode_debut.isoformat() <= "1991-01-01"
    assert serie.periode_fin.isoformat() >= "2020-12-31"

    # Point hors de toute cellule échantillonnée : la plus proche, signalée.
    loin = _get(client, "/v1/localites/resolution", headers_auth, lat=0.5, lon=0.5)
    assert loin["meme_cellule"] is False
    assert loin["distance_km"] > 300


def test_convention_de_cellule_un_degre_verifiee_sur_les_donnees() -> None:
    """Socle de la résolution (ADR-0004) : cellule NASA = 1 degré, frontières entières.

    Deux localités de la même cellule portent la même série GHI mensuelle
    NASA POWER (empreinte identique), deux cellules distinctes des séries
    distinctes - points posés sur une frontière entière compris.
    """
    (ligne,) = _lignes(
        """
        WITH empreintes AS (
            SELECT l.code,
                   floor(l.latitude) AS cel_lat, floor(l.longitude) AS cel_lon,
                   md5(string_agg(m.valeur::text, ',' ORDER BY m.annee, m.mois)) AS emp
            FROM series_metadonnees sm
            JOIN localites l ON l.id = sm.localite_id
            JOIN sources s ON s.id = sm.source_id
            JOIN mesures_ressource_mensuelles m
              ON m.serie_id = sm.id AND m.valide_au IS NULL
            WHERE s.code = 'nasa_power' AND sm.grandeur_code = 'ghi'
              AND sm.granularite = 'mensuel' AND l.pays_iso3 = 'CIV'
            GROUP BY l.code, l.latitude, l.longitude
        )
        SELECT count(*) AS localites,
               count(DISTINCT emp) AS empreintes,
               count(DISTINCT (cel_lat, cel_lon)) AS cellules,
               count(DISTINCT (cel_lat, cel_lon, emp)) AS couples
        FROM empreintes
        """
    )
    assert ligne.localites == 142
    assert ligne.empreintes == ligne.cellules == ligne.couples


# === Séries : catalogue ===================================================


def test_catalogue_des_series_d_une_localite_et_filtres(
    client: TestClient, headers_auth: dict[str, str]
) -> None:
    def total_api(**filtres: Any) -> tuple[int, list[dict[str, Any]]]:
        page = _get(client, "/v1/series", headers_auth, localite=DEPARTEMENT, limit=1000, **filtres)
        assert page["total"] == len(page["items"])
        return page["total"], page["items"]

    def total_base(clause: str = "TRUE", **params: Any) -> int:
        return int(
            _scalaire(
                f"""
                SELECT count(*) FROM series_metadonnees sm
                JOIN localites l ON l.id = sm.localite_id
                JOIN sources s ON s.id = sm.source_id
                WHERE l.code = :loc AND sm.actif AND {clause}
                """,
                loc=DEPARTEMENT,
                **params,
            )
        )

    total, items = total_api()
    assert total == total_base() >= 21
    assert {i["localite_code"] for i in items} == {DEPARTEMENT}

    total, items = total_api(source="nasa_power")
    assert total == total_base("s.code = 'nasa_power'")
    assert {i["source_code"] for i in items} == {"nasa_power"}

    total, items = total_api(grandeur="ghi")
    assert total == total_base("sm.grandeur_code = 'ghi'") >= 5

    total, items = total_api(granularite="journalier")
    assert total == total_base("sm.granularite = 'journalier'") >= 3
    assert {i["granularite"] for i in items} == {"journalier"}

    total, items = total_api(source="kuma_calculs")
    assert total == total_base("s.code = 'kuma_calculs'") >= 8
    assert {i["granularite"] for i in items} == {None}

    total, items = total_api(source="nasa_power", grandeur="ghi", granularite="mensuel")
    assert [i["code"] for i in items] == [SERIE_MENSUELLE]

    r = client.get("/v1/series", params={"granularite": "annuel"}, headers=headers_auth)
    assert r.status_code == 422


def test_catalogue_complet_paginable_sans_perte(
    client: TestClient, headers_auth: dict[str, str]
) -> None:
    # Ordre de référence lu en base (collation du serveur, pas celle de Python).
    attendu = [
        r.code for r in _lignes("SELECT code FROM series_metadonnees WHERE actif ORDER BY code")
    ]
    codes: list[str] = []
    offset = 0
    while True:
        page = _get(client, "/v1/series", headers_auth, limit=1000, offset=offset)
        assert page["total"] == len(attendu)
        codes.extend(i["code"] for i in page["items"])
        offset += 1000
        if offset >= page["total"]:
            break
    assert len(codes) == len(set(codes))
    assert codes == attendu


# === Séries : mesures =====================================================


def test_serie_mensuelle_420_mois_identique_a_la_base(
    client: TestClient, headers_auth: dict[str, str]
) -> None:
    serie = _get(client, f"/v1/series/{SERIE_MENSUELLE}", headers_auth)
    base = _lignes(
        """
        SELECT m.annee, m.mois, m.valeur
        FROM mesures_ressource_mensuelles m
        JOIN series_metadonnees sm ON sm.id = m.serie_id
        WHERE sm.code = :code AND m.valide_au IS NULL
        ORDER BY m.annee, m.mois
        """,
        code=SERIE_MENSUELLE,
    )
    assert len(base) == 420
    assert serie["granularite"] == "mensuel"
    assert serie["pagination_mesures"] == {"total": 420, "limit": 1000, "offset": 0}
    assert [(m["annee"], m["mois"], m["valeur"]) for m in serie["mesures"]] == [
        (r.annee, r.mois, r.valeur) for r in base
    ]
    assert {m["type"] for m in serie["mesures"]} == {"mensuel"}
    assert (serie["mesures"][0]["annee"], serie["mesures"][-1]["annee"]) == (1991, 2025)

    fenetre = _get(
        client,
        f"/v1/series/{SERIE_MENSUELLE}",
        headers_auth,
        **{"from": "2020-06", "to": "2021-05"},
    )
    assert fenetre["pagination_mesures"]["total"] == 12
    assert [(m["annee"], m["mois"]) for m in fenetre["mesures"]] == [
        (r.annee, r.mois) for r in base if (2020, 6) <= (r.annee, r.mois) <= (2021, 5)
    ]


def test_serie_journaliere_pagination_sans_perte_ni_doublon(
    client: TestClient, headers_auth: dict[str, str]
) -> None:
    base = _lignes(
        """
        SELECT m.instant_mesure, m.valeur
        FROM mesures_ressource m
        JOIN series_metadonnees sm ON sm.id = m.serie_id
        WHERE sm.code = :code AND m.valide_au IS NULL
        ORDER BY m.instant_mesure
        """,
        code=SERIE_JOURNALIERE,
    )
    assert len(base) == 12_784

    # Défaut : 1000 mesures, mais la troncature est annoncée.
    defaut = _get(client, f"/v1/series/{SERIE_JOURNALIERE}", headers_auth)
    assert len(defaut["mesures"]) == 1000
    assert defaut["pagination_mesures"] == {"total": 12_784, "limit": 1000, "offset": 0}

    lues: list[tuple[str, float]] = []
    offset = 0
    while True:
        page = _get(
            client, f"/v1/series/{SERIE_JOURNALIERE}", headers_auth, limit=5000, offset=offset
        )
        assert page["pagination_mesures"]["total"] == 12_784
        lues.extend((m["instant_mesure"], m["valeur"]) for m in page["mesures"])
        offset += 5000
        if offset >= page["pagination_mesures"]["total"]:
            break
    assert len(lues) == len({jour for jour, _ in lues}) == 12_784
    assert lues == [(r.instant_mesure.isoformat(), r.valeur) for r in base]

    fenetre = _get(
        client,
        f"/v1/series/{SERIE_JOURNALIERE}",
        headers_auth,
        **{"from": "2024-02-27", "to": "2024-03-02"},
    )
    assert [m["instant_mesure"] for m in fenetre["mesures"]] == [
        "2024-02-27",
        "2024-02-28",
        "2024-02-29",
        "2024-03-01",
        "2024-03-02",
    ]
    assert fenetre["pagination_mesures"]["total"] == 5


def _valeurs_derivees(code: str) -> list[Any]:
    return _lignes(
        """
        SELECT v.periode_type, v.annee_debut, v.mois, v.valeur
        FROM v_grandeurs_metier_courantes v
        JOIN series_metadonnees sm ON sm.id = v.series_metadonnees_id
        WHERE sm.code = :code
        ORDER BY v.annee_debut, v.mois NULLS FIRST, v.annee_fin, v.periode_type, v.id
        """,
        code=code,
    )


@pytest.mark.parametrize("code", [SERIE_ECART, SERIE_FRACTION_DIFFUSE])
def test_grandeurs_derivees_identiques_a_la_base_et_paginees(
    client: TestClient, headers_auth: dict[str, str], code: str
) -> None:
    base = _valeurs_derivees(code)
    assert base

    lues: list[tuple[str, int, int | None, float]] = []
    offset = 0
    while True:
        page = _get(client, f"/v1/series/{code}", headers_auth, limit=97, offset=offset)
        assert page["granularite"] is None
        assert page["pagination_mesures"]["total"] == len(base)
        lues.extend(
            (m["periode_type"], m["annee_debut"], m["mois"], m["valeur"]) for m in page["mesures"]
        )
        offset += 97
        if offset >= len(base):
            break
    assert lues == [(r.periode_type, r.annee_debut, r.mois, r.valeur) for r in base]


def test_fraction_diffuse_fenetre_annuelle(
    client: TestClient, headers_auth: dict[str, str]
) -> None:
    serie = _get(
        client,
        f"/v1/series/{SERIE_FRACTION_DIFFUSE}",
        headers_auth,
        **{"from": "2024-01", "to": "2024-12"},
    )
    types = Counter(m["periode_type"] for m in serie["mesures"])
    assert types == {"annuel": 1, "mensuel": 12}
    assert serie["pagination_mesures"]["total"] == 13
    assert all(0.0 < m["valeur"] < 1.0 for m in serie["mesures"])


def test_serie_mensuelle_en_csv(client: TestClient, headers_auth: dict[str, str]) -> None:
    r = client.get(f"/v1/series/{SERIE_MENSUELLE}", params={"format": "csv"}, headers=headers_auth)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["x-kuma-mesures-total"] == "420"
    lignes = r.text.strip().splitlines()
    assert len(lignes) == 421
    assert lignes[1].startswith(f"{SERIE_MENSUELLE},mensuel,1991,1,")


def test_serie_inconnue_404(client: TestClient, headers_auth: dict[str, str]) -> None:
    r = client.get("/v1/series/civ_serie_inexistante", headers=headers_auth)
    assert r.status_code == 404
    assert r.json()["erreur"]["code"] == CodeErreur.RESSOURCE_SERIE_INCONNUE.value


# === Édition publique =====================================================


@pytest.fixture
def session_annulee() -> Iterator[Session]:
    """Session de l'API liée à une transaction annulée en fin de test."""
    connexion = get_engine().connect()
    transaction = connexion.begin()
    session = Session(bind=connexion, join_transaction_mode="create_savepoint")

    def _obtenir() -> Iterator[Session]:
        yield session

    app.dependency_overrides[obtenir_session] = _obtenir
    try:
        yield session
    finally:
        app.dependency_overrides.pop(obtenir_session, None)
        session.close()
        transaction.rollback()
        connexion.close()


def test_edition_absente_sur_base_de_developpement(client: TestClient) -> None:
    if _scalaire("SELECT to_regclass('public.edition_metadonnees') IS NOT NULL"):
        pytest.skip("base servant une édition publiée")
    r = client.get("/v1/edition")
    assert r.status_code == 404
    assert r.json()["erreur"]["code"] == CodeErreur.RESSOURCE_INTROUVABLE.value


def test_edition_publiee_decrit_la_couverture_reelle(
    client: TestClient, session_annulee: Session
) -> None:
    session_annulee.execute(text("DROP TABLE IF EXISTS edition_metadonnees"))
    session_annulee.connection().exec_driver_sql(
        sql_metadonnees("edition_20261015", "2026-10-15", "583a1dd")
    )
    edition = _get(client, "/v1/edition", {})
    assert edition["edition_id"] == "edition_20261015"
    assert edition["couverture_resumee"] == {
        "localites": int(_scalaire("SELECT count(*) FROM localites WHERE actif")),
        "series": int(_scalaire("SELECT count(*) FROM series_metadonnees WHERE actif")),
    }


# === Horaire, calage, études : pas de donnée = erreur propre ==============


def _a_des_series_horaires(localite: str) -> bool:
    return bool(
        _scalaire(
            """
            SELECT EXISTS (
                SELECT 1 FROM series_metadonnees sm
                JOIN localites l ON l.id = sm.localite_id
                JOIN mesures_ressource_horaires m ON m.serie_id = sm.id
                WHERE l.code = :loc AND sm.granularite = 'horaire'
            )
            """,
            loc=localite,
        )
    )


def test_horaire_sans_donnee_stockee_en_edition_figee(
    client: TestClient, headers_auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    if _a_des_series_horaires(DEPARTEMENT):
        pytest.skip("des mesures horaires sont stockées pour cette localité")
    monkeypatch.setattr(get_settings(), "edition_figee", True)
    params = {"periode_debut": "2024-01-01", "periode_fin": "2024-01-07"}

    r = client.get(f"/v1/horaire/{DEPARTEMENT}/ghi", params=params, headers=headers_auth)
    assert r.status_code == 400
    erreur = r.json()["erreur"]
    assert erreur["code"] == CodeErreur.PLAGE_TEMPORELLE_NON_DISPONIBLE.value
    assert erreur["details"]["raison"] == "edition_figee_sans_relais_temps_reel"

    # Code court : résolu par le préfixe d'un pays du référentiel (même
    # erreur propre, pas un 404 de localité).
    r = client.get("/v1/horaire/abidjan/ghi", params=params, headers=headers_auth)
    assert r.status_code == 400

    r = client.get("/v1/horaire/inexistante/ghi", params=params, headers=headers_auth)
    assert r.status_code == 404
    assert r.json()["erreur"]["code"] == CodeErreur.RESSOURCE_LOCALITE_INCONNUE.value


def test_horaire_localite_sans_coordonnees_404_et_non_500(
    client: TestClient, headers_auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hors édition figée, le repli passe-plat exige des coordonnées."""
    monkeypatch.setattr(get_settings(), "edition_figee", False)
    r = client.get(
        "/v1/horaire/afrique/ghi",
        params={"periode_debut": "2024-01-01", "periode_fin": "2024-01-02"},
        headers=headers_auth,
    )
    assert r.status_code == 404
    assert r.json()["erreur"]["code"] == CodeErreur.RESSOURCE_INTROUVABLE.value


def test_horaire_disponibilite(client: TestClient, headers_auth: dict[str, str]) -> None:
    dispo = _get(client, f"/v1/horaire/{DEPARTEMENT}/ghi/disponibilite", headers_auth)
    assert dispo["plage_disponible"]["debut"] == "2001-01-01"
    assert dispo["plage_disponible"]["fin"] > "2025-01-01"


def test_calage_sans_mesure_sol(client: TestClient, headers_auth: dict[str, str]) -> None:
    attendus = int(
        _scalaire("SELECT count(DISTINCT code) FROM referentiels_calage WHERE actif = TRUE")
    )
    listing = _get(client, "/v1/calage", headers_auth)
    assert listing["total"] == len(listing["items"]) == attendus

    if _scalaire(
        """
        SELECT EXISTS (SELECT 1 FROM referentiels_calage rc
                       JOIN localites l ON l.id = rc.localite_id
                       WHERE l.code = :loc AND rc.grandeur_code = 'ghi' AND rc.actif)
        """,
        loc=DEPARTEMENT,
    ):
        pytest.skip("un référentiel de calage existe pour cette localité")
    r = client.get(f"/v1/calage/{DEPARTEMENT}/ghi", headers=headers_auth)
    assert r.status_code == 404
    assert r.json()["erreur"]["code"] == CodeErreur.RESSOURCE_INTROUVABLE.value


def test_etude_au_point_sans_sequence_horaire(
    client: TestClient, headers_auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    if _scalaire("SELECT count(*) FROM mesures_ressource_horaires"):
        pytest.skip("des mesures horaires sont stockées")
    point = {"lat": 5.42, "lon": -4.03}

    r = client.get("/v1/etudes/capsule", params=point, headers=headers_auth)
    assert r.status_code == 404
    assert r.json()["erreur"]["code"] == CodeErreur.RESSOURCE_INTROUVABLE.value

    # Fenêtre au-delà de l'ancienne période figée 2001-2025 : pas de 422.
    r = client.get(
        "/v1/etudes/capsule",
        params={**point, "annee_min": 2026, "annee_max": 2026},
        headers=headers_auth,
    )
    assert r.status_code == 404

    settings = get_settings()
    monkeypatch.setattr(settings, "kuma_calage_base", None)
    r = client.get("/v1/etudes/capsule", params={**point, "calage": 1}, headers=headers_auth)
    assert r.status_code == 503
    assert r.json()["erreur"]["code"] == CodeErreur.CALAGE_INDISPONIBLE.value
