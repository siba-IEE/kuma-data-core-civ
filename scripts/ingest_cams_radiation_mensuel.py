#!/usr/bin/env python3
"""Ingesteur reproductible : GHI, DNI et DHI mensuels CAMS Radiation (2005-2020), CIV.

Télécharge l'irradiation **all-sky** mensuelle de **CAMS Radiation**
(Heliosat-4 + McClear, ADS Copernicus) aux 3 points ivoiriens, et **régénère**
deux modules de seed que les migrations lisent hors-ligne (les migrations
n'accèdent jamais au réseau — cf. README) :

- ``src/kuma_data_core/db/seeds/series_cams_ghi_mensuel_civ.py`` (grandeur ``ghi``) ;
- ``src/kuma_data_core/db/seeds/series_cams_dni_mensuel_civ.py`` (grandeur ``dni``) ;
- ``src/kuma_data_core/db/seeds/series_cams_dhi_mensuel_civ.py`` (grandeur ``dhi``,
  contrat ADR-0013).

Contrats de série : ``docs/decisions/0011-cams-radiation-ghi-dni-quatrieme-source.md``
(GHI, DNI) et ``docs/decisions/0013-dhi-nasa-cams.md`` (DHI)
(source ``cams_radiation`` id 13, méthode ``modele_satellitaire``, confiance B).
Recette reprise du moteur générique (`scripts/preparer_seed_cams.py`, sondage ADS
vérifié 2026-06-16).

**Accès ADS (clé obligatoire)** : la clé est lue depuis la variable
d'environnement **``ADS_API_KEY``** (secret d'environnement) ; à défaut, depuis
``~/.cdsapirc`` (format standard cdsapi). Endpoint ADS
``https://ads.atmosphere.copernicus.eu/api``. Licence CC-BY CAMS à accepter une
fois sur le compte Copernicus.

**Faits API** (CAMS ``cams-solar-radiation-timeseries``) : ``sky_type=observed_cloud``
(all-sky), ``time_step=1month`` (agrégat mensuel), CSV ``;``-séparé, en-têtes
``#``. Colonnes **repérées par nom** dans l'en-tête : ``GHI``, ``BNI`` (= DNI) et
``DHI``, all-sky, en **Wh/m² intégrés au mois**. Couverture 2004-02 → J-1 ; on
grave **2005-2020** (fenêtre commune aux autres sources GHI).

**Conversion** vers ``kwh_par_m2_jour`` : ``(Wh/m²/mois ÷ 1000) ÷ jours du mois``.

Usage : ``ADS_API_KEY=... uv run --with cdsapi python scripts/ingest_cams_radiation_mensuel.py``

**Lots nationaux** (ADR-0015) : ``--lot regions`` interroge les localités du lot
(``kuma_data_core.db.seeds.lots_civ``) et écrit des CSV gzip
(``seeds/donnees/cams_<grandeur>_mensuel_<lot>.csv.gz``) au lieu des modules
Python. Requêtes ADS en parallèle ; les CSV bruts sont mis en cache
(``--cache``) pour reprendre après une interruption sans tout redemander.

**Extension 2021-2025** (ADR-0018) : ``--extension`` interroge les 142 localités
(pilotes + lots) sur 2021-2025 et écrit ``cams_<grandeur>_mensuel_ext_2021_2025.csv.gz``
(mêmes codes de série que les séries déjà gravées, qu'elle prolonge).
"""

from __future__ import annotations

import argparse
import calendar
import math
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import cdsapi  # type: ignore[import-untyped]

from kuma_data_core.db.seeds.localites_civ_seed_data import LOCALITES_SEED
from kuma_data_core.db.seeds.lots_civ import (
    CONTRATS_CAMS,
    LOT_EXTENSION,
    contrat_extension,
    points_lot,
    points_nationaux,
)
from kuma_data_core.db.seeds.series_csv import ecrire_series

DATASET = "cams-solar-radiation-timeseries"
ADS_URL = "https://ads.atmosphere.copernicus.eu/api"
SOURCE_CODE = "cams_radiation"
GRANULARITE = "mensuel"
METHODE_COLLECTE = "modele_satellitaire"
NIVEAU_CONFIANCE = "B"  # satellite (A réservé au sol)
ANNEE_DEBUT = 2005
ANNEE_FIN = 2020
WH_PAR_KWH = 1000.0
POINTS: tuple[str, ...] = ("civ_dep_abidjan", "civ_dep_yamoussoukro", "civ_dep_korhogo")

