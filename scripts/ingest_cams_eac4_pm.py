#!/usr/bin/env python3
"""Ingesteur reproductible : PM2.5 et PM10 CAMS EAC4, mensuel et journalier, CIV.

Télécharge les concentrations de particules de surface de la réanalyse **CAMS
EAC4** (ADS Copernicus) sur la boîte englobante de la Côte d'Ivoire et écrit les
CSV gzip que la migration 0037 lit hors-ligne (ADR-0015, ADR-0022) :

- **mensuel** (``cams-global-reanalysis-eac4-monthly``, ``monthly_mean``) aux
  **142 localités** : ``seeds/donnees/cams_eac4_<grandeur>_mensuel_civ142.csv.gz`` ;
- **journalier** (``cams-global-reanalysis-eac4``, analyses 3-horaires
  00-21 UTC) aux **34 localités** du lot ``pilotes_regions`` :
  ``seeds/donnees/cams_eac4_<grandeur>_journalier_pilotes_regions.csv.gz``.

Contrats : ``kuma_data_core.db.seeds.aerosols_civ`` (source ``cams_eac4`` id 15,
méthode ``reanalyse``, confiance B, 2003-2025).

**Faits API** (sondage du 2026-10-15) : variables ``particulate_matter_2.5um`` et
``particulate_matter_10um`` (noms netCDF ``pm2p5``, ``pm10``), unité native
**kg m⁻³**, grille régulière **0,75°** alignée sur les multiples de 0,75°,
``data_format=netcdf_zip`` (un netCDF4 par archive). Le mensuel couvre 2003-01 à
2025-12, le 3-horaire 2003-01-01 à 2025-12-31.

**Traitement** :

- conversion kg/m³ → µg/m³ (× 1e9), sans autre transformation ;
- extraction au **point de grille le plus proche** (axe par axe, la grille étant
  régulière ; une égalité exacte est refusée plutôt que tranchée en silence). Le
  script affiche combien de localités partagent une même maille ;
- moyenne journalière = moyenne arithmétique des **8 analyses** 00, 03, …, 21 UTC
  du jour civil UTC (la Côte d'Ivoire est en UTC+0). Un jour sans ses 8 analyses
  ou une valeur manquante arrête l'ingestion : rien n'est comblé ;
- les valeurs nulles servies par l'EAC4 sont conservées et comptées.

**Contrôle de cohérence** : pour 3 localités (les points pilotes), le mensuel
servi est comparé à la moyenne des analyses 3-horaires du mois ; l'écart est
affiché. Attendu : quelques 10⁻⁴ µg/m³, sauf en mars 2024 où le mensuel servi
s'écarte de ses propres analyses (jusqu'à 6 %, incohérence de la source,
ADR-0022).

**Accès ADS (clé obligatoire)** : variable d'environnement ``ADS_API_KEY`` ; à
défaut ``~/.cdsapirc`` (cf. ``ingest_cams_radiation_mensuel.py``). Une requête par
année pour le 3-horaire, une seule pour le mensuel ; chaque archive est
téléchargée dans son propre sous-dossier du cache (``--cache``) et réutilisée
telle quelle si elle est valide, ce qui permet de reprendre après une
interruption (la file ADS est parfois lente).

Usage : ``uv run python -I scripts/ingest_cams_eac4_pm.py --cache <dossier>``
(``--granularite mensuel|journalier|tout``, ``--telecharger-seulement``).
"""

from __future__ import annotations

import argparse
import math
import os
import shutil
import tempfile
import threading
import time
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import cdsapi  # type: ignore[import-untyped]
import netCDF4  # type: ignore[import-untyped]
import numpy as np

from kuma_data_core.db.seeds.aerosols_civ import (
    ANNEE_DEBUT_EAC4,
    ANNEE_FIN_EAC4,
    CONTRATS_EAC4_JOURNALIERS,
    CONTRATS_EAC4_MENSUELS,
    LOT_AEROSOLS_JOURNALIER,
    LOT_AEROSOLS_MENSUEL,
    PARAMETRES_EAC4,
)
from kuma_data_core.db.seeds.lots_civ import POINTS_PILOTES, points_journalier, points_nationaux
from kuma_data_core.db.seeds.series_csv import ecrire_series, ecrire_series_journalieres

