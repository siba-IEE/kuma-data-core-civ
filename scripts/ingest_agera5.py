#!/usr/bin/env python3
"""Ingesteur reproductible : agroclimat AgERA5 (CDS), journalier et mensuel, CIV.

Télécharge, année par année de 1991 à 2025, les fichiers journaliers AgERA5
v2.0 (jeu CDS ``sis-agrometeorological-indicators``) des quatre grandeurs du lot
(ET0, Tmin, Tmax, déficit de pression de vapeur à Tmax) sur la zone de la Côte
d'Ivoire, en une requête par grandeur et par année (le CDS plafonne le coût
d'une requête). Lit, dans chaque fichier, la valeur des
mailles de 0,1° qui contiennent les 142 localités (``maille_agera5``, 119
mailles), convertit dans l'unité du référentiel (K → °C, hPa → kPa), calcule
la moyenne des jours de chaque mois et écrit huit CSV gzip
(``seeds/donnees/agera5_<grandeur>_<journalier|mensuel>_civ142.csv.gz``,
ADR-0015) que la migration 0059 lit hors-ligne.

Contrats : ``kuma_data_core.db.seeds.agroclimat_agera5_civ`` — source ``agera5``
(id 19), méthode ``reanalyse``, confiance B, 1991-2025 (ADR-0040).

**Faits API** : une archive zip par requête, un netCDF par jour
(``<Nom>_C3S-glob-agric_AgERA5_<AAAAMMJJ>_final-v2.0.0.area-subset....nc``),
dimension ``time`` d'un jour, coordonnées ``lat`` (décroissante) et ``lon`` aux
multiples de 0,1°, mer masquée (valeur absente).

**Garde-fous** : un fichier par jour de l'année, variable, unité et
agrégation servies, date du fichier = date du nom, nœuds servis = nœuds
attendus, aucune valeur absente aux 119 mailles, Tmin ≤ Tmax chaque jour, déficit
de pression de vapeur ≤ pression de vapeur saturante à Tmax, bornes des
contrats (relecture par ``series_csv``).

**Recoupements publiés** : Tmin et Tmax face à la température moyenne ERA5
journalière gravée (0053, maille de 0,25°) ; si le cache horaire ERA5 de 0057
est fourni (``--cache-era5-horaire``), Tmin et Tmax face aux minimum et maximum
des 24 heures UTC du nœud ERA5, avec un décalage de −1, 0 et +1 jour pour
vérifier la convention de jour ; ET0 face à la formule de Hargreaves (FAO-56,
équation 52) sur Tmin, Tmax et l'irradiation extraterrestre calculée.

**Accès CDS (clé obligatoire)** : clé personnelle Copernicus dans la variable
d'environnement ``ADS_API_KEY`` ; à défaut dans ``~/.cdsapirc``. La licence du
jeu (CC BY 4.0) doit avoir été acceptée sur le compte Copernicus. Requêtes
simultanées limitées (``--paralleles``), attente quand la file CDS est pleine.
Chaque grandeur-année téléchargée est réduite aux 119 mailles dans le cache
(``--cache``, hors dépôt, ``agera5_<grandeur>_<année>.csv.gz``) ; l'archive brute n'est
gardée qu'avec ``--garder-bruts``. Lecture netCDF sérialisée ; à lancer avec
``python -I``.

Usage : ``ADS_API_KEY=... uv run python -I scripts/ingest_agera5.py --cache .cache/agera5``
"""

from __future__ import annotations

import argparse
import calendar
import csv
import gzip
import math
import os
import re
import tempfile
import threading
import time
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import cdsapi  # type: ignore[import-untyped]
import numpy as np
import xarray as xr

