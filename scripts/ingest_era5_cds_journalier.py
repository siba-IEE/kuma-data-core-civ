#!/usr/bin/env python3
"""Ingesteur reproductible : pluie journalière ERA5 (CDS Copernicus), 142 localités, CIV.

Télécharge, pour chacun des **110 nœuds 0,25°** où tombent les 142 localités
(``points_nationaux``, mêmes nœuds que le mensuel 0036), la série **horaire**
ERA5 de ``total_precipitation`` (réanalyse ECMWF, Copernicus C3S) du
1991-01-01 00 h au 2026-01-01 23 h UTC, la somme sur chaque jour civil UTC et
écrit un CSV gzip
(``seeds/donnees/ecmwf_era5_precipitation_journalier_civ142.csv.gz``, ADR-0015)
que la migration 0050 lit hors-ligne (les migrations n'accèdent jamais au
réseau).

Contrat : ``kuma_data_core.db.seeds.pluie_era5_journaliere_civ`` — source
``ecmwf_era5`` (id 2), méthode ``reanalyse``, confiance B, 1991-2025.

**Faits API** (jeu ``reanalysis-era5-single-levels-timeseries``, sondage du
2026-10-15) : une requête par point (``location`` = nœud exact, sinon le CDS
prend le nœud le plus proche), plage de dates d'un seul tenant, archive zip d'un
netCDF : dimension ``valid_time`` horaire, coordonnées scalaires ``latitude`` et
``longitude`` du nœud servi, variable ``tp`` en mètres. 30 s à 2 min par requête
selon la file, 3,7 Mo par nœud. **Mêmes valeurs, à l'octet près, que le jeu
horaire sur grille** ``reanalysis-era5-single-levels`` (ERA5 définitif,
``expver`` 0001) : vérifié le 2026-10-15 aux 110 nœuds sur 5 904 heures
chacun (2000-10 et 2000-11, 2019-03 et 2019-04, 2022-08 à 2022-10, 2025-12, le
2026-01-01), soit 649 440 valeurs identiques.

**Cumul du jour** (``cumul_journalier_mm``) : un cumul horaire ERA5 daté HH
couvre l'heure qui finit à HH ; le jour J somme les 24 cumuls datés de 01 h (J)
à 00 h (J + 1), soit le jour civil UTC, local en Côte d'Ivoire (UTC+0). Somme
exacte (``math.fsum``) en mètres, × 1000 → mm/jour, arrondi à 4 décimales à
l'écriture. Aucune interpolation spatiale ni temporelle, aucune valeur bouchée.
C'est la convention du produit dérivé ``derived-era5-single-levels-daily-statistics``
(``daily_sum``, ``utc+00:00`` : décalage d'une heure pour les variables
cumulées, documentation ECMWF), non retenu : une année par requête, calculée à
la demande, encore en file après une heure au sondage.

**Garde-fous** : unité servie, nœud servi = nœud demandé, axe horaire continu
couvrant toute la période, aucune valeur manquante ni négative, bornes du
contrat (relecture par ``series_csv.lire_series_journalieres``). La moyenne des
jours de chaque mois est comparée au mensuel ERA5 gravé (CSV de 0036) : hors
mois de raccord entre expériences de production ERA5
(``MOIS_TRANSITION_ERA5``), l'écart ne dépasse pas 0,0036 mm/jour (57 226 mois)
et le script échoue au-delà de ``TOLERANCE_MENSUEL`` ; un calage 00 h → 23 h le
porterait à 0,48 mm/jour. Dans 13 des 17 mois de raccord, le mensuel du CDS
s'écarte de la somme des cumuls horaires jusqu'à 0,39 mm/jour (Tengréla,
1995-09) : incohérence entre produits ERA5 du CDS, constatée aussi sur le jeu
horaire sur grille (2019-03, 2000-10), non corrigée.

**Accès CDS (clé obligatoire)** : la clé personnelle Copernicus, la même que pour
l'ADS (ADR-0011), est lue dans la variable d'environnement ``ADS_API_KEY`` ; à
défaut dans ``~/.cdsapirc``. Le CDS limite les requêtes en file par jeu de
données : 2 requêtes simultanées au plus, reprise après refus. Les netCDF bruts
restent dans le cache (``--cache``, hors dépôt), un sous-dossier par nœud, chaque
téléchargement dans un sous-dossier temporaire vide : régénérer depuis le cache
redonne les mêmes octets. Lecture netCDF sérialisée (bibliothèque non sûre
entre threads) ; à lancer avec ``python -I`` sur des fichiers téléchargés.

Usage : ``ADS_API_KEY=... uv run python -I scripts/ingest_era5_cds_journalier.py --cache .cache/era5_cds_jour``
(mettre ``SSL_CERT_FILE`` si un proxy TLS d'entreprise intercepte la sortie).
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
from kuma_data_core.db.seeds.pluie_era5_journaliere_civ import (
    CONTRAT_PLUIE_ERA5_JOURNALIERE,
    DECALAGE_HEURES,
    HEURES_PAR_JOUR,
    JEU_CDS,
    LOT_PLUIE_ERA5_JOURNALIERE,
    MOIS_TRANSITION_ERA5,
    NOM_NETCDF,
    UNITE_SOURCE,
    VARIABLE_CDS,
    cumul_journalier_mm,
)
from kuma_data_core.db.seeds.series_csv import (
    ecrire_series_journalieres,
    lire_series,
    nb_jours,
)

CONTRAT = CONTRAT_PLUIE_ERA5_JOURNALIERE
CDS_URL = "https://cds.climate.copernicus.eu/api"
PREMIER_JOUR = date(CONTRAT.annee_debut, 1, 1)
NB_JOURS = nb_jours(CONTRAT)
# Heures servies : du premier jour 00 h au lendemain du dernier jour, 23 h inclus.
DEBUT_HORAIRE = datetime(CONTRAT.annee_debut, 1, 1)
NB_HEURES = (NB_JOURS + 1) * HEURES_PAR_JOUR
PLAGE = f"{PREMIER_JOUR.isoformat()}/{date(CONTRAT.annee_fin + 1, 1, 1).isoformat()}"
TOLERANCE_MENSUEL = 0.004  # mm/jour : moyenne des jours - mensuel 0036, hors raccords ERA5
ESSAIS = 30
ATTENTE_S = 60
TAILLE_MAX_NC = 50 * 1024 * 1024  # un nœud sur 1991-2025 pèse environ 3,7 Mo
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
        cache
        / nom
        / f"era5_horaire_{VARIABLE_CDS}_{nom}_{CONTRAT.annee_debut}_{CONTRAT.annee_fin}.nc"
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


def _lire_horaire(chemin: Path, noeud: Noeud) -> np.ndarray:
    """Cumuls horaires (m) du nœud, de DEBUT_HORAIRE à NB_HEURES heures plus tard ; contrôles."""
    with VERROU_NETCDF, xr.open_dataset(chemin, engine="netcdf4") as ds:
        da = ds[NOM_NETCDF]
        if da.attrs.get("units") != UNITE_SOURCE:
            raise SystemExit(
                f"{chemin.name} : unité {da.attrs.get('units')!r}, {UNITE_SOURCE!r} attendue."
            )
        servi = (float(ds["latitude"].values), float(ds["longitude"].values))
        if not np.allclose(servi, noeud, atol=1e-6):
            raise SystemExit(f"{chemin.name} : nœud servi {servi}, {noeud} demandé.")
        heures = ds["valid_time"].values.astype("datetime64[h]")
        attendu = np.datetime64(DEBUT_HORAIRE, "h") + np.arange(NB_HEURES)
        if heures.shape != attendu.shape or not np.array_equal(heures, attendu):
            raise SystemExit(
                f"{chemin.name} : {heures.size} heures servies, {NB_HEURES} attendues."
            )
        valeurs = da.values.astype(float).ravel()
    if valeurs.size != NB_HEURES or not np.all(np.isfinite(valeurs)):
        raise SystemExit(f"{chemin.name} : valeur manquante.")
    if np.any(valeurs < 0):
        raise SystemExit(f"{chemin.name} : cumul horaire négatif.")
    return valeurs


def _telecharger_en_cache(noeud: Noeud, cache: Path) -> Path:
    """Télécharge la série horaire d'un nœud (1991-2025), sauf si elle est valide en cache."""
    chemin = _chemin_cache(cache, noeud)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    if chemin.exists():
        try:
            _lire_horaire(chemin, noeud)
            return chemin
        except (SystemExit, ValueError, OSError, KeyError):
            chemin.unlink()  # cache corrompu ou incomplet : on redemande
    requete = {
        "variable": [VARIABLE_CDS],
        "location": {"longitude": noeud[1], "latitude": noeud[0]},
        "date": [PLAGE],
        "data_format": "netcdf",
    }
    for essai in range(1, ESSAIS + 1):
        with tempfile.TemporaryDirectory(dir=chemin.parent) as tmp:
            partiel = Path(tmp) / "reponse.zip"
            try:
                _client().retrieve(JEU_CDS, requete, str(partiel))
            except Exception as erreur:  # file d'attente CDS saturée, coupure réseau…
                derniere = str(erreur).strip().splitlines()[-1] if str(erreur).strip() else ""
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