ADS_URL = "https://ads.atmosphere.copernicus.eu/api"
DATASET_MENSUEL = "cams-global-reanalysis-eac4-monthly"
DATASET_3H = "cams-global-reanalysis-eac4"
PAS_GRILLE = 0.75  # degrés
HEURES: tuple[str, ...] = ("00:00", "03:00", "06:00", "09:00", "12:00", "15:00", "18:00", "21:00")
UNITE_NATIVE = "kg m**-3"
KG_VERS_MICROGRAMME = 1e9  # kg/m³ -> µg/m³
NOM_ARCHIVE = "eac4.zip"
# L'ADS rejette une requête quand l'utilisateur en a trop en file pour un même
# jeu de données (« Number queued requests for this dataset is temporarily
# limited ») : on retente, avec une attente croissante.
TENTATIVES = 8
ATTENTE_REPRISE_S = 60
_VERROU_NETCDF = threading.Lock()

Point = tuple[str, str, float, float]
Champs = tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, np.ndarray]]


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


def _aire(points: list[Point]) -> list[float]:
    """Boîte ADS ``[N, O, S, E]`` calée sur la grille 0,75° et contenant, pour chaque
    point, les deux lignes de grille qui l'encadrent (donc sa maille la plus proche)."""
    lats = [p[2] for p in points]
    lons = [p[3] for p in points]
    return [
        math.ceil(max(lats) / PAS_GRILLE) * PAS_GRILLE,
        math.floor(min(lons) / PAS_GRILLE) * PAS_GRILLE,
        math.floor(min(lats) / PAS_GRILLE) * PAS_GRILLE,
        math.ceil(max(lons) / PAS_GRILLE) * PAS_GRILLE,
    ]


def _variables() -> list[str]:
    return [PARAMETRES_EAC4[g][0] for g in PARAMETRES_EAC4]


def _requete_mensuelle(aire: list[float]) -> dict[str, Any]:
    return {
        "variable": _variables(),
        "year": [str(a) for a in range(ANNEE_DEBUT_EAC4, ANNEE_FIN_EAC4 + 1)],
        "month": [f"{m:02d}" for m in range(1, 13)],
        "product_type": ["monthly_mean"],
        "area": aire,
        "data_format": "netcdf_zip",
    }


def _requete_3h(aire: list[float], annee: int) -> dict[str, Any]:
    return {
        "variable": _variables(),
        "date": [f"{annee}-01-01/{annee}-12-31"],
        "time": list(HEURES),
        "area": aire,
        "data_format": "netcdf_zip",
    }


def _lire_archive(chemin: Path) -> Champs:
    """Lit l'archive ADS : (instants UTC en s, latitudes, longitudes, {grandeur: kg/m³}).

    La bibliothèque HDF5 sous-jacente n'est pas sûre entre threads : les lectures
    sont sérialisées par un verrou (les téléchargements, eux, restent parallèles)."""
    with _VERROU_NETCDF:
        return _lire_archive_sans_verrou(chemin)


def _lire_archive_sans_verrou(chemin: Path) -> Champs:
    with zipfile.ZipFile(chemin) as z:
        noms = z.namelist()
        if len(noms) != 1:
            raise ValueError(f"{chemin} : {len(noms)} fichiers dans l'archive, 1 attendu.")
        ds = netCDF4.Dataset("eac4", memory=z.read(noms[0]))
    try:
        temps = np.asarray(ds["valid_time"][:], dtype="int64")
        if ds["valid_time"].units != "seconds since 1970-01-01":
            raise ValueError(f"{chemin} : unité de temps {ds['valid_time'].units!r}.")
        lats = np.asarray(ds["latitude"][:], dtype="f8")
        lons = np.asarray(ds["longitude"][:], dtype="f8")
        champs: dict[str, np.ndarray] = {}
        for grandeur, (_, nom_nc, _, _, _) in PARAMETRES_EAC4.items():
            var = ds[nom_nc]
            if var.units != UNITE_NATIVE:
                raise ValueError(f"{chemin} : {nom_nc} en {var.units!r}, {UNITE_NATIVE!r} attendu.")
            if var.dimensions != ("valid_time", "latitude", "longitude"):
                raise ValueError(f"{chemin} : dimensions {var.dimensions!r} inattendues.")
            champs[grandeur] = np.ma.filled(var[:].astype("f8"), np.nan)
    finally:
        ds.close()
    return temps, lats, lons, champs


