#!/usr/bin/env python3
"""Ingesteur reproductible : pluie journalière CHIRPS v3.0 (rnl), 142 localités, CIV.

Lit, pour chaque jour du 1991-01-01 au 2025-12-31, la fenêtre ivoirienne du
COG quasi global CHIRPS v3.0 final ``rnl`` du Climate Hazards Center (UCSB),
garde la valeur de la maille de 0,05° qui contient chacune des 142 localités
(``points_nationaux``, 122 mailles distinctes ; règle de rattachement :
``pluie_chirps_civ.maille_chirps``) et écrit un CSV gzip
(``seeds/donnees/chirps_precipitation_journalier_civ142.csv.gz``, ADR-0015) que
la migration 0055 lit hors-ligne (les migrations n'accèdent jamais au réseau).

Contrat : ``kuma_data_core.db.seeds.pluie_chirps_civ`` — source ``chirps``
(id 18), méthode ``modele_satellitaire``, confiance B, 1991-2025.

**Lecture** : GDAL ``/vsicurl/`` par requêtes HTTP d'une plage d'octets
chacune (en-tête et deux tuiles de 512 × 512 mailles par jour, environ 260 Kio) ;
aucun fichier complet n'est téléchargé. Le serveur refuse les rafales et les
requêtes à plusieurs plages (HTTP 403) : peu de lectures simultanées, nouvelles
tentatives espacées. Les valeurs extraites sont mises en cache par année
(``--cache``, hors dépôt, un tableau ``float32`` par année) : régénérer depuis
le cache redonne les mêmes octets.

**Garde-fous** :

- grille servie conforme (7 200 × 2 400, pas de 0,05°, origine 180° O / 60° N,
  ``float32``) ;
- aucune maille océan (−9999), valeur négative ou non finie aux mailles
  retenues, tous les jours de la période ;
- un jour par an, la même fenêtre lue dans le GeoTIFF du même jour doit être
  identique, maille par maille, à celle du COG ;
- la somme des jours de chaque mois est comparée au CHIRPS v3.0 **mensuel**
  (``monthly/global/cogs``), produit de référence fondu avec les stations ;
  l'écart est publié et le script échoue au-delà de ``TOLERANCE_MENSUEL`` ;
- bornes du contrat (relecture par ``series_csv.lire_series_journalieres``).

Dépendance : ``rasterio`` (groupe ``dev``). Fichiers distants non fiables : à
lancer avec ``python -I``.

Usage : ``uv run python -I scripts/ingest_chirps_journalier.py --cache .cache/chirps``
"""

from __future__ import annotations

import argparse
import math
import os
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

# Options GDAL lues à l'initialisation : pas de listage des dossiers distants,
# extensions .cog autorisées, une plage d'octets par requête (le serveur du CHC
# refuse les requêtes à plusieurs plages, HTTP 403), plages contiguës fusionnées,
# pas de cache : sans ``CPL_VSIL_CURL_NON_CACHED``, GDAL garde en mémoire l'échec
# d'une lecture et toutes les nouvelles tentatives sur la même URL échouent.
os.environ.update(
    {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "CPL_VSIL_CURL_NON_CACHED": "/vsicurl/https://data.chc.ucsb.edu/",
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".cog,.tif",
        "GDAL_HTTP_MULTIRANGE": "SERIAL",
        "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
        "GDAL_HTTP_MAX_RETRY": "5",
        "GDAL_HTTP_RETRY_DELAY": "3",
        "VSI_CACHE": "FALSE",
    }
)

import numpy as np
import rasterio  # type: ignore[import-untyped]
from rasterio.windows import Window  # type: ignore[import-untyped]

from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.pluie_chirps_civ import (
    CONTRAT_PLUIE_CHIRPS,
    HAUTEUR,
    LARGEUR,
    LATITUDE_NORD,
    LONGITUDE_OUEST,
    LOT_PLUIE_CHIRPS,
    PAS_DEG,
    VALEUR_OCEAN,
    maille_chirps,
    url_cog,
    url_tif,
)
from kuma_data_core.db.seeds.series_csv import ecrire_series_journalieres