# Garde-fous de sanité (kWh/m²/jour, moyenne journalière du mois).
BORNES_MAX: dict[str, float] = {"ghi": 9.0, "dni": 12.0, "dhi": 6.0}
GRANDEURS: tuple[str, ...] = ("ghi", "dni", "dhi")

_SEEDS = Path(__file__).resolve().parents[1] / "src/kuma_data_core/db/seeds"


def _coord(code: str) -> tuple[str, float, float]:
    for e in LOCALITES_SEED:
        if e["code"] == code:
            return e["nom"], float(e["latitude"]), float(e["longitude"])
    raise SystemExit(f"Localité introuvable dans LOCALITES_SEED : {code!r}")


def _client() -> cdsapi.Client:
    """Client cdsapi sur l'ADS : clé depuis ADS_API_KEY, repli ~/.cdsapirc."""
    cle = os.environ.get("ADS_API_KEY")
    if not cle:
        rc_path = os.path.expanduser("~/.cdsapirc")
        if not os.path.exists(rc_path):
            raise SystemExit(
                "Clé ADS absente : définir ADS_API_KEY (secret d'environnement) "
                "ou fournir ~/.cdsapirc. Cf. ADR-0011."
            )
        rc: dict[str, str] = {}
        with open(rc_path) as f:
            for line in f:
                if line.strip() and ":" in line:
                    k, v = line.split(":", 1)
                    rc[k.strip()] = v.strip()
        cle = rc["key"]
    return cdsapi.Client(url=ADS_URL, key=cle)


def _telecharger(client: cdsapi.Client, lat: float, lon: float, dossier: Path) -> Path:
    chemin = dossier / f"cams_{lat:.4f}_{lon:.4f}.csv"
    client.retrieve(
        DATASET,
        {
            "sky_type": "observed_cloud",
            "location": {"latitude": lat, "longitude": lon},
            "altitude": ["-999."],
            "date": [f"{ANNEE_DEBUT}-01-01/{ANNEE_FIN}-12-31"],
            "time_step": "1month",
            "time_reference": "universal_time",
            "format": "csv",
        },
        str(chemin),
    )
    return chemin


def _index_colonnes(lignes: list[str]) -> dict[str, int]:
    """Repère les index des colonnes 'GHI', 'BNI' et 'DHI' (all-sky) dans l'en-tête CSV."""
    for ln in lignes:
        if "Observation period" in ln and ";GHI;" in f"{ln};":
            noms = [c.strip().lstrip("# ").strip() for c in ln.lstrip("#").split(";")]
            idx = {n: i for i, n in enumerate(noms)}
            if "GHI" in idx and "BNI" in idx and "DHI" in idx:
                return {"ghi": idx["GHI"], "dni": idx["BNI"], "dhi": idx["DHI"]}
    raise SystemExit("En-tête CAMS introuvable (colonnes GHI/BNI/DHI non repérées).")


def _extraire(chemin: Path) -> dict[str, list[tuple[int, int, float]]]:
    """Extrait GHI, DNI et DHI mensuels convertis (kWh/m²/jour) depuis le CSV CAMS."""
    lignes = chemin.read_text(encoding="utf-8", errors="replace").splitlines()
    col = _index_colonnes(lignes)
    out: dict[str, list[tuple[int, int, float]]] = {g: [] for g in GRANDEURS}
    for ln in lignes:
        if not ln or ln.startswith("#"):
            continue
        cols = ln.split(";")
        if len(cols) <= max(col.values()):
            continue
        periode = cols[0].strip()  # ex. '2005-01-01T00:00:00.0/2005-02-01T00:00:00.0'
        annee, mois = int(periode[:4]), int(periode[5:7])
        n_jours = calendar.monthrange(annee, mois)[1]
        for grandeur, i in col.items():
            wh = float(cols[i].strip())
            if math.isnan(wh):
                continue
            valeur = (wh / WH_PAR_KWH) / n_jours
            out[grandeur].append((annee, mois, round(valeur, 4)))
    for grandeur in out:
        out[grandeur].sort()
    return out


