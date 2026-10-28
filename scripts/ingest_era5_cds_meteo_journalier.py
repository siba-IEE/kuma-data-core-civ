#!/usr/bin/env python3
"""Ingesteur reproductible : température et vent journaliers ERA5 (CDS), 142 localités, CIV.

Télécharge, pour chacun des **110 nœuds 0,25°** où tombent les 142 localités
(``points_nationaux``, mêmes nœuds que le mensuel 0036 et la pluie 0050), les
séries **horaires** ERA5 ``2m_temperature``, ``10m_u_component_of_wind`` et
``10m_v_component_of_wind`` (réanalyse ECMWF, Copernicus C3S) du 1991-01-01
00 h au 2025-12-31 23 h UTC, calcule la moyenne de chaque jour civil UTC et
écrit un CSV gzip par grandeur
(``seeds/donnees/ecmwf_era5_<grandeur>_journalier_civ142.csv.gz``, ADR-0015)
que la migration 0053 lit hors-ligne (les migrations n'accèdent jamais au
réseau).

Contrats : ``kuma_data_core.db.seeds.meteo_era5_journaliere_civ`` — source
``ecmwf_era5`` (id 2), méthode ``reanalyse``, confiance B, 1991-2025.

**Faits API** (jeu ``reanalysis-era5-single-levels-timeseries``, sondage du
2026-10-28) : une requête par nœud pour les trois variables, plage de dates
d'un seul tenant, archive zip d'un netCDF : dimension ``valid_time`` horaire,
coordonnées scalaires ``latitude`` et ``longitude`` du nœud servi, variables
``t2m`` (K), ``u10`` et ``v10`` (m s**-1).

**Jour** (``meteo_era5_journaliere_civ``) : moyenne des 24 valeurs horaires
instantanées datées de 00 h à 23 h du jour J ; vent : moyenne des vitesses
horaires √(u² + v²).

**Garde-fous** : unités servies, nœud servi = nœud demandé, axe horaire continu
couvrant toute la période, aucune valeur manquante, bornes du contrat
(relecture par ``series_csv.lire_series_journalieres``). La moyenne des jours
de chaque mois est comparée au mensuel ERA5 gravé (CSV de 0036) : l'écart est
publié et le script échoue au-delà de ``TOLERANCES_MENSUEL``.

**Accès CDS (clé obligatoire)** : la clé personnelle Copernicus, la même que pour
l'ADS (ADR-0011), est lue dans la variable d'environnement ``ADS_API_KEY`` ; à
défaut dans ``~/.cdsapirc``. Requêtes simultanées limitées (``--paralleles``),
reprise après refus. Les netCDF bruts restent dans le cache (``--cache``, hors
dépôt), un sous-dossier par nœud, chaque téléchargement dans un sous-dossier
temporaire vide. Lecture netCDF sérialisée (bibliothèque non sûre entre
threads) ; à lancer avec ``python -I`` sur des fichiers téléchargés.

Usage : ``ADS_API_KEY=... uv run python -I scripts/ingest_era5_cds_meteo_journalier.py --cache .cache/era5_cds_meteo_jour``
"""

from __future__ import annotations

import argparse
import math
import os
import tempfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

import cdsapi  # type: ignore[import-untyped]
import numpy as np
import xarray as xr

from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.meteo_era5_civ import (
    CONTRATS_METEO_ERA5_MENSUELS,
    LOT_METEO_ERA5,
    maille_era5,
)
from kuma_data_core.db.seeds.meteo_era5_journaliere_civ import (
    CONTRATS_METEO_ERA5_JOURNALIERS,
    GRANDEURS_ERA5_JOURNALIERES,
    HEURES_PAR_JOUR,
    JEU_CDS,
    LOT_METEO_ERA5_JOURNALIERE,
    UNITES_SOURCE,
    VARIABLES_CDS,
    temperature_journaliere_c,
    vent_journalier,
)
from kuma_data_core.db.seeds.series_csv import (
    ecrire_series_journalieres,
    lire_series,
    nb_jours,
)

CONTRAT = CONTRATS_METEO_ERA5_JOURNALIERS["t2m"]
CDS_URL = "https://cds.climate.copernicus.eu/api"
PREMIER_JOUR = date(CONTRAT.annee_debut, 1, 1)
NB_JOURS = nb_jours(CONTRAT)
DEBUT_HORAIRE = datetime(CONTRAT.annee_debut, 1, 1)
NB_HEURES = NB_JOURS * HEURES_PAR_JOUR
PLAGE = f"{PREMIER_JOUR.isoformat()}/{date(CONTRAT.annee_fin, 12, 31).isoformat()}"
# Écart maximal toléré entre la moyenne des jours d'un mois et le mensuel 0036.
TOLERANCES_MENSUEL: dict[str, float] = {"t2m": 0.01, "vent_10m": 0.01}
ESSAIS = 30
ATTENTE_S = 60
FILE_PLEINE = "Maximum number queued requests"
"""Refus du Copernicus quand la file de l'utilisateur est pleine : pas un échec."""
TAILLE_MAX_NC = 50 * 1024 * 1024  # un nœud sur 1991-2025 pèse environ 4 Mo
VERROU_NETCDF = threading.Lock()  # la bibliothèque netCDF n'est pas sûre entre threads

