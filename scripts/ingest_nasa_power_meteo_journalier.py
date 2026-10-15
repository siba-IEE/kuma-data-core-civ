#!/usr/bin/env python3
"""Ingesteur reproductible : météo journalière NASA POWER aux 34 localités, CIV (ADR-0020).

Interroge l'API NASA POWER **journalière** (communauté ``RE``) aux 34 localités
du lot ``pilotes_regions`` (3 points pilotes + 31 régions, ADR-0016), une
requête par point pour les 6 paramètres météorologiques, et écrit un CSV gzip
par grandeur (``seeds/donnees/nasa_power_<grandeur>_journalier_pilotes_regions.csv.gz``)
que la migration 0035 lit hors-ligne (ADR-0015).

Contrats : ``seeds/meteo_civ.py`` (``CONTRATS_METEO_NASA_JOURNALIERS``) —
``t2m`` (``T2M``), ``rh2m`` (``RH2M``), ``vent_2m`` (``WS2M``), ``vent_10m``
(``WS10M``) et ``precipitation`` (``PRECTOTCORR``) en réanalyse MERRA-2,
1991-2025 ; ``albedo_surface`` (``ALLSKY_SRF_ALB``) CERES SYN1deg, 2001-2025.
Valeurs dans l'unité servie, identique à l'unité de la grandeur au référentiel
(°C, %, m/s, mm/jour, sans dimension) : aucune conversion.

Garde-fous : unités servies, aucune valeur de remplissage (-999) dans la
période du contrat, bornes, complétude (tous les jours civils), relecture
validée. Une grandeur dont la période contient une valeur de remplissage n'est
**pas écrite** (complétude stricte impossible, rien n'est bouché) : la
répartition des jours manquants est affichée et le script sort en erreur.

**Pluie** : NASA POWER sert des valeurs aberrantes probables (726,74 mm le
2022-09-16 à San-Pédro, 710,75 mm à Gbôklé), gravées telles que servies, sans
correction ; la borne journalière du contrat est de 1000 mm/jour (ADR-0020).

Usage : ``uv run python scripts/ingest_nasa_power_meteo_journalier.py``
(``--cache <dossier>`` garde les réponses JSON brutes pour reprendre ou
réécrire sans réinterroger l'API).
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import ssl
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

from kuma_data_core.db.seeds.lots_civ import points_journalier
from kuma_data_core.db.seeds.meteo_civ import (
    CONTRATS_METEO_NASA_JOURNALIERS,
    LOT_METEO_JOURNALIER,
    PARAMETRES_METEO_NASA,
)
from kuma_data_core.db.seeds.series_csv import ecrire_series_journalieres

REMPLISSAGE: float = -900.0  # NASA POWER code l'absence par -999

# Unité servie par NASA POWER (``parameters.<P>.units``) = unité du référentiel.
UNITES_SERVIES: dict[str, str] = {
    "t2m": "C",  # degree_celsius
    "rh2m": "%",  # pourcent
    "vent_2m": "m/s",  # metre_par_seconde
    "vent_10m": "m/s",
    "precipitation": "mm/day",  # mm_par_jour
    "albedo_surface": "dimensionless",  # sans_unite
}


def _fetch(lat: float, lon: float, debut: date, fin: date) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "parameters": ",".join(p[0] for p in PARAMETRES_METEO_NASA.values()),
            "community": "RE",
            "longitude": lon,
            "latitude": lat,
            "start": debut.strftime("%Y%m%d"),
            "end": fin.strftime("%Y%m%d"),
            "format": "JSON",
        }
    )
    url = f"https://power.larc.nasa.gov/api/temporal/daily/point?{query}"
    cafile = os.environ.get("SSL_CERT_FILE")
    ctx = ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()
    with urllib.request.urlopen(url, timeout=300, context=ctx) as reponse:
        data: dict[str, Any] = json.load(reponse)
    return data


def _reponse(
    code: str, lat: float, lon: float, debut: date, fin: date, cache: Path | None
) -> dict[str, Any]:
    """Réponse JSON d'un point, relue du cache si présente (``--cache``)."""
    chemin = cache / f"nasa_power_meteo_journalier_{code}.json" if cache else None
    if chemin is not None and chemin.exists():
        data: dict[str, Any] = json.loads(chemin.read_text(encoding="utf-8"))
        return data
    data = _fetch(lat, lon, debut, fin)
    if chemin is not None:
        partiel = chemin.with_suffix(".partiel")
        partiel.write_text(json.dumps(data), encoding="utf-8")
        partiel.replace(chemin)
    return data