def _cumuls_journaliers(chemin: Path, noeud: Noeud) -> list[tuple[date, float]]:
    """Cumul de chaque jour civil UTC (mm/jour), heures datées 01 h (J) → 00 h (J + 1)."""
    horaire = _lire_horaire(chemin, noeud)
    par_jour = horaire[DECALAGE_HEURES : DECALAGE_HEURES + NB_JOURS * HEURES_PAR_JOUR].reshape(
        NB_JOURS, HEURES_PAR_JOUR
    )
    return [
        (PREMIER_JOUR + timedelta(days=i), cumul_journalier_mm(par_jour[i].tolist()))
        for i in range(NB_JOURS)
    ]


def _comparer_au_mensuel(series: list[Serie]) -> None:
    """Moyenne des jours de chaque mois (valeurs du CSV) - mensuel ERA5 gravé (0036)."""
    mensuel = {
        s["localite_code"]: {(a, m): v for a, m, v in s["mesures"]}
        for s in lire_series(CONTRATS_METEO_ERA5_MENSUELS["precipitation"], LOT_METEO_ERA5)
    }
    ecarts: dict[bool, list[tuple[float, str, int, int]]] = {False: [], True: []}
    for code, _, _, mesures in series:
        par_mois: dict[tuple[int, int], list[float]] = {}
        for jour, v in mesures:
            par_mois.setdefault((jour.year, jour.month), []).append(round(v, 4))
        for (annee, mois), valeurs in par_mois.items():
            ecart = math.fsum(valeurs) / len(valeurs) - mensuel[code][(annee, mois)]
            ecarts[(annee, mois) in MOIS_TRANSITION_ERA5].append((ecart, code, annee, mois))
    for transition, liste in ecarts.items():
        absolus = sorted(abs(e[0]) for e in liste)
        pire = max(liste, key=lambda e: abs(e[0]))
        print(
            f"moyenne des jours - mensuel 0036, "
            f"{'mois de transition ERA5' if transition else 'autres mois'} ({len(liste)}) : "
            f"moyen {math.fsum(e[0] for e in liste) / len(liste):+.6f}, médian |écart| "
            f"{absolus[len(absolus) // 2]:.6f}, max {abs(pire[0]):.6f} mm/jour "
            f"({pire[1]} {pire[2]}-{pire[3]:02d})"
        )
    # Hors raccords d'expériences ERA5, l'écart n'est que l'arrondi des produits du CDS ;
    # un mauvais calage horaire des cumuls (00 h → 23 h) le porterait à 0,48 mm/jour.
    pire = max(ecarts[False], key=lambda e: abs(e[0]))
    if abs(pire[0]) > TOLERANCE_MENSUEL:
        raise SystemExit(f"Écart au mensuel 0036 au-delà de {TOLERANCE_MENSUEL} mm/jour : {pire}.")


