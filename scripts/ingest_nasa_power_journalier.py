#!/usr/bin/env python3
"""Ingesteur reproductible : GHI, DNI et DHI journaliers NASA POWER, CIV (lot 3).

Interroge l'API NASA POWER **journalière** (communauté ``RE``) aux 34 localités
du lot ``pilotes_regions`` (3 points pilotes + 31 régions, ADR-0016), une
requête par point pour les 3 paramètres, et écrit un CSV gzip par grandeur
(``seeds/donnees/nasa_power_<grandeur>_journalier_pilotes_regions.csv.gz``)
que la migration lit hors-ligne (ADR-0015).

Périodes identiques au mensuel : GHI 1991-2020 ; DNI et DHI 2001-2020 (DNI non
servi avant 2001, DHI en rupture avant 2001 — ADR-0013). Valeurs en
kWh/m²/jour (unité ``kwh_par_m2_jour``), sans conversion.

Garde-fous : aucune valeur de remplissage (-999) dans la période gravée,
bornes physiques, complétude (tous les jours civils), relecture validée.

Usage : ``uv run python scripts/ingest_nasa_power_journalier.py`` ; ``--extension``
pour prolonger les mêmes séries sur 2021-2025 (ADR-0018).
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import urllib.parse
import urllib.request
from datetime import date

from kuma_data_core.db.seeds.lots_civ import (
    CONTRATS_NASA_JOURNALIERS,
    CONTRATS_NASA_JOURNALIERS_EXTENSION,
    LOT_EXTENSION,
    LOT_JOURNALIER,
    PARAMETRES_NASA,
    points_journalier,
)
from kuma_data_core.db.seeds.series_csv import ContratSerie, ecrire_series_journalieres

REMPLISSAGE: float = -900.0  # NASA POWER code l'absence par -999


def _fetch(lat: float, lon: float, debut: date, fin: date) -> dict[str, dict[str, float]]:
    query = urllib.parse.urlencode(
        {
            "parameters": ",".join(PARAMETRES_NASA.values()),
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
        data = json.load(reponse)
    parametres: dict[str, dict[str, float]] = data["properties"]["parameter"]
    return parametres


def main(contrats: dict[str, ContratSerie], lot: str) -> None:
    par_grandeur: dict[str, list[tuple[str, float, float, list[tuple[date, float]]]]] = {
        g: [] for g in contrats
    }
    debut_requete = date(min(c.annee_debut for c in contrats.values()), 1, 1)
    fin_requete = date(max(c.annee_fin for c in contrats.values()), 12, 31)
    dhi_sup_ghi = 0
    for code, _, lat, lon in points_journalier():
        brut = _fetch(lat, lon, debut_requete, fin_requete)
        par_jour: dict[str, dict[date, float]] = {}
        for grandeur, contrat in contrats.items():
            debut, fin = date(contrat.annee_debut, 1, 1), date(contrat.annee_fin, 12, 31)
            mesures: dict[date, float] = {}
            for cle, valeur in brut[PARAMETRES_NASA[grandeur]].items():
                jour = date(int(cle[:4]), int(cle[4:6]), int(cle[6:8]))
                if not debut <= jour <= fin:
                    continue
                if valeur <= REMPLISSAGE:
                    raise SystemExit(f"{code}/{grandeur} : valeur de remplissage au {jour}")
                mesures[jour] = float(valeur)
            par_jour[grandeur] = mesures
            par_grandeur[grandeur].append((code, lat, lon, sorted(mesures.items())))
        dhi_sup_ghi += sum(
            1 for jour, v in par_jour["dhi"].items() if v > par_jour["ghi"][jour] + 1e-9
        )
        print(f"{code}: " + ", ".join(f"{g} {len(m)} j" for g, m in par_jour.items()), flush=True)
    for grandeur, contrat in contrats.items():
        cible = ecrire_series_journalieres(contrat, lot, par_grandeur[grandeur])
        print(f"{grandeur}: {len(par_grandeur[grandeur])} séries -> {cible.name}")
    print(f"Jours DHI > GHI (période gravée, tous points) : {dhi_sup_ghi}")


if __name__ == "__main__":
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--extension", action="store_true", help="prolonger 2021-2025")
    args = parseur.parse_args()
    if args.extension:
        main(CONTRATS_NASA_JOURNALIERS_EXTENSION, LOT_EXTENSION)
    else:
        main(CONTRATS_NASA_JOURNALIERS, LOT_JOURNALIER)