CONTRAT = CONTRAT_PLUIE_CHIRPS
URL_MENSUEL = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/monthly/global/cogs"
TOLERANCE_MENSUEL = 0.05  # mm/mois : somme des jours - CHIRPS mensuel
MOIS_INCOHERENTS: frozenset[tuple[int, int]] = frozenset({(2000, 2)})
"""Mois où le journalier CHIRPS v3 ne redonne pas le mensuel (constat du 2026-10-28) :
en février 2000, 5 des 121 mailles diffèrent (jusqu'à 4,1 mm), les jours 21 à 29
portant de la pluie où le mensuel est nul, ou l'inverse. Publié, non corrigé."""
# Le serveur du CHC refuse (HTTP 403) les rafales de requêtes : lectures une à
# une, pause entre deux jours, nouvelles tentatives de plus en plus espacées.
ESSAIS = 15
ATTENTE_S = 60

Maille = tuple[int, int]


def _fenetre(mailles: list[Maille]) -> Window:
    lignes = [m[0] for m in mailles]
    colonnes = [m[1] for m in mailles]
    return Window(
        min(colonnes), min(lignes), max(colonnes) - min(colonnes) + 1, max(lignes) - min(lignes) + 1
    )


def _controler_grille(ds: rasterio.DatasetReader, url: str) -> None:
    t = ds.transform
    conforme = (
        (ds.width, ds.height, ds.count, ds.dtypes[0]) == (LARGEUR, HAUTEUR, 1, "float32")
        and math.isclose(t.a, float(PAS_DEG), rel_tol=1e-6)
        and math.isclose(t.e, -float(PAS_DEG), rel_tol=1e-6)
        and t.b == 0
        and t.d == 0
        and math.isclose(t.c, LONGITUDE_OUEST, abs_tol=1e-9)
        and math.isclose(t.f, LATITUDE_NORD, abs_tol=1e-9)
    )
    if not conforme:
        raise SystemExit(f"{url} : grille inattendue ({ds.width}×{ds.height}, {t}).")


def _lire(url: str, fenetre: Window, controler: bool = False) -> np.ndarray:
    for essai in range(1, ESSAIS + 1):
        try:
            with rasterio.open("/vsicurl/" + url) as ds:
                if controler:
                    _controler_grille(ds, url)
                return ds.read(1, window=fenetre)
        except rasterio.errors.RasterioIOError as erreur:
            print(f"{url.rsplit('/', 1)[-1]} : essai {essai} échoué ({erreur})", flush=True)
            time.sleep(ATTENTE_S * min(essai, 8))
    raise SystemExit(f"{url} : abandon après {ESSAIS} essais.")


def _valeurs(bloc: np.ndarray, fenetre: Window, mailles: list[Maille], url: str) -> np.ndarray:
    vals = np.array(
        [bloc[ligne - fenetre.row_off, col - fenetre.col_off] for ligne, col in mailles],
        dtype=np.float32,
    )
    if np.any(vals == VALEUR_OCEAN) or not np.all(np.isfinite(vals)) or np.any(vals < 0):
        raise SystemExit(f"{url} : maille océan, négative ou non finie : {vals.tolist()!r}.")
    return vals


def _annee(
    annee: int, mailles: list[Maille], fenetre: Window, cache: Path, paralleles: int, pause: float
) -> np.ndarray:
    """Valeurs (jours × mailles) d'une année, depuis le cache ou les COG distants."""
    chemin = cache / f"chirps_v3_rnl_{annee}.npy"
    jours = [
        date(annee, 1, 1) + timedelta(days=i)
        for i in range((date(annee + 1, 1, 1) - date(annee, 1, 1)).days)
    ]
    if chemin.exists():
        tableau = np.load(chemin, allow_pickle=False)
        if tableau.shape == (len(jours), len(mailles)) and tableau.dtype == np.float32:
            return tableau
        chemin.unlink()

    def jour(j: date) -> np.ndarray:
        url = url_cog(j)
        valeurs = _valeurs(_lire(url, fenetre, controler=j.day == 1), fenetre, mailles, url)
        time.sleep(pause)
        return valeurs

    with ThreadPoolExecutor(max_workers=paralleles) as pool:
        tableau = np.stack(list(pool.map(jour, jours)))
    # Témoin : un jour par an, le GeoTIFF doit donner exactement les mêmes valeurs.
    temoin = jours[(annee * 37) % len(jours)]
    cog = tableau[jours.index(temoin)]
    tif = _valeurs(_lire(url_tif(temoin), fenetre), fenetre, mailles, url_tif(temoin))
    if not np.array_equal(cog, tif):
        raise SystemExit(f"{temoin} : COG et GeoTIFF diffèrent.")
    temporaire = chemin.with_suffix(".tmp.npy")
    np.save(temporaire, tableau, allow_pickle=False)
    temporaire.replace(chemin)
    print(f"{annee} : {len(jours)} jours, témoin {temoin} identique au GeoTIFF", flush=True)
    return tableau