Noeud = tuple[float, float]
Serie = tuple[str, float, float, list[tuple[date, float]]]


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


def _nom_noeud(noeud: Noeud) -> str:
    return f"{noeud[0]:+06.2f}_{noeud[1]:+07.2f}"


def _chemin_cache(cache: Path, noeud: Noeud) -> Path:
    nom = _nom_noeud(noeud)
    return (
        cache / nom / f"era5_horaire_t2m_u10_v10_{nom}_{CONTRAT.annee_debut}_{CONTRAT.annee_fin}.nc"
    )


def _extraire_netcdf(archive: Path, cible: Path) -> None:
    """Extrait l'unique netCDF de l'archive zip servie, sous un nom fixé (rien d'autre)."""
    if not zipfile.is_zipfile(archive):
        archive.replace(cible)  # netCDF servi sans archive
        return
    with zipfile.ZipFile(archive) as zf:
        membres = [m for m in zf.infolist() if not m.is_dir()]
        if len(membres) != 1 or not membres[0].filename.endswith(".nc"):
            raise SystemExit(f"{archive.name} : {[m.filename for m in membres]!r}, un .nc attendu.")
        if membres[0].file_size > TAILLE_MAX_NC:
            raise SystemExit(f"{archive.name} : membre de {membres[0].file_size} octets, refusé.")
        cible.write_bytes(zf.read(membres[0]))


def _lire_horaire(chemin: Path, noeud: Noeud) -> dict[str, np.ndarray]:
    """Valeurs horaires (unités servies) du nœud, de DEBUT_HORAIRE à NB_HEURES heures plus tard."""
    sortie: dict[str, np.ndarray] = {}
    with VERROU_NETCDF, xr.open_dataset(chemin, engine="netcdf4") as ds:
        servi = (float(ds["latitude"].values), float(ds["longitude"].values))
        if not np.allclose(servi, noeud, atol=1e-6):
            raise SystemExit(f"{chemin.name} : nœud servi {servi}, {noeud} demandé.")
        heures = ds["valid_time"].values.astype("datetime64[h]")
        attendu = np.datetime64(DEBUT_HORAIRE, "h") + np.arange(NB_HEURES)
        if heures.shape != attendu.shape or not np.array_equal(heures, attendu):
            raise SystemExit(
                f"{chemin.name} : {heures.size} heures servies, {NB_HEURES} attendues."
            )
        for nom, unite in UNITES_SOURCE.items():
            da = ds[nom]
            if da.attrs.get("units") != unite:
                raise SystemExit(
                    f"{chemin.name} : {nom} en {da.attrs.get('units')!r}, {unite!r} attendue."
                )
            sortie[nom] = da.values.astype(float).ravel()
    for nom, valeurs in sortie.items():
        if valeurs.size != NB_HEURES or not np.all(np.isfinite(valeurs)):
            raise SystemExit(f"{chemin.name} : valeur manquante ({nom}).")
    return sortie


def _telecharger_en_cache(noeud: Noeud, cache: Path) -> Path:
    """Télécharge les séries horaires d'un nœud (1991-2025), sauf si elles sont valides en cache."""
    chemin = _chemin_cache(cache, noeud)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    if chemin.exists():
        try:
            _lire_horaire(chemin, noeud)
            return chemin
        except (SystemExit, ValueError, OSError, KeyError):
            chemin.unlink()  # cache corrompu ou incomplet : on redemande
    requete = {
        "variable": list(VARIABLES_CDS),
        "location": {"longitude": noeud[1], "latitude": noeud[0]},
        "date": [PLAGE],
        "data_format": "netcdf",
    }
    essai = 0
    while essai < ESSAIS:
        with tempfile.TemporaryDirectory(dir=chemin.parent) as tmp:
            partiel = Path(tmp) / "reponse.zip"
            try:
                _client().retrieve(JEU_CDS, requete, str(partiel))
            except Exception as erreur:  # file d'attente CDS saturée, coupure réseau…
                derniere = str(erreur).strip().splitlines()[-1] if str(erreur).strip() else ""
                if FILE_PLEINE not in derniere:  # file pleine : on attend son tour
                    essai += 1
                    print(f"{_nom_noeud(noeud)}: essai {essai} échoué ({derniere})", flush=True)
                time.sleep(ATTENTE_S)
                continue
            extrait = Path(tmp) / chemin.name
            _extraire_netcdf(partiel, extrait)
            extrait.replace(chemin)
        _lire_horaire(chemin, noeud)
        print(f"{_nom_noeud(noeud)}: téléchargé", flush=True)
        return chemin
    raise SystemExit(f"{_nom_noeud(noeud)}: abandon après {ESSAIS} essais.")