def main(cache: Path, paralleles: int) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    points = points_nationaux()
    noeuds = sorted({maille_era5(lat, lon) for _, _, lat, lon in points})
    print(f"{len(points)} localités, {len(noeuds)} mailles 0,25° distinctes, {PLAGE}")

    with ThreadPoolExecutor(max_workers=paralleles) as pool:
        telecharges = pool.map(lambda n: _telecharger_en_cache(n, cache), noeuds)
        chemins = dict(zip(noeuds, telecharges, strict=True))
    cumuls = {n: _cumuls_journaliers(chemins[n], n) for n in noeuds}
    series: list[Serie] = [
        (code, lat, lon, cumuls[maille_era5(lat, lon)]) for code, _, lat, lon in points
    ]
    cible = ecrire_series_journalieres(CONTRAT, LOT_PLUIE_ERA5_JOURNALIERE, series)
    toutes = [round(v, 4) for _, _, _, m in series for _, v in m]
    print(
        f"precipitation: {len(series)} séries × {NB_JOURS} jours -> {cible.name} "
        f"(min {min(toutes)}, moyenne {math.fsum(toutes) / len(toutes):.3f}, max {max(toutes)})"
    )
    _comparer_au_mensuel(series)


if __name__ == "__main__":
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--cache", type=Path, default=Path(".cache/era5_cds_jour"))
    parseur.add_argument("--paralleles", type=int, default=2, help="requêtes CDS simultanées")
    args = parseur.parse_args()
    main(args.cache, args.paralleles)