def main() -> None:
    par_grandeur: dict[str, list[dict[str, Any]]] = {g: [] for g in GRANDEURS}
    attendu = (ANNEE_FIN - ANNEE_DEBUT + 1) * 12
    client = _client()
    with tempfile.TemporaryDirectory() as tmp:
        dossier = Path(tmp)
        for code in POINTS:
            nom, lat, lon = _coord(code)
            mesures = _extraire(_telecharger(client, lat, lon, dossier))
            for grandeur in GRANDEURS:
                m = mesures[grandeur]
                if len(m) != attendu:
                    raise SystemExit(f"{code}/{grandeur} : {len(m)} mois, {attendu} attendus")
                vmin, vmax = min(v for _, _, v in m), max(v for _, _, v in m)
                if not (vmin >= 0.0 and vmax <= BORNES_MAX[grandeur]):
                    raise SystemExit(f"{grandeur} hors bornes pour {code} : [{vmin}, {vmax}]")
                par_grandeur[grandeur].append(
                    {
                        "code": f"cams_{grandeur}_mensuel_{code}",
                        "libelle": (
                            f"{grandeur.upper()} mensuel CAMS Radiation — {nom} "
                            f"({ANNEE_DEBUT}-{ANNEE_FIN})"
                        ),
                        "localite_code": code,
                        "latitude": lat,
                        "longitude": lon,
                        "mesures": m,
                    }
                )
                print(f"{code}/{grandeur}: {len(m)} mois, ∈ [{vmin}, {vmax}] kWh/m²/jour")
    for grandeur in GRANDEURS:
        _ecrire_seed(grandeur, par_grandeur[grandeur])
        print(f"Seed régénéré : series_cams_{grandeur}_mensuel_civ.py")


def _telecharger_en_cache(lat: float, lon: float, cache: Path) -> Path:
    """Télécharge le CSV CAMS d'un point, sauf s'il est déjà valide en cache."""
    chemin = cache / f"cams_{lat:.4f}_{lon:.4f}.csv"
    if chemin.exists():
        try:
            _extraire(chemin)
            return chemin
        except (SystemExit, ValueError):
            chemin.unlink()  # cache corrompu ou incomplet : on redemande
    with tempfile.TemporaryDirectory(dir=cache) as tmp:
        partiel = _telecharger(_client(), lat, lon, Path(tmp))
        partiel.replace(chemin)
    return chemin


def main_extension(cache: Path, paralleles: int) -> None:
    """Extension 2021-2025 des séries déjà gravées, aux 142 localités (ADR-0018)."""
    global ANNEE_DEBUT, ANNEE_FIN
    contrats = {g: contrat_extension(CONTRATS_CAMS[g]) for g in GRANDEURS}
    ANNEE_DEBUT = contrats["ghi"].annee_debut
    ANNEE_FIN = contrats["ghi"].annee_fin
    _telecharger_et_ecrire(points_nationaux(), cache, paralleles, contrats, LOT_EXTENSION)


def main_lot(lot: str, cache: Path, paralleles: int) -> None:
    """Lot national : télécharge en parallèle, valide, écrit les CSV gzip (ADR-0015)."""
    _telecharger_et_ecrire(points_lot(lot), cache, paralleles, CONTRATS_CAMS, lot)


def _telecharger_et_ecrire(
    points: list[tuple[str, str, float, float]],
    cache: Path,
    paralleles: int,
    contrats: dict[str, Any],
    lot: str,
) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    attendu = (ANNEE_FIN - ANNEE_DEBUT + 1) * 12

    def traiter(point: tuple[str, str, float, float]) -> tuple[str, float, float, Any]:
        code, _, lat, lon = point
        mesures = _extraire(_telecharger_en_cache(lat, lon, cache))
        print(f"{code}: téléchargé", flush=True)
        return code, lat, lon, mesures

    with ThreadPoolExecutor(max_workers=paralleles) as pool:
        resultats = list(pool.map(traiter, points))
    for grandeur in GRANDEURS:
        series = []
        for code, lat, lon, mesures in resultats:
            m = mesures[grandeur]
            if len(m) != attendu:
                raise SystemExit(f"{code}/{grandeur} : {len(m)} mois, {attendu} attendus")
            series.append((code, lat, lon, m))
        cible = ecrire_series(contrats[grandeur], lot, series)
        print(f"{grandeur}: {len(series)} séries -> {cible.name}")


