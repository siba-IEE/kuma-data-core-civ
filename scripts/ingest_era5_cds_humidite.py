#!/usr/bin/env python3
"""Ingesteur reproductible : humidité relative ERA5 (CDS), journalière et mensuelle, CIV.

Télécharge, pour chacun des **110 nœuds 0,25°** où tombent les 142 localités
(``points_nationaux``, mêmes nœuds que la température et le vent journaliers
0053), les séries **horaires** ERA5 ``2m_temperature`` et
``2m_dewpoint_temperature`` (réanalyse ECMWF, Copernicus C3S) du 1991-01-01
00 h au 2025-12-31 23 h UTC. Calcule l'humidité relative de chaque heure
(formule d'ECMWF, ``humidite_era5_civ``), puis la moyenne de chaque jour civil
UTC et de chaque mois, et écrit deux CSV gzip
(``seeds/donnees/ecmwf_era5_rh2m_<journalier|mensuel>_civ142.csv.gz``, ADR-0015)
que la migration 0057 lit hors-ligne (les migrations n'accèdent jamais au
réseau).

Contrats : ``kuma_data_core.db.seeds.humidite_era5_civ`` — source ``ecmwf_era5``
(id 2), méthode ``reanalyse``, confiance B, 1991-2025 (ADR-0038).

**Faits API** (jeu ``reanalysis-era5-single-levels-timeseries``) : une requête
par nœud pour les deux variables, plage de dates d'un seul tenant, archive zip
d'un netCDF : dimension ``valid_time`` horaire, coordonnées scalaires
``latitude`` et ``longitude`` du nœud servi, variables ``t2m`` et ``d2m`` (K).

**Garde-fous** : unités servies, nœud servi = nœud demandé, axe horaire continu
couvrant toute la période, aucune valeur manquante, bornes des contrats
(relecture par ``series_csv``). Recoupements publiés : la température moyenne
de chaque jour redonne le journalier ERA5 gravé (CSV de 0053) à 0,0001 °C près,
sinon le script échoue (mêmes heures, même nœud) ; la moyenne des jours de
chaque mois redonne le mensuel ; écart à l'humidité NASA POWER (``RH2M``).

**Accès CDS (clé obligatoire)** : la clé personnelle Copernicus est lue dans la
variable d'environnement ``ADS_API_KEY`` ; à défaut dans ``~/.cdsapirc``.
Requêtes simultanées limitées (``--paralleles``), attente quand la file CDS est
pleine, reprise après refus. Les netCDF bruts restent dans le cache
(``--cache``, hors dépôt), un sous-dossier par nœud, chaque téléchargement dans
un sous-dossier temporaire vide. Lecture netCDF sérialisée (bibliothèque non
sûre entre threads) ; à lancer avec ``python -I`` sur des fichiers téléchargés.

Usage : ``ADS_API_KEY=... uv run python -I scripts/ingest_era5_cds_humidite.py --cache .cache/era5_cds_humidite``
"""

from __future__ import annotations

import argparse
import calendar
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

from kuma_data_core.db.seeds.humidite_era5_civ import (
    CONTRAT_HUMIDITE_ERA5_JOURNALIER,
    CONTRAT_HUMIDITE_ERA5_MENSUEL,
    LOT_HUMIDITE_ERA5,
    UNITES_SOURCE_HUMIDITE,
    VARIABLES_CDS_HUMIDITE,
    humidite_journaliere,
    humidite_mensuelle,
    humidites_horaires,
)
from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.meteo_civ import (
    CONTRATS_METEO_NASA_JOURNALIERS,
    CONTRATS_METEO_NASA_MENSUELS,
    LOT_METEO_JOURNALIER,
    LOT_METEO_MENSUEL,
)
from kuma_data_core.db.seeds.meteo_era5_civ import maille_era5
from kuma_data_core.db.seeds.meteo_era5_journaliere_civ import (
    CONTRATS_METEO_ERA5_JOURNALIERS,
    HEURES_PAR_JOUR,
    JEU_CDS,
    LOT_METEO_ERA5_JOURNALIERE,
    temperature_journaliere_c,
)
from kuma_data_core.db.seeds.series_csv import (
    ecrire_series,
    ecrire_series_journalieres,
    lire_series,
    lire_series_journalieres,
    nb_jours,
)

