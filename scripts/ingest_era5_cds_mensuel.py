#!/usr/bin/env python3
"""Ingesteur reproductible : météo mensuelle ERA5 (CDS Copernicus), 142 localités, CIV.

Télécharge les **moyennes mensuelles ERA5** (réanalyse ECMWF, Copernicus C3S) du
Climate Data Store sur une boîte englobant la Côte d'Ivoire, extrait la valeur
du **point de grille 0,25° le plus proche** de chacune des 142 localités
(``points_nationaux``) et écrit un CSV gzip par grandeur
(``seeds/donnees/ecmwf_era5_<grandeur>_mensuel_civ142.csv.gz``, ADR-0015), que la
migration 0036 lit hors-ligne (les migrations n'accèdent jamais au réseau).

Contrats : ``kuma_data_core.db.seeds.meteo_era5_civ`` et
``docs/decisions/0021-meteo-era5-cds.md`` — source ``ecmwf_era5`` (id 2), méthode
``reanalyse``, confiance B, 1991-2025.

**Faits API** (jeu ``reanalysis-era5-single-levels-monthly-means``, produit
``monthly_averaged_reanalysis``, sondage du 2026-10-15) : netCDF sur grille
régulière 0,25°, dimension ``valid_time`` (1ᵉʳ du mois), coordonnée ``expver``
(``0001`` = ERA5 définitif, ``0005`` = ERA5T provisoire). Variables
``t2m`` (K), ``si10`` (m/s) et ``tp`` (mètres d'eau par jour).

**Conversions** (``VariableEra5.convertir``) : K − 273,15 → °C ; m/jour × 1000 →
mm/jour ; vent sans conversion. Aucune interpolation spatiale ni temporelle.

**Garde-fous** : unité servie conforme, mois complets et dans l'ordre (12 × années
du contrat), tous les mois en ERA5 définitif (``expver`` 0001 : aucune donnée
provisoire gravée), grille au pas de 0,25°, aucune valeur manquante à la maille
retenue, bornes du contrat (relecture par ``series_csv.lire_series``).

**Accès CDS (clé obligatoire)** : la clé personnelle Copernicus, la même que pour
l'ADS (ADR-0011), est lue dans la variable d'environnement ``ADS_API_KEY`` ; à
défaut dans ``~/.cdsapirc``. Les conditions d'utilisation d'ERA5 doivent avoir
été acceptées une fois sur le compte. Les netCDF bruts restent dans le cache
(``--cache``, hors dépôt) pour reprendre après une interruption.

Usage : ``ADS_API_KEY=... uv run python scripts/ingest_era5_cds_mensuel.py --cache .cache/era5_cds``
(mettre ``SSL_CERT_FILE`` si un proxy TLS d'entreprise intercepte la sortie).
"""

from __future__ import annotations

import argparse
import math
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cdsapi  # type: ignore[import-untyped]
import numpy as np
import xarray as xr

from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.meteo_era5_civ import (
    ANNEE_DEBUT_ERA5,
    ANNEE_FIN_ERA5,
    CONTRATS_METEO_ERA5_MENSUELS,
    LOT_METEO_ERA5,
    PAS_GRILLE_DEG,
    VARIABLES_ERA5,
    VariableEra5,
    maille_era5,
)
from kuma_data_core.db.seeds.series_csv import ecrire_series

DATASET = "reanalysis-era5-single-levels-monthly-means"
CDS_URL = "https://cds.climate.copernicus.eu/api"
ZONE: list[float] = [11.0, -9.0, 4.0, -2.0]  # N, O, S, E : CIV (4,42-10,49 N ; 8,42-2,78 O) + marge
EXPVER_DEFINITIF = "0001"
NB_MOIS = (ANNEE_FIN_ERA5 - ANNEE_DEBUT_ERA5 + 1) * 12
# Le CDS rejette les requêtes au-delà d'un quota de file par jeu de données
# (« Number queued requests … temporarily limited ») : on attend et on reprend.
ESSAIS = 30
ATTENTE_S = 60

Serie = tuple[str, float, float, list[tuple[int, int, float]]]


def _client() -> cdsapi.Client:
    """Client cdsapi sur le CDS : clé depuis ADS_API_KEY, repli ~/.cdsapirc."""
    cle = os.environ.get("ADS_API_KEY")
    if not cle:
        rc_path = os.path.expanduser("~/.cdsapirc")
        if not os.path.exists(rc_path):
            raise SystemExit(
                "Clé Copernicus absente : définir ADS_API_KEY (secret d'environnement) "
                "ou fournir ~/.cdsapirc. Cf. ADR-0021."
            )
        rc: dict[str, str] = {}
        with open(rc_path) as f:
            for line in f:
                if line.strip() and ":" in line:
                    k, v = line.split(":", 1)
                    rc[k.strip()] = v.strip()
        cle = rc["key"]
    return cdsapi.Client(url=CDS_URL, key=cle, quiet=True)


def _chemin_cache(cache: Path, variable: VariableEra5) -> Path:
    return cache / f"era5_mensuel_{variable.variable_cds}_{ANNEE_DEBUT_ERA5}_{ANNEE_FIN_ERA5}.nc"