def _comparer_au_mensuel(
    jours: list[date], valeurs: np.ndarray, mailles: list[Maille], fenetre: Window, cache: Path
) -> None:
    """Somme des jours de chaque mois - CHIRPS v3.0 mensuel, maille par maille."""
    chemin = cache / "chirps_v3_mensuel.npy"
    mois = sorted({(j.year, j.month) for j in jours})
    if chemin.exists():
        mensuel = np.load(chemin, allow_pickle=False)
    else:

        def lire_mois(am: tuple[int, int]) -> np.ndarray:
            url = f"{URL_MENSUEL}/chirps-v3.0.{am[0]}.{am[1]:02d}.cog"
            return _valeurs(_lire(url, fenetre), fenetre, mailles, url)

        mensuel = np.stack([lire_mois(am) for am in mois])
        np.save(chemin, mensuel, allow_pickle=False)
    index: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, j in enumerate(jours):
        index[(j.year, j.month)].append(i)
    ecarts = np.stack(
        [
            valeurs[index[am]].astype(np.float64).sum(axis=0) - mensuel[k]
            for k, am in enumerate(mois)
        ]
    )
    for k, am in enumerate(mois):
        if am in MOIS_INCOHERENTS:
            hors = np.flatnonzero(np.abs(ecarts[k]) > TOLERANCE_MENSUEL)
            print(
                f"{am[0]}-{am[1]:02d} (incohérence connue) : {hors.size} mailles, "
                + ", ".join(
                    f"{mailles[c]} jours {ecarts[k, c] + mensuel[k, c]:.3f} / mensuel "
                    f"{mensuel[k, c]:.3f}"
                    for c in hors
                )
            )
    autres = np.array([am not in MOIS_INCOHERENTS for am in mois])
    ecarts = ecarts[autres]
    pire = np.unravel_index(np.argmax(np.abs(ecarts)), ecarts.shape)
    print(
        f"somme des jours - CHIRPS mensuel, hors mois incohérents ({ecarts.size} "
        f"mois-mailles) : moyen {ecarts.mean():+.6f}, médian |écart| "
        f"{np.median(np.abs(ecarts)):.6f}, max {abs(ecarts[pire]):.6f} mm/mois"
    )
    if abs(ecarts[pire]) > TOLERANCE_MENSUEL:
        raise SystemExit(f"Écart au mensuel CHIRPS au-delà de {TOLERANCE_MENSUEL} mm/mois.")


def main(cache: Path, paralleles: int, pause: float) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    points = points_nationaux()
    maille_de = {code: maille_chirps(lat, lon) for code, _, lat, lon in points}
    mailles = sorted(set(maille_de.values()))
    fenetre = _fenetre(mailles)
    print(f"{len(points)} localités, {len(mailles)} mailles de 0,05° distinctes, fenêtre {fenetre}")

    annees = range(CONTRAT.annee_debut, CONTRAT.annee_fin + 1)
    valeurs = np.concatenate(
        [_annee(a, mailles, fenetre, cache, paralleles, pause) for a in annees]
    )
    jours = [date(CONTRAT.annee_debut, 1, 1) + timedelta(days=i) for i in range(valeurs.shape[0])]
    if jours[-1] != date(CONTRAT.annee_fin, 12, 31):
        raise SystemExit(f"Dernier jour lu {jours[-1]}, {CONTRAT.annee_fin}-12-31 attendu.")
    _comparer_au_mensuel(jours, valeurs, mailles, fenetre, cache)

    colonne = {m: k for k, m in enumerate(mailles)}
    series = [
        (
            code,
            lat,
            lon,
            list(zip(jours, valeurs[:, colonne[maille_de[code]]].tolist(), strict=True)),
        )
        for code, _, lat, lon in points
    ]
    cible = ecrire_series_journalieres(CONTRAT, LOT_PLUIE_CHIRPS, series)
    toutes = valeurs.astype(np.float64)
    print(
        f"precipitation: {len(series)} séries × {len(jours)} jours -> {cible.name} "
        f"(min {toutes.min():.4f}, moyenne {toutes.mean():.3f}, max {toutes.max():.4f})"
    )


if __name__ == "__main__":
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--cache", type=Path, default=Path(".cache/chirps"))
    parseur.add_argument("--paralleles", type=int, default=1, help="lectures HTTP simultanées")
    parseur.add_argument("--pause", type=float, default=0.5, help="secondes entre deux jours")
    args = parseur.parse_args()
    main(args.cache, args.paralleles, args.pause)