from kuma_data_core.db.seeds.agroclimat_agera5_civ import (
    CONTRATS_AGERA5_JOURNALIERS,
    CONTRATS_AGERA5_MENSUELS,
    GRANDEURS_AGERA5,
    JEU_CDS,
    LOT_AGERA5,
    VERSION_FICHIERS,
    maille_agera5,
    requete_cds,
    sur_une_limite,
)
from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.meteo_era5_civ import maille_era5
from kuma_data_core.db.seeds.meteo_era5_journaliere_civ import (
    CONTRATS_METEO_ERA5_JOURNALIERS,
    LOT_METEO_ERA5_JOURNALIERE,
)
from kuma_data_core.db.seeds.series_csv import (
    ecrire_series,
    ecrire_series_journalieres,
    lire_series,
    lire_series_journalieres,
)

CDS_URL = "https://cds.climate.copernicus.eu/api"
CONTRAT = CONTRATS_AGERA5_JOURNALIERS["et0"]
ANNEES = range(CONTRAT.annee_debut, CONTRAT.annee_fin + 1)
ESSAIS = 30
ATTENTE_S = 60
FILE_PLEINE = "Maximum number queued requests"
"""Refus du Copernicus quand la file de l'utilisateur est pleine : pas un échec."""
TAILLE_MAX_MEMBRE = 5 * 1024 * 1024  # un fichier journalier de la zone pèse environ 36 ko
VERROU_NETCDF = threading.Lock()  # la bibliothèque netCDF n'est pas sûre entre threads
AGREGATIONS: dict[str, str] = {
    "et0": "Sum 00-00LT",
    "t2m_min": "Min 00-00LT",
    "t2m_max": "Max 00-00LT",
    "vpd_tmax": "Time of mx2t_dmax",
}
"""Attribut ``temporal_aggregation`` servi, par grandeur."""
MOTIF_FICHIER = re.compile(
    r"^(?P<nom>.+)_C3S-glob-agric_AgERA5_(?P<jour>\d{8})_" + re.escape(VERSION_FICHIERS) + r"\."
)
NOMS_FICHIERS: dict[str, str] = {
    "ReferenceET-PenmanMonteith-FAO56": "et0",
    "Temperature-Air-2m_Min-24h": "t2m_min",
    "Temperature-Air-2m_Max-24h": "t2m_max",
    "Vapour-Pressure-Deficit-at-Maximum-Temperature": "vpd_tmax",
}
ORDRE: tuple[str, ...] = tuple(GRANDEURS_AGERA5)

Maille = tuple[int, int]  # nœud en dixièmes de degré


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


def _mailles() -> list[Maille]:
    return sorted({maille_agera5(lat, lon) for _, _, lat, lon in points_nationaux()})


def _jours(annee: int) -> list[date]:
    debut = date(annee, 1, 1)
    return [debut + timedelta(days=i) for i in range(366 if calendar.isleap(annee) else 365)]


def _chemin_extrait(cache: Path, annee: int, grandeur: str) -> Path:
    return cache / f"agera5_{grandeur}_{annee}.csv.gz"


def _lire_extrait(chemin: Path, annee: int) -> dict[tuple[date, Maille], float]:
    """Valeurs servies (unité de la source) d'une grandeur-année réduite aux mailles, complètes."""
    valeurs: dict[tuple[date, Maille], float] = {}
    with gzip.open(chemin, "rt", encoding="utf-8", newline="") as f:
        lecteur = csv.reader(f)
        if next(lecteur) != ["jour", "lat_dixiemes", "lon_dixiemes", "valeur"]:
            raise ValueError(f"{chemin.name} : en-tête inattendu.")
        for jour, lat, lon, v in lecteur:
            valeurs[(date.fromisoformat(jour), (int(lat), int(lon)))] = float(v)
    attendu = len(_jours(annee)) * len(_mailles())
    if len(valeurs) != attendu:
        raise ValueError(f"{chemin.name} : {len(valeurs)} valeurs, {attendu} attendues.")
    return valeurs