def _telecharger_en_cache(
    dataset: str, requete: dict[str, Any], cache: Path, nom: str, nb_instants: int
) -> Path:
    """Archive d'une requête dans ``cache/<nom>/`` ; réutilisée si elle est valide.

    Chaque téléchargement se fait dans un sous-dossier neuf et vide, renommé en
    ``cache/<nom>`` une fois l'archive validée (nombre d'instants attendu)."""
    dossier = cache / nom
    chemin = dossier / NOM_ARCHIVE
    if chemin.exists():
        try:
            if len(_lire_archive(chemin)[0]) == nb_instants:
                return chemin
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            pass
    if dossier.exists():
        shutil.rmtree(dossier)  # cache invalide, incomplet ou interrompu : on redemande
    for tentative in range(1, TENTATIVES + 1):
        neuf = Path(tempfile.mkdtemp(prefix=f"{nom}.", dir=cache))
        try:
            _client().retrieve(dataset, requete, str(neuf / NOM_ARCHIVE))
            break
        except Exception as erreur:  # file ADS saturée, coupure réseau…
            shutil.rmtree(neuf)
            if tentative == TENTATIVES:
                raise
            print(f"{nom} : tentative {tentative} échouée ({erreur}) ; reprise", flush=True)
            time.sleep(ATTENTE_REPRISE_S * tentative)
    instants = len(_lire_archive(neuf / NOM_ARCHIVE)[0])
    if instants != nb_instants:
        raise SystemExit(f"{nom} : {instants} instants servis, {nb_instants} attendus.")
    neuf.rename(dossier)
    print(f"{nom} : téléchargé ({instants} instants)", flush=True)
    return chemin


def _nb_jours_annee(annee: int) -> int:
    return (date(annee, 12, 31) - date(annee, 1, 1)).days + 1


def telecharger(cache: Path, paralleles: int, granularite: str) -> dict[str, Path]:
    """Télécharge (ou réutilise) les archives : ``mensuel`` et ``3h_<année>``."""
    cache.mkdir(parents=True, exist_ok=True)
    aire = _aire(points_nationaux())
    print(f"Boîte ADS [N, O, S, E] : {aire}", flush=True)
    taches: list[tuple[str, str, dict[str, Any], int]] = []
    if granularite in ("mensuel", "tout"):
        nb_mois = (ANNEE_FIN_EAC4 - ANNEE_DEBUT_EAC4 + 1) * 12
        taches.append(
            (
                f"mensuel_{ANNEE_DEBUT_EAC4}_{ANNEE_FIN_EAC4}",
                DATASET_MENSUEL,
                _requete_mensuelle(aire),
                nb_mois,
            )
        )
    if granularite in ("journalier", "tout"):
        for annee in range(ANNEE_DEBUT_EAC4, ANNEE_FIN_EAC4 + 1):
            taches.append(
                (
                    f"3h_{annee}",
                    DATASET_3H,
                    _requete_3h(aire, annee),
                    _nb_jours_annee(annee) * len(HEURES),
                )
            )

    def traiter(tache: tuple[str, str, dict[str, Any], int]) -> tuple[str, Path]:
        nom, dataset, requete, nb = tache
        return nom, _telecharger_en_cache(dataset, requete, cache, nom, nb)

    with ThreadPoolExecutor(max_workers=paralleles) as pool:
        return dict(pool.map(traiter, taches))


def _maille(lat: float, lon: float, lats: np.ndarray, lons: np.ndarray) -> tuple[int, int]:
    """Indices du point de grille le plus proche (axe par axe, grille régulière)."""
    indices = []
    for valeur, axe in ((lat, lats), (lon, lons)):
        ecarts = np.abs(axe - valeur)
        i = int(np.argmin(ecarts))
        if np.count_nonzero(np.isclose(ecarts, ecarts[i], atol=1e-9)) > 1:
            raise SystemExit(f"Point ({lat}, {lon}) à égale distance de deux mailles.")
        if not (axe.min() < valeur < axe.max()):
            raise SystemExit(f"Point ({lat}, {lon}) hors de la grille téléchargée.")
        indices.append(i)
    return indices[0], indices[1]