CONTRAT = CONTRAT_HUMIDITE_ERA5_JOURNALIER
CDS_URL = "https://cds.climate.copernicus.eu/api"
PREMIER_JOUR = date(CONTRAT.annee_debut, 1, 1)
NB_JOURS = nb_jours(CONTRAT)
DEBUT_HORAIRE = datetime(CONTRAT.annee_debut, 1, 1)
NB_HEURES = NB_JOURS * HEURES_PAR_JOUR
PLAGE = f"{PREMIER_JOUR.isoformat()}/{date(CONTRAT.annee_fin, 12, 31).isoformat()}"
TOLERANCE_T2M_0053 = 0.0001  # °C : mêmes heures, même nœud, arrondi à 4 décimales
LOTS_NASA_JOURNALIERS: tuple[str, ...] = (LOT_METEO_JOURNALIER, "departements")
ESSAIS = 30
ATTENTE_S = 60
FILE_PLEINE = "Maximum number queued requests"
"""Refus du Copernicus quand la file de l'utilisateur est pleine : pas un échec."""
TAILLE_MAX_NC = 50 * 1024 * 1024  # un nœud sur 1991-2025 pèse environ 3 Mo
VERROU_NETCDF = threading.Lock()  # la bibliothèque netCDF n'est pas sûre entre threads

Noeud = tuple[float, float]
Jours = list[tuple[date, float]]
Mois = list[tuple[int, int, float]]
Extremes = tuple[float, float, int]  # humidité horaire min, max, heures au-dessus de 100 %


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
    return cache / nom / f"era5_horaire_t2m_d2m_{nom}_{CONTRAT.annee_debut}_{CONTRAT.annee_fin}.nc"


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
    """Valeurs horaires (K) du nœud, de DEBUT_HORAIRE à NB_HEURES heures plus tard."""
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
        for nom, unite in UNITES_SOURCE_HUMIDITE.items():
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
        "variable": list(VARIABLES_CDS_HUMIDITE),
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


def _calculer(chemin: Path, noeud: Noeud) -> tuple[Jours, Mois, Jours, Extremes]:
    """Humidité du jour et du mois, température du jour (°C), extrêmes horaires du nœud."""
    h = _lire_horaire(chemin, noeud)
    t2m, d2m = h["t2m"].tolist(), h["d2m"].tolist()
    horaires = humidites_horaires(t2m, d2m)
    jours: Jours = []
    temperatures: Jours = []
    for i in range(NB_JOURS):
        tranche = slice(i * HEURES_PAR_JOUR, (i + 1) * HEURES_PAR_JOUR)
        jour = PREMIER_JOUR + timedelta(days=i)
        jours.append((jour, humidite_journaliere(horaires[tranche])))
        temperatures.append((jour, temperature_journaliere_c(t2m[tranche])))
    mois: Mois = []
    debut = 0
    for annee in range(CONTRAT.annee_debut, CONTRAT.annee_fin + 1):
        for m in range(1, 13):
            n = calendar.monthrange(annee, m)[1]
            fin = debut + n * HEURES_PAR_JOUR
            mois.append((annee, m, humidite_mensuelle(horaires[debut:fin], n)))
            debut = fin
    if debut != NB_HEURES:
        raise SystemExit(f"{chemin.name} : {debut} heures réparties, {NB_HEURES} attendues.")
    extremes = (min(horaires), max(horaires), sum(h > 100.0 for h in horaires))
    return jours, mois, temperatures, extremes


def _comparer_t2m_0053(temperatures: dict[str, Jours]) -> None:
    """Température moyenne du jour, recalculée ici - journalier ERA5 gravé (CSV de 0053)."""
    grave = {
        s["localite_code"]: dict(s["mesures"])
        for s in lire_series_journalieres(
            CONTRATS_METEO_ERA5_JOURNALIERS["t2m"], LOT_METEO_ERA5_JOURNALIERE
        )
    }
    pire = max(
        (abs(round(v, 4) - grave[code][jour]), code, jour)
        for code, mesures in temperatures.items()
        for jour, v in mesures
    )
    print(f"t2m : jour recalculé - journalier 0053 : max {pire[0]:.6f} ({pire[1]} {pire[2]})")
    if pire[0] > TOLERANCE_T2M_0053:
        raise SystemExit(
            f"t2m : écart au journalier 0053 au-delà de {TOLERANCE_T2M_0053} : {pire}."
        )


def _comparer_jours_au_mois(jours: dict[str, Jours], mois: dict[str, Mois]) -> None:
    """Moyenne des jours de chaque mois (valeurs arrondies du CSV) - valeur mensuelle."""
    pire = (0.0, "", 0, 0)
    for code, mesures in jours.items():
        par_mois: dict[tuple[int, int], list[float]] = {}
        for jour, v in mesures:
            par_mois.setdefault((jour.year, jour.month), []).append(round(v, 4))
        for annee, m, v in mois[code]:
            valeurs = par_mois[(annee, m)]
            ecart = abs(math.fsum(valeurs) / len(valeurs) - round(v, 4))
            pire = max(pire, (ecart, code, annee, m))
    print(
        f"rh2m : moyenne des jours - mensuel : max {pire[0]:.6f} ({pire[1]} {pire[2]}-{pire[3]:02d})"
    )