def main(cache: Path | None, paralleles: int) -> None:
    contrats = CONTRATS_METEO_NASA_JOURNALIERS
    points = points_journalier()
    debut_requete = date(min(c.annee_debut for c in contrats.values()), 1, 1)
    fin_requete = date(max(c.annee_fin for c in contrats.values()), 12, 31)
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)

    def telecharger(point: tuple[str, str, float, float]) -> dict[str, Any]:
        code, _, lat, lon = point
        data = _reponse(code, lat, lon, debut_requete, fin_requete, cache)
        print(f"{code}: reçu", flush=True)
        return data

    with ThreadPoolExecutor(max_workers=paralleles) as pool:
        reponses = list(pool.map(telecharger, points))

    par_grandeur: dict[str, list[tuple[str, float, float, list[tuple[date, float]]]]] = {
        g: [] for g in contrats
    }
    remplis: dict[str, list[tuple[str, date]]] = {g: [] for g in contrats}
    for (code, _, lat, lon), data in zip(points, reponses, strict=True):
        for grandeur, contrat in contrats.items():
            parametre = PARAMETRES_METEO_NASA[grandeur][0]
            unite = data["parameters"][parametre]["units"]
            if unite != UNITES_SERVIES[grandeur]:
                raise SystemExit(f"{code}/{grandeur} : unité servie {unite!r} inattendue")
            debut, fin = date(contrat.annee_debut, 1, 1), date(contrat.annee_fin, 12, 31)
            mesures: list[tuple[date, float]] = []
            for cle, valeur in data["properties"]["parameter"][parametre].items():
                jour = date(int(cle[:4]), int(cle[4:6]), int(cle[6:8]))
                if not debut <= jour <= fin:
                    continue
                if valeur is None or valeur <= REMPLISSAGE:
                    remplis[grandeur].append((code, jour))
                    continue
                mesures.append((jour, float(valeur)))
            par_grandeur[grandeur].append((code, lat, lon, sorted(mesures)))

    incompletes: list[str] = []
    for grandeur, contrat in contrats.items():
        manquants = remplis[grandeur]
        if manquants:
            incompletes.append(grandeur)
            par_annee = collections.Counter(j.year for _, j in manquants)
            par_lieu = collections.Counter(c for c, _ in manquants)
            print(
                f"{grandeur}: {len(manquants)} valeurs de remplissage "
                f"({len({j for _, j in manquants})} jours distincts) — non écrite ; "
                f"par année {dict(sorted(par_annee.items()))} ; "
                f"par localité {dict(sorted(par_lieu.items()))}"
            )
            continue
        cible = ecrire_series_journalieres(contrat, LOT_METEO_JOURNALIER, par_grandeur[grandeur])
        valeurs = [v for _, _, _, m in par_grandeur[grandeur] for _, v in m]
        print(
            f"{grandeur}: {len(par_grandeur[grandeur])} séries, {len(valeurs)} jours, "
            f"min {min(valeurs)} max {max(valeurs)} -> {cible.name}"
        )
    if incompletes:
        raise SystemExit(f"Grandeurs non gravables (complétude stricte impossible) : {incompletes}")


if __name__ == "__main__":
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--cache", type=Path, help="dossier des réponses JSON brutes")
    parseur.add_argument("--paralleles", type=int, default=4, help="requêtes simultanées (≤ 4)")
    args = parseur.parse_args()
    main(args.cache, min(args.paralleles, 4))