def _lire_membre(chemin: Path, grandeur: str, jour: date, mailles: list[Maille]) -> list[float]:
    """Valeurs servies aux mailles, après contrôle de la variable, de l'unité et de la date."""
    g = GRANDEURS_AGERA5[grandeur]
    with VERROU_NETCDF, xr.open_dataset(chemin, engine="netcdf4") as ds:
        da = ds[g.variable_netcdf]
        if da.attrs.get("units") != g.unite_source:
            raise SystemExit(
                f"{chemin.name} : unité {da.attrs.get('units')!r}, {g.unite_source!r} attendue."
            )
        if da.attrs.get("temporal_aggregation") != AGREGATIONS[grandeur]:
            raise SystemExit(
                f"{chemin.name} : agrégation {da.attrs.get('temporal_aggregation')!r}."
            )
        temps = ds["time"].values.astype("datetime64[D]")
        if temps.size != 1 or temps[0] != np.datetime64(jour, "D"):
            raise SystemExit(f"{chemin.name} : date servie {temps!r}, {jour} attendue.")
        lat = np.rint(ds["lat"].values * 10).astype(int)
        lon = np.rint(ds["lon"].values * 10).astype(int)
        if not (
            np.allclose(ds["lat"].values * 10, lat, atol=1e-6)
            and np.allclose(ds["lon"].values * 10, lon, atol=1e-6)
        ):
            raise SystemExit(f"{chemin.name} : nœuds hors des multiples de 0,1°.")
        ilat = {int(v): i for i, v in enumerate(lat)}
        ilon = {int(v): i for i, v in enumerate(lon)}
        grille = da.values[0]
        sortie = []
        for la, lo in mailles:
            if la not in ilat or lo not in ilon:
                raise SystemExit(f"{chemin.name} : maille ({la / 10}, {lo / 10}) absente.")
            v = float(grille[ilat[la], ilon[lo]])
            if not math.isfinite(v):
                raise SystemExit(f"{chemin.name} : valeur absente en ({la / 10}, {lo / 10}).")
            sortie.append(v)
    return sortie


def _reduire(archive: Path, annee: int, grandeur: str, cible: Path) -> None:
    """Archive d'une grandeur-année → CSV gzip des valeurs servies aux mailles (contrôlées)."""
    mailles = _mailles()
    jours = set(_jours(annee))
    lignes: list[tuple[str, int, int, str]] = []
    vus: set[date] = set()
    with zipfile.ZipFile(archive) as zf, tempfile.TemporaryDirectory(dir=cible.parent) as tmp:
        for membre in zf.infolist():
            if membre.is_dir():
                continue
            m = MOTIF_FICHIER.match(membre.filename)
            if (
                not m
                or NOMS_FICHIERS.get(m["nom"]) != grandeur
                or membre.file_size > TAILLE_MAX_MEMBRE
            ):
                raise SystemExit(f"{archive.name} : membre inattendu {membre.filename!r}.")
            jour = date(int(m["jour"][:4]), int(m["jour"][4:6]), int(m["jour"][6:]))
            if jour not in jours or jour in vus:
                raise SystemExit(f"{archive.name} : {membre.filename!r} hors année ou en double.")
            vus.add(jour)
            chemin = Path(tmp) / "membre.nc"
            chemin.write_bytes(zf.read(membre))
            for (la, lo), v in zip(
                mailles, _lire_membre(chemin, grandeur, jour, mailles), strict=True
            ):
                lignes.append((jour.isoformat(), la, lo, repr(v)))
    if vus != jours:
        raise SystemExit(f"{archive.name} : {len(vus)} jours servis, {len(jours)} attendus.")
    lignes.sort()
    partiel = cible.with_suffix(".tmp")
    with gzip.open(partiel, "wt", encoding="utf-8", newline="") as f:
        ecrivain = csv.writer(f, lineterminator="\n")
        ecrivain.writerow(["jour", "lat_dixiemes", "lon_dixiemes", "valeur"])
        ecrivain.writerows(lignes)
    partiel.replace(cible)


