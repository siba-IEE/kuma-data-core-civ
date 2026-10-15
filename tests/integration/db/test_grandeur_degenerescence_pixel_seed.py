"""Tests d'intégration de la grandeur ``degenerescence_pixel`` (migration 0042).

Dégénérescence de pixel (ADR-0027) : pour chaque série mensuelle brute, nombre
d'autres localités dont la série de même source et même grandeur est
strictement identique, mois par mois. Matérialisée dans ``grandeurs_metier``
(une ligne ``statique`` par série brute, FK vers cette série), grandeur
reclassée ``stockee``.

Vérifie le contrat (référentiel, une ligne par série mensuelle brute et aucune
autre, invariants de ligne, lecture par le chemin de l'API) et la **fidélité** :
les groupes de jumeaux sont recalculés indépendamment, en Python, depuis les
sources brutes (seeds pilotes, CSV des lots et de l'extension 2021+) pour les
10 familles de rayonnement, et depuis les mesures en base pour toute autre
famille gravée. Fige enfin les constats chiffrés de l'ADR : séries distinctes
par source et par niveau, partition NASA identique pour GHI, DNI et DHI et
calée sur des cellules de 1°, jumeaux des services au point limités aux
localités de coordonnées identiques, ERA5 plus fin que sa maille de 0,25°,
journalier NASA cohérent avec le mensuel.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from functools import cache
from types import ModuleType

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
from kuma_data_core.db.seeds.localites_civ_seed_data import LOCALITES_SEED
from kuma_data_core.db.seeds.lots_civ import POINTS_PILOTES, points_journalier, points_lot
from tests.integration.db.mesures_brutes import mesures_mensuelles

pytestmark = pytest.mark.integration

GRANDEUR_CODE = "degenerescence_pixel"

_NASA = (np_ghi, np_dni, np_dhi)
_AU_POINT = (sarah3_ghi, sarah3_dni, era5_ghi, era5_dni, cams_ghi, cams_dni, cams_dhi)
_RAYONNEMENT = _NASA + _AU_POINT

_REGIONS = frozenset(code for code, _, _, _ in points_lot("regions"))
_DEPARTEMENTS = frozenset(code for code, _, _, _ in points_lot("departements")) | POINTS_PILOTES
_LOCALITES = _REGIONS | _DEPARTEMENTS  # 31 régions + 111 départements
_COORDS = {
    e["code"]: (float(e["latitude"]), float(e["longitude"]))
    for e in LOCALITES_SEED
    if e["code"] in _LOCALITES
}

# Séries distinctes attendues (142 localités, 31 régions, 111 départements) : constats
# de l'ADR-0027 (NASA : 22 et 35 déjà relevés par l'ADR-0015).
_DISTINCTES: dict[str, tuple[int, int, int]] = {"nasa_power": (35, 22, 35)} | {
    s.SOURCE_CODE: (126, 31, 111) for s in _AU_POINT
}

_DISTINCTS = re.compile(r"À des coordonnées distinctes \((\d+)\) : ([^;]+) ;")
_CONFONDUS = re.compile(r"Aux mêmes coordonnées \((\d+)\) : ([^;]+) ;")


def _id(seed: ModuleType) -> str:
    return f"{seed.SOURCE_CODE}-{seed.GRANDEUR_CODE}"


def _groupes(
    vecteurs: dict[str, tuple[object, ...]], perimetre: frozenset[str]
) -> set[frozenset[str]]:
    """Partition des localités du périmètre par vecteur strictement identique."""
    par_vecteur: dict[tuple[object, ...], set[str]] = defaultdict(set)
    for loc in perimetre:
        par_vecteur[vecteurs[loc]].add(loc)
    return {frozenset(m) for m in par_vecteur.values()}


@cache
def _vecteurs_bruts(seed: ModuleType) -> dict[str, tuple[object, ...]]:
    """Vecteur ((année, mois), valeur) chronologique par localité, relu des sources brutes."""
    return {loc: tuple(sorted(m.items())) for loc, m in mesures_mensuelles(seed).items()}


def _groupes_bruts(seed: ModuleType, perimetre: frozenset[str] = _LOCALITES) -> set[frozenset[str]]:
    return _groupes(_vecteurs_bruts(seed), perimetre)


def _codes(liste: str) -> set[str]:
    return {c.strip() for c in liste.split(",")}


def _jumeaux_de_la_note(note: str) -> tuple[set[str], set[str]]:
    """Jumeaux à coordonnées distinctes et confondues, relus dans le commentaire."""
    sections = []
    for motif in (_DISTINCTS, _CONFONDUS):
        m = motif.search(note)
        codes = _codes(m.group(2)) if m else set()
        assert m is None or int(m.group(1)) == len(codes), note
        sections.append(codes)
    return sections[0], sections[1]


def test_grandeur_referentiel(db_session: Session) -> None:
    """Grandeur id 34, F1, sans dimension, version 1, reclassée stockee (ADR-0027)."""
    row = db_session.execute(
        text(
            """
            SELECT g.id, g.famille, g.strategie_calcul, g.version_formule_actuelle,
                   g.description, u.code AS unite
            FROM grandeurs_referentiel g JOIN unites u ON u.id = g.unite_id
            WHERE g.code = :c
            """
        ),
        {"c": GRANDEUR_CODE},
    ).one()
    assert (row.id, row.famille, row.strategie_calcul, row.version_formule_actuelle) == (
        34,
        "F1",
        "stockee",
        1,
    )
    assert row.unite == "sans_unite"
    assert "ADR-0027" in row.description and "calculee_volee" not in row.description


def test_une_ligne_par_serie_mensuelle_brute(db_session: Session) -> None:
    """Exactement une ligne par série mensuelle brute, aucune pour les autres séries.

    Les séries journalières (NASA aux 34 localités) et les séries calculées
    (``kuma_calculs``) n'en portent pas : l'API lit une ligne unique par
    (localité, source, grandeur). Une famille mensuelle gravée après 0042 sans
    recalcul échoue ici (placer 0042 après elle, ou la recalculer, ADR-0027).
    """
    rows = db_session.execute(
        text(
            """
            SELECT x.code AS source, s.grandeur_code, s.granularite,
                   COUNT(gm.id) AS nb
            FROM series_metadonnees s
            JOIN sources x ON x.id = s.source_id
            LEFT JOIN grandeurs_metier gm
                ON gm.series_metadonnees_id = s.id AND gm.grandeur_code = :g
               AND gm.valide_au IS NULL
            GROUP BY s.id, x.code
            """
        ),
        {"g": GRANDEUR_CODE},
    ).all()
    attendu: dict[tuple[str, str, str | None], set[int]] = defaultdict(set)
    for r in rows:
        mensuelle_brute = r.granularite == "mensuel" and r.source != "kuma_calculs"
        if r.nb != int(mensuelle_brute):
            attendu[(r.source, r.grandeur_code, r.granularite)].add(r.nb)
    assert not attendu, f"familles hors contrat (nombre de lignes par série) : {dict(attendu)}"
    total = db_session.execute(
        text("SELECT COUNT(*) FROM grandeurs_metier WHERE grandeur_code = :g"),
        {"g": GRANDEUR_CODE},
    ).scalar_one()
    assert total == sum(r.nb for r in rows)  # aucune ligne orpheline ni historisée


def test_lignes_rayonnement(db_session: Session) -> None:
    """10 familles de rayonnement x 142 localités = 1420 lignes."""
    rows = db_session.execute(
        text(
            """
            SELECT x.code AS source, s.grandeur_code, COUNT(*) AS nb,
                   COUNT(DISTINCT gm.localite_id) AS nb_localites
            FROM grandeurs_metier gm
            JOIN series_metadonnees s ON s.id = gm.series_metadonnees_id
            JOIN sources x ON x.id = s.source_id
            WHERE gm.grandeur_code = :g
            GROUP BY x.code, s.grandeur_code
            """
        ),
        {"g": GRANDEUR_CODE},
    ).all()
    comptes = {(r.source, r.grandeur_code): (r.nb, r.nb_localites) for r in rows}
    for seed in _RAYONNEMENT:
        assert comptes[(seed.SOURCE_CODE, seed.GRANDEUR_CODE)] == (142, 142), _id(seed)
    assert sum(comptes[(s.SOURCE_CODE, s.GRANDEUR_CODE)][0] for s in _RAYONNEMENT) == 1420


def test_invariants_de_ligne(db_session: Session) -> None:
    """Statique, années de la série, version 1, confiance B, brut, compte entier borné."""
    rows = db_session.execute(
        text(
            """
            SELECT gm.periode_type, gm.mois, gm.annee_debut, gm.annee_fin, gm.version_formule,
                   gm.valeur, gm.niveau_confiance_derive, gm.niveau_confiance_override,
                   gm.statut, gm.valide_au, gm.localite_id, s.localite_id AS localite_serie,
                   EXTRACT(YEAR FROM s.periode_debut)::int AS an_debut,
                   EXTRACT(YEAR FROM s.periode_fin)::int AS an_fin,
                   COUNT(*) OVER (PARTITION BY s.source_id, s.grandeur_code) AS n_famille
            FROM grandeurs_metier gm
            JOIN series_metadonnees s ON s.id = gm.series_metadonnees_id
            WHERE gm.grandeur_code = :g
            """
        ),
        {"g": GRANDEUR_CODE},
    ).all()
    assert rows
    for r in rows:
        assert (r.periode_type, r.mois, r.version_formule) == ("statique", None, 1)
        assert (r.annee_debut, r.annee_fin) == (r.an_debut, r.an_fin)
        assert r.localite_id == r.localite_serie
        assert (r.niveau_confiance_derive, r.niveau_confiance_override) == ("B", None)
        assert (r.statut, r.valide_au) == ("brut", None)
        assert r.valeur == int(r.valeur) and 0 <= r.valeur <= r.n_famille - 1
    courantes = db_session.execute(
        text(
            "SELECT COUNT(*) FROM v_grandeurs_metier_courantes "
            "WHERE grandeur_code = :g AND niveau_effectif = 'B'"
        ),
        {"g": GRANDEUR_CODE},
    ).scalar_one()
    assert courantes == len(rows)


@pytest.mark.parametrize("seed", _RAYONNEMENT, ids=_id)
def test_jumeaux_fideles_aux_sources_brutes(db_session: Session, seed: ModuleType) -> None:
    """Compte et liste des jumeaux = regroupement recalculé depuis les seeds et CSV."""
    jumeaux = {loc: g - {loc} for g in _groupes_bruts(seed) for loc in g}
    assert set(jumeaux) == _LOCALITES
    rows = db_session.execute(
        text(
            """
            SELECT l.code AS localite, gm.valeur, gm.commentaire_editorial AS note
            FROM grandeurs_metier gm
            JOIN localites l ON l.id = gm.localite_id
            JOIN series_metadonnees s ON s.id = gm.series_metadonnees_id
            JOIN sources x ON x.id = s.source_id
            WHERE gm.grandeur_code = :g AND x.code = :src AND s.grandeur_code = :gr
            """
        ),
        {"g": GRANDEUR_CODE, "src": seed.SOURCE_CODE, "gr": seed.GRANDEUR_CODE},
    ).all()
    assert {r.localite for r in rows} == _LOCALITES
    for r in rows:
        attendus = jumeaux[r.localite]
        assert r.valeur == len(attendus), r.localite
        distincts, confondus = _jumeaux_de_la_note(r.note)
        point = _COORDS[r.localite]
        assert distincts == {j for j in attendus if _COORDS[j] != point}, r.localite
        assert confondus == {j for j in attendus if _COORDS[j] == point}, r.localite
        assert ("Un compte nul" in r.note) == (not attendus), r.localite
        assert "confiance B" in r.note and "ADR-0027" in r.note


def test_jumeaux_fideles_a_la_base(db_session: Session) -> None:
    """Toute famille gravée (y compris hors rayonnement) : compte = regroupement en base.

    Recalcul indépendant de la migration : empreinte textuelle du vecteur de
    chaque série, regroupée en Python.
    """
    rows = db_session.execute(
        text(
            """
            SELECT s.id, s.source_id, s.grandeur_code, gm.valeur,
                   md5(array_agg(m.annee * 100 + m.mois ORDER BY m.annee, m.mois)::text
                       || '/' || array_agg(m.valeur ORDER BY m.annee, m.mois)::text) AS empreinte
            FROM grandeurs_metier gm
            JOIN series_metadonnees s ON s.id = gm.series_metadonnees_id
            JOIN mesures_ressource_mensuelles m
                ON m.serie_id = s.id AND m.valide_au IS NULL AND m.statut <> 'deprecie'
            WHERE gm.grandeur_code = :g
            GROUP BY s.id, gm.valeur
            """
        ),
        {"g": GRANDEUR_CODE},
    ).all()
    taille: dict[tuple[int, str, str], int] = defaultdict(int)
    for r in rows:
        taille[(r.source_id, r.grandeur_code, r.empreinte)] += 1
    for r in rows:
        assert r.valeur == taille[(r.source_id, r.grandeur_code, r.empreinte)] - 1, r.id


def test_nasa_meme_partition_ghi_dni_dhi() -> None:
    """GHI, DNI et DHI NASA partagent la grille CERES : mêmes groupes (35)."""
    partitions = [_groupes_bruts(seed) for seed in _NASA]
    assert partitions[0] == partitions[1] == partitions[2]
    assert len(partitions[0]) == 35


def test_nasa_partition_cellules_un_degre() -> None:
    """Constat : la partition NASA coïncide avec des cellules de 1° bornées aux degrés entiers."""
    cellules: dict[tuple[int, int], set[str]] = defaultdict(set)
    for loc, (lat, lon) in _COORDS.items():
        cellules[(math.floor(lat), math.floor(lon))].add(loc)
    assert {frozenset(c) for c in cellules.values()} == _groupes_bruts(np_ghi)
    assert len(cellules) == 35


def test_nasa_plus_grands_groupes() -> None:
    """Constats ADR : 8 localités seules dans leur série, 134 avec jumeaux, groupe max 12."""
    groupes = _groupes_bruts(np_ghi)
    tailles = sorted((len(g) for g in groupes), reverse=True)
    assert tailles[:6] == [12, 9, 9, 8, 7, 7]
    assert sum(t == 1 for t in tailles) == 8
    assert sum(t for t in tailles if t > 1) == 134
    plus_grand = max(groupes, key=len)
    assert {"civ_dep_yamoussoukro", "civ_dep_toumodi", "civ_belier", "civ_goh"} <= plus_grand
    # Départements seuls : 12 sans aucun autre département dans leur série.
    par_dep = _groupes_bruts(np_ghi, _DEPARTEMENTS)
    assert sum(len(g) == 1 for g in par_dep) == 12


def test_sources_au_point_jumeaux_confondus() -> None:
    """SARAH-3, ERA5 et CAMS : seules les 16 paires de coordonnées identiques sont jumelles."""
    par_point: dict[tuple[float, float], set[str]] = defaultdict(set)
    for loc, point in _COORDS.items():
        par_point[point].add(loc)
    confondues = {frozenset(m) for m in par_point.values() if len(m) > 1}
    assert len(confondues) == 16
    assert all(len(m) == 2 and m & _REGIONS and m & _DEPARTEMENTS for m in confondues)
    for seed in _AU_POINT:
        multiples = {g for g in _groupes_bruts(seed) if len(g) > 1}
        assert multiples == confondues, _id(seed)


@pytest.mark.parametrize("seed", _RAYONNEMENT, ids=_id)
def test_series_distinctes_par_niveau(seed: ModuleType) -> None:
    """Séries distinctes aux 142 localités, aux 31 régions et aux 111 départements."""
    obtenu = tuple(
        len(_groupes_bruts(seed, perimetre)) for perimetre in (_LOCALITES, _REGIONS, _DEPARTEMENTS)
    )
    assert obtenu == _DISTINCTES[seed.SOURCE_CODE]


@pytest.mark.parametrize("seed", (era5_ghi, era5_dni), ids=_id)
def test_era5_plus_fin_que_sa_maille(seed: ModuleType) -> None:
    """ERA5 via PVGIS distingue chaque point (126), plus que ses noeuds de 0,25° (110)."""
    points = set(_COORDS.values())
    noeuds = {(round(lat / 0.25), round(lon / 0.25)) for lat, lon in points}
    assert len(points) == 126 and len(noeuds) == 110
    assert len(_groupes_bruts(seed)) == len(points)


@pytest.mark.parametrize("seed", _NASA, ids=_id)
def test_journalier_nasa_meme_partition(db_session: Session, seed: ModuleType) -> None:
    """Le journalier NASA regroupe les localités comme le mensuel : aux 142 localités
    depuis le lot des 108 départements (0046, ADR-0031), et aux 34 du lot initial."""
    rows = db_session.execute(
        text(
            """
            SELECT l.code AS localite,
                   md5(array_agg(m.valeur ORDER BY m.instant_mesure)::text) AS empreinte
            FROM series_metadonnees s
            JOIN sources x ON x.id = s.source_id AND x.code = 'nasa_power'
            JOIN localites l ON l.id = s.localite_id
            JOIN mesures_ressource m ON m.serie_id = s.id AND m.valide_au IS NULL
            WHERE s.granularite = 'journalier' AND s.grandeur_code = :gr
            GROUP BY l.code
            """
        ),
        {"gr": seed.GRANDEUR_CODE},
    ).all()
    assert {r.localite for r in rows} == _LOCALITES
    vecteurs: dict[str, tuple[object, ...]] = {r.localite: (r.empreinte,) for r in rows}
    journalier = _groupes(vecteurs, _LOCALITES)
    assert journalier == _groupes_bruts(seed)
    assert len(journalier) == 35
    lot_initial = frozenset(code for code, _, _, _ in points_journalier())
    assert len(lot_initial) == 34
    journalier_34 = _groupes(vecteurs, lot_initial)
    assert journalier_34 == _groupes_bruts(seed, lot_initial)
    assert len(journalier_34) == 22


def test_lecture_par_le_chemin_de_l_api(db_session: Session) -> None:
    """Chemin de lecture de l'API (NASA GHI) : une ligne courante unique par localité."""
    rows = db_session.execute(
        text(
            """
            SELECT l.code AS localite, COUNT(*) AS nb, MIN(gm.valeur) AS valeur
            FROM grandeurs_metier gm
            JOIN localites l ON l.id = gm.localite_id
            JOIN series_metadonnees sm ON sm.id = gm.series_metadonnees_id
            JOIN sources s ON s.id = sm.source_id
            WHERE gm.grandeur_code = 'degenerescence_pixel'
              AND s.code = 'nasa_power' AND sm.grandeur_code = 'ghi'
              AND gm.valide_au IS NULL
            GROUP BY l.code
            """
        )
    ).all()
    assert {r.localite for r in rows} == _LOCALITES
    assert all(r.nb == 1 for r in rows)
    valeurs = {r.localite: r.valeur for r in rows}
    assert valeurs["civ_dep_yamoussoukro"] == 11
    assert valeurs["civ_dep_tabou"] == 0