def _comparer_a_nasa(jours: dict[str, Jours], mois: dict[str, Mois]) -> None:
    """ERA5 - NASA POWER (RH2M), jour à jour et mois à mois, par localité."""
    nasa_jours: dict[str, dict[date, float]] = {}
    for lot in LOTS_NASA_JOURNALIERS:
        for s in lire_series_journalieres(CONTRATS_METEO_NASA_JOURNALIERS["rh2m"], lot):
            nasa_jours[s["localite_code"]] = dict(s["mesures"])
    nasa_mois = {
        s["localite_code"]: {(a, m): v for a, m, v in s["mesures"]}
        for s in lire_series(CONTRATS_METEO_NASA_MENSUELS["rh2m"], LOT_METEO_MENSUEL)
    }
    for libelle, ecarts in (
        (
            "jour",
            {
                code: [
                    round(v, 4) - nasa_jours[code][j] for j, v in mesures if j in nasa_jours[code]
                ]
                for code, mesures in jours.items()
                if code in nasa_jours
            },
        ),
        (
            "mois",
            {
                code: [round(v, 4) - nasa_mois[code][(a, m)] for a, m, v in mesures]
                for code, mesures in mois.items()
            },
        ),
    ):
        tous = [e for valeurs in ecarts.values() for e in valeurs]
        par_localite = {c: math.fsum(v) / len(v) for c, v in ecarts.items()}
        bas = min(par_localite, key=par_localite.__getitem__)
        haut = max(par_localite, key=par_localite.__getitem__)
        print(
            f"rh2m ERA5 - NASA ({libelle}, {len(ecarts)} localités, {len(tous)} valeurs) : "
            f"moyen {math.fsum(tous) / len(tous):+.3f}, par localité de "
            f"{par_localite[bas]:+.3f} ({bas}) à {par_localite[haut]:+.3f} ({haut})"
        )


def main(cache: Path, paralleles: int) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    points = points_nationaux()
    noeuds = sorted({maille_era5(lat, lon) for _, _, lat, lon in points})
    print(f"{len(points)} localités, {len(noeuds)} mailles 0,25° distinctes, {PLAGE}")

    with ThreadPoolExecutor(max_workers=paralleles) as pool:
        telecharges = pool.map(lambda n: _telecharger_en_cache(n, cache), noeuds)
        chemins = dict(zip(noeuds, telecharges, strict=True))
    calculs = {n: _calculer(chemins[n], n) for n in noeuds}
    extremes = [calculs[n][3] for n in noeuds]
    print(
        f"rh2m horaire ({len(noeuds) * NB_HEURES} heures-nœuds) : "
        f"min {min(e[0] for e in extremes):.2f}, max {max(e[1] for e in extremes):.2f}, "
        f"au-dessus de 100 % : {sum(e[2] for e in extremes)}"
    )
    jours = {code: calculs[maille_era5(lat, lon)][0] for code, _, lat, lon in points}
    mois = {code: calculs[maille_era5(lat, lon)][1] for code, _, lat, lon in points}
    cible = ecrire_series_journalieres(
        CONTRAT_HUMIDITE_ERA5_JOURNALIER,
        LOT_HUMIDITE_ERA5,
        [(code, lat, lon, jours[code]) for code, _, lat, lon in points],
    )
    print(f"rh2m : {len(points)} séries × {NB_JOURS} jours -> {cible.name}")
    cible = ecrire_series(
        CONTRAT_HUMIDITE_ERA5_MENSUEL,
        LOT_HUMIDITE_ERA5,
        [(code, lat, lon, mois[code]) for code, _, lat, lon in points],
    )
    print(f"rh2m : {len(points)} séries × {len(mois[points[0][0]])} mois -> {cible.name}")
    _comparer_t2m_0053({code: calculs[maille_era5(lat, lon)][2] for code, _, lat, lon in points})
    _comparer_jours_au_mois(jours, mois)
    _comparer_a_nasa(jours, mois)


if __name__ == "__main__":
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--cache", type=Path, default=Path(".cache/era5_cds_humidite"))
    parseur.add_argument("--paralleles", type=int, default=2, help="requêtes CDS simultanées")
    args = parseur.parse_args()
    main(args.cache, args.paralleles)