def _telecharger(annee: int, grandeur: str, cache: Path, garder_bruts: bool) -> Path:
    """Télécharge et réduit une grandeur-année, sauf si son extrait est valide en cache."""
    cible = _chemin_extrait(cache, annee, grandeur)
    etiquette = f"{grandeur} {annee}"
    if cible.exists():
        try:
            _lire_extrait(cible, annee)
            return cible
        except (ValueError, OSError):
            cible.unlink()
    brut = cache / "bruts" / f"agera5_{grandeur}_{annee}.zip"
    if brut.exists():
        try:
            _reduire(brut, annee, grandeur, cible)
            print(f"{etiquette}: réduit depuis l'archive gardée", flush=True)
            return cible
        except (SystemExit, zipfile.BadZipFile, OSError) as erreur:
            print(f"{etiquette}: archive gardée refusée ({erreur}), on redemande", flush=True)
            brut.unlink()
    essai = 0
    while essai < ESSAIS:
        with tempfile.TemporaryDirectory(dir=cache) as tmp:
            partiel = Path(tmp) / "reponse.zip"
            try:
                _client().retrieve(JEU_CDS, requete_cds(annee, grandeur), str(partiel))
            except Exception as erreur:  # file d'attente CDS saturée, coupure réseau…
                derniere = str(erreur).strip().splitlines()[-1] if str(erreur).strip() else ""
                if FILE_PLEINE not in derniere:
                    essai += 1
                    print(f"{etiquette}: essai {essai} échoué ({derniere})", flush=True)
                time.sleep(ATTENTE_S)
                continue
            _reduire(partiel, annee, grandeur, cible)
            if garder_bruts:
                brut.parent.mkdir(parents=True, exist_ok=True)
                partiel.replace(brut)
        print(f"{etiquette}: téléchargé", flush=True)
        return cible
    raise SystemExit(f"{etiquette}: abandon après {ESSAIS} essais.")


def _es_kpa(t_c: float) -> float:
    """Pression de vapeur saturante (FAO-56, équation 11), kPa."""
    return 0.6108 * math.exp(17.27 * t_c / (t_c + 237.3))


def _ra_mm(latitude: float, jour: date) -> float:
    """Irradiation extraterrestre journalière (FAO-56, équations 21 à 25), en mm d'évaporation."""
    j = jour.timetuple().tm_yday
    phi = math.radians(latitude)
    dr = 1 + 0.033 * math.cos(2 * math.pi * j / 365)
    delta = 0.409 * math.sin(2 * math.pi * j / 365 - 1.39)
    ws = math.acos(-math.tan(phi) * math.tan(delta))
    ra_mj = (
        (24 * 60 / math.pi)
        * 0.0820
        * dr
        * (ws * math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.sin(ws))
    )
    return 0.408 * ra_mj


def _series(cache: Path) -> dict[str, dict[str, list[tuple[date, float]]]]:
    """Séries journalières par grandeur et localité, dans l'unité du référentiel."""
    par_maille: dict[str, dict[Maille, list[tuple[date, float]]]] = {
        g: defaultdict(list) for g in ORDRE
    }
    for g in ORDRE:
        for annee in ANNEES:
            valeurs = _lire_extrait(_chemin_extrait(cache, annee, g), annee)
            for (jour, maille), v in sorted(valeurs.items()):
                par_maille[g][maille].append((jour, GRANDEURS_AGERA5[g].convertir(v)))
    series: dict[str, dict[str, list[tuple[date, float]]]] = {g: {} for g in ORDRE}
    for code, _, lat, lon in points_nationaux():
        maille = maille_agera5(lat, lon)
        for g in ORDRE:
            series[g][code] = par_maille[g][maille]
    return series


def _mensuel(jours: list[tuple[date, float]]) -> list[tuple[int, int, float]]:
    par_mois: dict[tuple[int, int], list[float]] = defaultdict(list)
    for jour, v in jours:
        par_mois[(jour.year, jour.month)].append(v)
    return [(a, m, math.fsum(vs) / len(vs)) for (a, m), vs in sorted(par_mois.items())]