def _telecharger_en_cache(variable: VariableEra5, cache: Path) -> Path:
    """Télécharge le netCDF d'une variable (1991-2025, boîte CIV), sauf s'il est valide en cache."""
    chemin = _chemin_cache(cache, variable)
    if chemin.exists():
        try:
            _lire_grille(chemin, variable)
            return chemin
        except (SystemExit, ValueError, OSError, KeyError):
            chemin.unlink()  # cache corrompu ou incomplet : on redemande
    requete = {
        "product_type": ["monthly_averaged_reanalysis"],
        "variable": [variable.variable_cds],
        "year": [str(a) for a in range(ANNEE_DEBUT_ERA5, ANNEE_FIN_ERA5 + 1)],
        "month": [f"{m:02d}" for m in range(1, 13)],
        "time": ["00:00"],
        "area": ZONE,
        "data_format": "netcdf",
        "download_format": "unarchived",
    }
    for essai in range(1, ESSAIS + 1):
        with tempfile.TemporaryDirectory(dir=cache) as tmp:
            partiel = Path(tmp) / chemin.name
            try:
                _client().retrieve(DATASET, requete, str(partiel))
            except Exception as erreur:  # file d'attente CDS saturée, coupure réseau…
                derniere = str(erreur).strip().splitlines()[-1] if str(erreur).strip() else ""
                print(f"{variable.variable_cds}: essai {essai} échoué ({derniere})", flush=True)
                time.sleep(ATTENTE_S)
                continue
            partiel.replace(chemin)
        _lire_grille(chemin, variable)
        return chemin
    raise SystemExit(f"{variable.variable_cds}: abandon après {ESSAIS} essais.")


def _lire_grille(
    chemin: Path, variable: VariableEra5
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[tuple[int, int]]]:
    """Valeurs brutes ``(mois, lat, lon)``, latitudes, longitudes et mois ``(année, mois)``."""
    with xr.open_dataset(chemin) as ds:
        da = ds[variable.nom_netcdf]
        if da.attrs.get("units") != variable.unite_source:
            raise SystemExit(
                f"{chemin.name} : unité {da.attrs.get('units')!r}, "
                f"{variable.unite_source!r} attendue."
            )
        temps = ds["valid_time"].values.astype("datetime64[M]").astype(int)
        mois = [(int(t) // 12 + 1970, int(t) % 12 + 1) for t in temps]
        attendus = [
            (a, m) for a in range(ANNEE_DEBUT_ERA5, ANNEE_FIN_ERA5 + 1) for m in range(1, 13)
        ]
        if mois != attendus:
            raise SystemExit(f"{chemin.name} : {len(mois)} mois servis, {NB_MOIS} attendus.")
        expver = {str(e) for e in np.atleast_1d(ds["expver"].values)} if "expver" in ds else set()
        if expver - {EXPVER_DEFINITIF}:
            raise SystemExit(f"{chemin.name} : données provisoires ERA5T (expver {expver}).")
        lats = ds["latitude"].values.astype(float)
        lons = ds["longitude"].values.astype(float)
        for axe in (lats, lons):
            if not np.allclose(np.abs(np.diff(axe)), PAS_GRILLE_DEG):
                raise SystemExit(f"{chemin.name} : grille hors pas {PAS_GRILLE_DEG}°.")
        valeurs = da.transpose("valid_time", "latitude", "longitude").values.astype(float)
    return valeurs, lats, lons, mois


def _indice(axe: np.ndarray, cible: float, chemin: Path) -> int:
    trouves = np.flatnonzero(np.isclose(axe, cible, atol=1e-6))
    if len(trouves) != 1:
        raise SystemExit(f"{chemin.name} : nœud {cible} absent de la grille servie.")
    return int(trouves[0])


def _extraire(
    chemin: Path, variable: VariableEra5, points: list[tuple[str, str, float, float]]
) -> list[Serie]:
    """Série convertie de chaque localité, à la maille 0,25° la plus proche."""
    valeurs, lats, lons, mois = _lire_grille(chemin, variable)
    series: list[Serie] = []
    for code, _, lat, lon in points:
        lat_n, lon_n = maille_era5(lat, lon)
        i, j = _indice(lats, lat_n, chemin), _indice(lons, lon_n, chemin)
        brut = valeurs[:, i, j]
        if not np.all(np.isfinite(brut)):
            raise SystemExit(f"{chemin.name} : valeur manquante à la maille de {code}.")
        mesures = [
            (annee, m, round(variable.convertir(float(v)), 4))
            for (annee, m), v in zip(mois, brut, strict=True)
        ]
        series.append((code, lat, lon, mesures))
    return series


def main(cache: Path, paralleles: int) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    points = points_nationaux()
    mailles = {maille_era5(lat, lon) for _, _, lat, lon in points}
    print(f"{len(points)} localités, {len(mailles)} mailles 0,25° distinctes")

    variables = list(VARIABLES_ERA5.values())
    with ThreadPoolExecutor(max_workers=paralleles) as pool:
        chemins = list(pool.map(lambda v: _telecharger_en_cache(v, cache), variables))
    for variable, chemin in zip(variables, chemins, strict=True):
        series = _extraire(chemin, variable, points)
        contrat = CONTRATS_METEO_ERA5_MENSUELS[variable.grandeur]
        cible = ecrire_series(contrat, LOT_METEO_ERA5, series)
        toutes = [v for _, _, _, m in series for _, _, v in m]
        moyenne = math.fsum(toutes) / len(toutes)
        print(
            f"{variable.grandeur}: {len(series)} séries × {NB_MOIS} mois -> {cible.name} "
            f"(min {min(toutes)}, moyenne {moyenne:.3f}, max {max(toutes)})"
        )


if __name__ == "__main__":
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--cache", type=Path, default=Path(".cache/era5_cds"))
    parseur.add_argument("--paralleles", type=int, default=2, help="requêtes CDS simultanées")
    args = parseur.parse_args()
    main(args.cache, args.paralleles)