def _mailles(points: list[Point], lats: np.ndarray, lons: np.ndarray) -> dict[str, tuple[int, int]]:
    mailles = {code: _maille(lat, lon, lats, lons) for code, _, lat, lon in points}
    partage = Counter(mailles.values())
    groupes = sorted(n for n in partage.values() if n > 1)
    print(
        f"{len(points)} localités -> {len(partage)} mailles distinctes ; "
        f"{sum(groupes)} localités partagent une maille ({len(groupes)} mailles, "
        f"tailles {groupes})",
        flush=True,
    )
    return mailles


def _instants(temps: np.ndarray) -> list[datetime]:
    return [datetime.fromtimestamp(int(t), tz=UTC) for t in temps]


def ecrire_mensuel(archive: Path) -> dict[str, dict[str, dict[tuple[int, int], float]]]:
    """Écrit les CSV mensuels (142 localités) ; renvoie {grandeur: {code: {(a, m): µg/m³}}}."""
    temps, lats, lons, champs = _lire_archive(archive)
    points = points_nationaux()
    mailles = _mailles(points, lats, lons)
    mois = [(t.year, t.month) for t in _instants(temps)]
    if any(t.day != 1 or t.hour != 0 for t in _instants(temps)) or len(set(mois)) != len(mois):
        raise SystemExit("Mensuel : instants inattendus (1er du mois 00 UTC, sans doublon).")
    sortie: dict[str, dict[str, dict[tuple[int, int], float]]] = {}
    for grandeur, contrat in CONTRATS_EAC4_MENSUELS.items():
        series = []
        sortie[grandeur] = {}
        for code, _, lat, lon in points:
            j, k = mailles[code]
            valeurs = champs[grandeur][:, j, k] * KG_VERS_MICROGRAMME
            if np.isnan(valeurs).any():
                raise SystemExit(f"Mensuel {grandeur} {code} : valeur manquante servie.")
            mesures = [(a, m, float(v)) for (a, m), v in zip(mois, valeurs, strict=True)]
            sortie[grandeur][code] = {(a, m): v for a, m, v in mesures}
            series.append((code, lat, lon, mesures))
        cible = ecrire_series(contrat, LOT_AEROSOLS_MENSUEL, series)
        tout = np.array([v for _, _, _, ms in series for _, _, v in ms])
        print(
            f"{grandeur} mensuel : {len(series)} séries -> {cible.name} ; "
            f"min {tout.min():.2f}, max {tout.max():.2f} µg/m³, nuls {int((tout == 0).sum())}",
            flush=True,
        )
    return sortie