def _controler(series: dict[str, dict[str, list[tuple[date, float]]]]) -> None:
    """Tmin ≤ Tmax et déficit ≤ pression de vapeur saturante à Tmax, chaque jour."""
    pire_vpd = 0.0
    for code, tmin in series["t2m_min"].items():
        tmax = series["t2m_max"][code]
        vpd = series["vpd_tmax"][code]
        for (j1, a), (j2, b), (j3, d) in zip(tmin, tmax, vpd, strict=True):
            if not (j1 == j2 == j3) or a > b:
                raise SystemExit(f"{code} {j1} : Tmin {a:.4f} > Tmax {b:.4f}.")
            rapport = d / _es_kpa(b)
            pire_vpd = max(pire_vpd, rapport)
            if rapport > 1.0:
                raise SystemExit(f"{code} {j1} : déficit {d:.4f} kPa > e_sat(Tmax).")
    print(f"contrôles : Tmin ≤ Tmax partout ; déficit / e_sat(Tmax) au plus {pire_vpd:.3f}")


def _recouper(
    series: dict[str, dict[str, list[tuple[date, float]]]], cache_horaire: Path | None
) -> None:
    """Constats publiés : ERA5 journalier (0053), ERA5 horaire (0057), Hargreaves."""
    era5 = {
        s["localite_code"]: dict(s["mesures"])
        for s in lire_series_journalieres(
            CONTRATS_METEO_ERA5_JOURNALIERS["t2m"], LOT_METEO_ERA5_JOURNALIERE
        )
    }
    dedans = total = 0
    ecarts_milieu: list[float] = []
    for code, tmin in series["t2m_min"].items():
        tmax = dict(series["t2m_max"][code])
        for jour, a in tmin:
            t = era5[code][jour]
            b = tmax[jour]
            total += 1
            dedans += a <= t <= b
            ecarts_milieu.append((a + b) / 2 - t)
    print(
        f"ERA5 journalier (0053) : moyenne ERA5 entre Tmin et Tmax {100 * dedans / total:.2f} % des "
        f"jours-localités ; (Tmin + Tmax)/2 - t2m ERA5 = {np.mean(ecarts_milieu):+.3f} °C "
        f"(écart absolu moyen {np.mean(np.abs(ecarts_milieu)):.3f})"
    )
    for g in ORDRE:
        moyennes = {code: np.mean([v for _, v in s]) for code, s in series[g].items()}
        bas = min(moyennes, key=moyennes.__getitem__)
        haut = max(moyennes, key=moyennes.__getitem__)
        mois = defaultdict(list)
        for s in series[g].values():
            for jour, v in s:
                mois[jour.month].append(v)
        profil = " ".join(f"{np.mean(mois[m]):.2f}" for m in range(1, 13))
        print(
            f"{g} : moyenne {np.mean(list(moyennes.values())):.3f} ; de {moyennes[bas]:.3f} ({bas}) à "
            f"{moyennes[haut]:.3f} ({haut}) ; janvier → décembre : {profil}"
        )
    # Hargreaves (FAO-56, équation 52) sur Tmin, Tmax et Ra calculée.
    lat = {code: la for code, _, la, _ in points_nationaux()}
    et0, hg = [], []
    for code, s in series["et0"].items():
        tmin = dict(series["t2m_min"][code])
        tmax = dict(series["t2m_max"][code])
        for jour, v in s:
            a, b = tmin[jour], tmax[jour]
            et0.append(v)
            hg.append(0.0023 * _ra_mm(lat[code], jour) * ((a + b) / 2 + 17.8) * math.sqrt(b - a))
    print(
        f"ET0 AgERA5 {np.mean(et0):.3f} mm/jour, Hargreaves {np.mean(hg):.3f} ; corrélation "
        f"journalière {np.corrcoef(et0, hg)[0, 1]:.3f}"
    )
    if cache_horaire is None:
        return
    # Convention de jour : extrêmes des 24 heures UTC du nœud ERA5 (cache de 0057).
    for g, fonction in (("t2m_min", np.min), ("t2m_max", np.max)):
        par_decalage: dict[int, list[float]] = defaultdict(list)
        noeuds = {}
        for code, _, la, lo in points_nationaux():
            noeuds.setdefault(maille_era5(la, lo), []).append(code)
        for noeud, codes in sorted(noeuds.items()):
            nom = f"{noeud[0]:+06.2f}_{noeud[1]:+07.2f}"
            chemin = cache_horaire / nom / f"era5_horaire_t2m_d2m_{nom}_1991_2025.nc"
            with VERROU_NETCDF, xr.open_dataset(chemin, engine="netcdf4") as ds:
                horaire = ds["t2m"].values.astype(float).ravel() - 273.15
            extremes = fonction(horaire.reshape(-1, 24), axis=1)
            ag = np.array([v for _, v in series[g][codes[0]]])
            for d in (-1, 0, 1):
                a = ag[max(0, d) : len(ag) + min(0, d)]
                e = extremes[max(0, -d) : len(extremes) + min(0, -d)]
                par_decalage[d].append(float(np.corrcoef(a, e)[0, 1]))
            par_decalage[9].append(float(np.mean(ag - extremes)))
        print(
            f"{g} face aux extrêmes horaires ERA5 (110 nœuds) : corrélation moyenne décalage −1 "
            f"{np.mean(par_decalage[-1]):.3f}, 0 {np.mean(par_decalage[0]):.3f}, +1 "
            f"{np.mean(par_decalage[1]):.3f} ; écart moyen {np.mean(par_decalage[9]):+.3f} °C"
        )