def _dq(valeur: str) -> str:
    """Chaîne littérale en guillemets doubles (style ruff), unicode conservé."""
    return '"' + valeur.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ecrire_seed(grandeur: str, series: list[dict[str, Any]]) -> None:
    lignes: list[str] = []
    for s in series:
        lignes.append("    {")
        lignes.append(f'        "code": {_dq(s["code"])},')
        lignes.append(f'        "libelle": {_dq(s["libelle"])},')
        lignes.append(f'        "localite_code": {_dq(s["localite_code"])},')
        lignes.append(f'        "latitude": {s["latitude"]!r},')
        lignes.append(f'        "longitude": {s["longitude"]!r},')
        lignes.append('        "mesures": [')
        for annee, mois, valeur in s["mesures"]:
            lignes.append(f"            ({annee}, {mois}, {valeur}),")
        lignes.append("        ],")
        lignes.append("    },")
    corps = "\n".join(lignes)
    borne = BORNES_MAX[grandeur]
    contrat = "ADR-0013" if grandeur == "dhi" else "ADR-0011"
    contenu = f'''"""Séries {grandeur.upper()} mensuel CAMS Radiation 2005-2020 — instance CIV.

**Fichier généré** par ``scripts/ingest_cams_radiation_mensuel.py`` ; ne pas
éditer à la main. Contrat de série : {contrat} (conventions : ADR-0007,
normalisation Wh/m²→kWh/m²/jour : ADR-0011).

Chaque mesure ``(annee, mois, valeur)`` est la **moyenne journalière** du mois
en **kWh/m²/jour** (grandeur ``{grandeur}`` -> unité ``kwh_par_m2_jour``), obtenue
depuis l'irradiation mensuelle CAMS all-sky (Wh/m²) ÷ 1000 ÷ jours du mois.
Source ``cams_radiation`` (id 13, Heliosat-4), méthode ``modele_satellitaire``,
confiance **{NIVEAU_CONFIANCE}**. 12 mois/an, {ANNEE_DEBUT}-{ANNEE_FIN}
(192 mesures/série).
"""

from __future__ import annotations

from typing import Any

SOURCE_CODE: str = {_dq(SOURCE_CODE)}
GRANDEUR_CODE: str = {_dq(grandeur)}
GRANULARITE: str = {_dq(GRANULARITE)}
METHODE_COLLECTE: str = {_dq(METHODE_COLLECTE)}
NIVEAU_CONFIANCE: str = {_dq(NIVEAU_CONFIANCE)}
PERIODE_DEBUT: str = "{ANNEE_DEBUT}-01-01"
PERIODE_FIN: str = "{ANNEE_FIN}-12-31"
ANNEE_DEBUT: int = {ANNEE_DEBUT}
ANNEE_FIN: int = {ANNEE_FIN}

SERIES: list[dict[str, Any]] = [
{corps}
]


_ATTENDU = (ANNEE_FIN - ANNEE_DEBUT + 1) * 12
for _s in SERIES:
    assert len(_s["mesures"]) == _ATTENDU, (_s["code"], len(_s["mesures"]))
    for _annee, _mois, _valeur in _s["mesures"]:
        assert 1 <= _mois <= 12 and ANNEE_DEBUT <= _annee <= ANNEE_FIN
        assert 0.0 <= _valeur <= {borne}
_codes = {{_s["code"] for _s in SERIES}}
assert len(_codes) == len(SERIES), "codes de série dupliqués"
del _s, _annee, _mois, _valeur, _codes, _ATTENDU
'''
    (_SEEDS / f"series_cams_{grandeur}_mensuel_civ.py").write_text(contenu, encoding="utf-8")


if __name__ == "__main__":
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--lot", help="lot national (ex. regions) ; défaut : 3 points pilotes")
    parseur.add_argument("--cache", type=Path, default=Path(".cache/cams"))
    parseur.add_argument("--paralleles", type=int, default=4)
    parseur.add_argument(
        "--extension", action="store_true", help="prolonger 2021-2025 (142 localités)"
    )
    args = parseur.parse_args()
    if args.extension:
        main_extension(args.cache, args.paralleles)
    elif args.lot:
        main_lot(args.lot, args.cache, args.paralleles)
    else:
        main()