def ecrire_journalier(
    archives: dict[str, Path],
) -> dict[str, dict[str, dict[tuple[int, int], list[float]]]]:
    """Écrit les CSV journaliers (34 localités).

    Renvoie, pour le contrôle de cohérence, les analyses 3-horaires brutes (µg/m³)
    groupées par mois : {grandeur: {code: {(a, m): [valeurs]}}}."""
    points = points_journalier()
    par_jour: dict[str, dict[str, dict[date, float]]] = {
        g: defaultdict(dict) for g in PARAMETRES_EAC4
    }
    par_mois: dict[str, dict[str, dict[tuple[int, int], list[float]]]] = {
        g: defaultdict(lambda: defaultdict(list)) for g in PARAMETRES_EAC4
    }
    nuls_3h: Counter[str] = Counter()
    pm25_sup_pm10_3h = 0
    mailles: dict[str, tuple[int, int]] | None = None
    for annee in range(ANNEE_DEBUT_EAC4, ANNEE_FIN_EAC4 + 1):
        temps, lats, lons, champs = _lire_archive(archives[f"3h_{annee}"])
        if mailles is None:
            mailles = _mailles(points, lats, lons)
        instants = _instants(temps)
        jours: dict[date, list[int]] = defaultdict(list)
        for i, t in enumerate(instants):
            jours[t.date()].append(i)
        if len(jours) != _nb_jours_annee(annee) or {d.year for d in jours} != {annee}:
            raise SystemExit(f"3h {annee} : {len(jours)} jours servis.")
        for jour, idx in jours.items():
            heures = sorted(instants[i].strftime("%H:%M") for i in idx)
            if tuple(heures) != HEURES:
                raise SystemExit(f"3h {jour} : analyses {heures}, {HEURES} attendues.")
        for code, _, _, _ in points:
            j, k = mailles[code]
            for grandeur in PARAMETRES_EAC4:
                valeurs = champs[grandeur][:, j, k] * KG_VERS_MICROGRAMME
                if np.isnan(valeurs).any():
                    raise SystemExit(f"3h {annee} {grandeur} {code} : valeur manquante servie.")
                nuls_3h[grandeur] += int((valeurs == 0).sum())
                for jour, idx in jours.items():
                    par_jour[grandeur][code][jour] = float(np.mean(valeurs[idx]))
                    par_mois[grandeur][code][(jour.year, jour.month)].extend(
                        float(v) for v in valeurs[idx]
                    )
            pm25_sup_pm10_3h += int((champs["pm2_5"][:, j, k] > champs["pm10"][:, j, k]).sum())
        print(f"3h {annee} : extrait", flush=True)

    for grandeur, contrat in CONTRATS_EAC4_JOURNALIERS.items():
        series = [
            (code, lat, lon, sorted(par_jour[grandeur][code].items()))
            for code, _, lat, lon in points
        ]
        cible = ecrire_series_journalieres(contrat, LOT_AEROSOLS_JOURNALIER, series)
        tout = np.array([v for _, _, _, ms in series for _, v in ms])
        print(
            f"{grandeur} journalier : {len(series)} séries -> {cible.name} ; "
            f"min {tout.min():.2f}, max {tout.max():.2f} µg/m³, jours nuls "
            f"{int((tout == 0).sum())}, analyses 3-horaires nulles {nuls_3h[grandeur]}",
            flush=True,
        )
    print(f"Analyses 3-horaires où PM2.5 > PM10 : {pm25_sup_pm10_3h}", flush=True)
    return par_mois


def controler_coherence(
    mensuel: dict[str, dict[str, dict[tuple[int, int], float]]],
    analyses: dict[str, dict[str, dict[tuple[int, int], list[float]]]],
) -> None:
    """Mensuel servi vs moyenne des analyses 3-horaires du mois, aux points pilotes."""
    for code in sorted(POINTS_PILOTES):
        for grandeur in PARAMETRES_EAC4:
            ecarts_abs, ecarts_rel = [], []
            for cle, servi in mensuel[grandeur][code].items():
                moyenne = float(np.mean(analyses[grandeur][code][cle]))
                ecarts_abs.append(abs(servi - moyenne))
                ecarts_rel.append(abs(servi - moyenne) / moyenne * 100 if moyenne else 0.0)
            print(
                f"Cohérence {code} {grandeur} : {len(ecarts_abs)} mois, écart max "
                f"{max(ecarts_abs):.4f} µg/m³ ({max(ecarts_rel):.4f} %), moyen "
                f"{np.mean(ecarts_abs):.4f} µg/m³",
                flush=True,
            )


def main() -> None:
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--cache", type=Path, default=Path(".cache/cams_eac4"))
    parseur.add_argument("--paralleles", type=int, default=3)
    parseur.add_argument("--granularite", choices=("mensuel", "journalier", "tout"), default="tout")
    parseur.add_argument(
        "--telecharger-seulement", action="store_true", help="remplir le cache sans écrire"
    )
    args = parseur.parse_args()
    archives = telecharger(args.cache, args.paralleles, args.granularite)
    if args.telecharger_seulement:
        return
    mensuel = analyses = None
    if args.granularite in ("mensuel", "tout"):
        mensuel = ecrire_mensuel(archives[f"mensuel_{ANNEE_DEBUT_EAC4}_{ANNEE_FIN_EAC4}"])
    if args.granularite in ("journalier", "tout"):
        analyses = ecrire_journalier(archives)
    if mensuel is not None and analyses is not None:
        controler_coherence(mensuel, analyses)


if __name__ == "__main__":
    main()