def _moyennes_journalieres(chemin: Path, noeud: Noeud) -> dict[str, list[tuple[date, float]]]:
    """Moyenne de chaque jour civil UTC (heures 00 h → 23 h) : t2m en °C, vent en m/s."""
    h = _lire_horaire(chemin, noeud)
    t2m, u10, v10 = (h[n].reshape(NB_JOURS, HEURES_PAR_JOUR) for n in ("t2m", "u10", "v10"))
    jours = [PREMIER_JOUR + timedelta(days=i) for i in range(NB_JOURS)]
    return {
        "t2m": [(j, temperature_journaliere_c(t2m[i].tolist())) for i, j in enumerate(jours)],
        "vent_10m": [
            (j, vent_journalier(u10[i].tolist(), v10[i].tolist())) for i, j in enumerate(jours)
        ],
    }


def _comparer_au_mensuel(grandeur: str, series: list[Serie]) -> None:
    """Moyenne des jours de chaque mois (valeurs du CSV) - mensuel ERA5 gravé (0036)."""
    mensuel = {
        s["localite_code"]: {(a, m): v for a, m, v in s["mesures"]}
        for s in lire_series(CONTRATS_METEO_ERA5_MENSUELS[grandeur], LOT_METEO_ERA5)
    }
    ecarts: list[tuple[float, str, int, int]] = []
    for code, _, _, mesures in series:
        par_mois: dict[tuple[int, int], list[float]] = {}
        for jour, v in mesures:
            par_mois.setdefault((jour.year, jour.month), []).append(round(v, 4))
        for (annee, mois), valeurs in par_mois.items():
            ecart = math.fsum(valeurs) / len(valeurs) - mensuel[code][(annee, mois)]
            ecarts.append((ecart, code, annee, mois))
    absolus = sorted(abs(e[0]) for e in ecarts)
    pire = max(ecarts, key=lambda e: abs(e[0]))
    print(
        f"{grandeur} : moyenne des jours - mensuel 0036 ({len(ecarts)} mois) : "
        f"moyen {math.fsum(e[0] for e in ecarts) / len(ecarts):+.6f}, médian |écart| "
        f"{absolus[len(absolus) // 2]:.6f}, max {abs(pire[0]):.6f} "
        f"({pire[1]} {pire[2]}-{pire[3]:02d})"
    )
    if abs(pire[0]) > TOLERANCES_MENSUEL[grandeur]:
        raise SystemExit(
            f"{grandeur} : écart au mensuel 0036 au-delà de {TOLERANCES_MENSUEL[grandeur]} : {pire}."
        )


def main(cache: Path, paralleles: int) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    points = points_nationaux()
    noeuds = sorted({maille_era5(lat, lon) for _, _, lat, lon in points})
    print(f"{len(points)} localités, {len(noeuds)} mailles 0,25° distinctes, {PLAGE}")

    with ThreadPoolExecutor(max_workers=paralleles) as pool:
        telecharges = pool.map(lambda n: _telecharger_en_cache(n, cache), noeuds)
        chemins = dict(zip(noeuds, telecharges, strict=True))
    moyennes = {n: _moyennes_journalieres(chemins[n], n) for n in noeuds}
    for grandeur in GRANDEURS_ERA5_JOURNALIERES:
        contrat = CONTRATS_METEO_ERA5_JOURNALIERS[grandeur]
        series: list[Serie] = [
            (code, lat, lon, moyennes[maille_era5(lat, lon)][grandeur])
            for code, _, lat, lon in points
        ]
        cible = ecrire_series_journalieres(contrat, LOT_METEO_ERA5_JOURNALIERE, series)
        toutes = [round(v, 4) for _, _, _, m in series for _, v in m]
        print(
            f"{grandeur}: {len(series)} séries × {NB_JOURS} jours -> {cible.name} "
            f"(min {min(toutes)}, moyenne {math.fsum(toutes) / len(toutes):.3f}, max {max(toutes)})"
        )
        _comparer_au_mensuel(grandeur, series)


if __name__ == "__main__":
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--cache", type=Path, default=Path(".cache/era5_cds_meteo_jour"))
    parseur.add_argument("--paralleles", type=int, default=2, help="requêtes CDS simultanées")
    args = parseur.parse_args()
    main(args.cache, args.paralleles)