def main() -> None:
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--cache", type=Path, default=Path(".cache/agera5"))
    parseur.add_argument("--paralleles", type=int, default=4, help="requêtes CDS simultanées")
    parseur.add_argument("--garder-bruts", action="store_true", help="garder les archives zip")
    parseur.add_argument("--telecharger-seulement", action="store_true")
    parseur.add_argument("--cache-era5-horaire", type=Path, default=None)
    args = parseur.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)

    points = points_nationaux()
    print(
        f"{len(points)} localités, {len(_mailles())} mailles de 0,1°, "
        f"{sum(sur_une_limite(la, lo) for _, _, la, lo in points)} sur une limite de maille"
    )
    with ThreadPoolExecutor(max_workers=args.paralleles) as pool:
        taches = [(a, g) for a in ANNEES for g in ORDRE]
        list(pool.map(lambda t: _telecharger(*t, args.cache, args.garder_bruts), taches))
    if args.telecharger_seulement:
        return

    series = _series(args.cache)
    _controler(series)
    coords = {code: (la, lo) for code, _, la, lo in points}
    for g in ORDRE:
        ecrire_series_journalieres(
            CONTRATS_AGERA5_JOURNALIERS[g],
            LOT_AGERA5,
            [(code, *coords[code], s) for code, s in sorted(series[g].items())],
        )
        ecrire_series(
            CONTRATS_AGERA5_MENSUELS[g],
            LOT_AGERA5,
            [(code, *coords[code], _mensuel(s)) for code, s in sorted(series[g].items())],
        )
        jours = sum(
            len(s["mesures"])
            for s in lire_series_journalieres(CONTRATS_AGERA5_JOURNALIERS[g], LOT_AGERA5)
        )
        mois = sum(len(s["mesures"]) for s in lire_series(CONTRATS_AGERA5_MENSUELS[g], LOT_AGERA5))
        print(f"{g} : {jours} mesures journalières, {mois} mensuelles écrites")
    _recouper(series, args.cache_era5_horaire)


if __name__ == "__main__":
    main()
