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

``--departements`` : les **108 départements** hors pilotes (lot ``departements``,
ADR-0031), une requête par point sur **1991-2025** d'un seul tenant (GHI
1991-2025, DNI et DHI 2001-2025), au plus 4 requêtes simultanées, reprise sur
erreur. Contrôle en plus l'unité servie (``kW-hr/m^2/day``). Complétude
stricte : une grandeur dont la période contient une valeur de remplissage n'est
**pas écrite** (rien n'est bouché) ; la répartition des jours manquants est
affichée et le script sort en erreur. ``--cache <dossier>`` garde les réponses
JSON brutes pour reprendre ou réécrire sans réinterroger l'API.
"""

from __future__ import annotations

import argparse
import collections
import http.client
import json
import os
import ssl
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

from kuma_data_core.db.seeds.journalier_departements_civ import (
    CONTRATS_RAYONNEMENT_DEPARTEMENTS,
    LOT_JOURNALIER_DEPARTEMENTS,
    points_journalier_departements,
)
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
UNITE_SERVIE: str = "kW-hr/m^2/day"  # = kwh_par_m2_jour au référentiel, sans conversion
TENTATIVES: int = 5  # par point, en cas d'erreur réseau ou de réponse tronquée


def _requete(lat: float, lon: float, debut: date, fin: date) -> dict[str, Any]:
    """Réponse JSON complète de l'API journalière pour un point (3 paramètres)."""
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
        data: dict[str, Any] = json.load(reponse)
    return data


def _fetch(lat: float, lon: float, debut: date, fin: date) -> dict[str, dict[str, float]]:
    parametres: dict[str, dict[str, float]] = _requete(lat, lon, debut, fin)["properties"][
        "parameter"
    ]
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


# --- Lot « départements » (ADR-0031) -------------------------------------------------


def _reponse(
    code: str, lat: float, lon: float, debut: date, fin: date, cache: Path | None
) -> dict[str, Any]:
    """Réponse JSON d'un point : relue du cache si présente, sinon demandée (reprises)."""
    chemin = cache / f"nasa_power_rayonnement_journalier_{code}.json" if cache else None
    if chemin is not None and chemin.exists():
        lue: dict[str, Any] = json.loads(chemin.read_text(encoding="utf-8"))
        return lue
    for tentative in range(1, TENTATIVES + 1):
        try:
            data = _requete(lat, lon, debut, fin)
            break
        except (OSError, http.client.HTTPException, ValueError) as erreur:
            if tentative == TENTATIVES:
                raise
            print(f"{code}: échec {tentative}/{TENTATIVES} ({erreur}), reprise", flush=True)
            time.sleep(10 * tentative)
    if chemin is not None:
        partiel = chemin.with_suffix(".partiel")
        partiel.write_text(json.dumps(data), encoding="utf-8")
        partiel.replace(chemin)
    return data


def main_departements(cache: Path | None, paralleles: int) -> None:
    """108 départements, 1991-2025 d'un seul tenant, complétude stricte."""
    contrats = CONTRATS_RAYONNEMENT_DEPARTEMENTS
    points = points_journalier_departements()
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
    dhi_sup_ghi: list[tuple[str, date, float, float]] = []
    for (code, _, lat, lon), data in zip(points, reponses, strict=True):
        par_jour: dict[str, dict[date, float]] = {}
        for grandeur, contrat in contrats.items():
            parametre = PARAMETRES_NASA[grandeur]
            unite = data["parameters"][parametre]["units"]
            if unite != UNITE_SERVIE:
                raise SystemExit(f"{code}/{grandeur} : unité servie {unite!r} inattendue")
            debut, fin = date(contrat.annee_debut, 1, 1), date(contrat.annee_fin, 12, 31)
            mesures: dict[date, float] = {}
            for cle, valeur in data["properties"]["parameter"][parametre].items():
                jour = date(int(cle[:4]), int(cle[4:6]), int(cle[6:8]))
                if not debut <= jour <= fin:
                    continue
                if valeur is None or valeur <= REMPLISSAGE:
                    remplis[grandeur].append((code, jour))
                    continue
                mesures[jour] = float(valeur)
            par_jour[grandeur] = mesures
            par_grandeur[grandeur].append((code, lat, lon, sorted(mesures.items())))
        dhi_sup_ghi += [
            (code, jour, v, par_jour["ghi"][jour])
            for jour, v in sorted(par_jour["dhi"].items())
            if jour in par_jour["ghi"] and v > par_jour["ghi"][jour]
        ]

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
        cible = ecrire_series_journalieres(
            contrat, LOT_JOURNALIER_DEPARTEMENTS, par_grandeur[grandeur]
        )
        valeurs = [v for _, _, _, m in par_grandeur[grandeur] for _, v in m]
        print(
            f"{grandeur}: {len(par_grandeur[grandeur])} séries, {len(valeurs)} jours, "
            f"min {min(valeurs)} max {max(valeurs)} -> {cible.name}"
        )
    print(f"Jours DHI > GHI (période gravée, 108 départements) : {len(dhi_sup_ghi)}")
    for code, jour, dhi, ghi in dhi_sup_ghi:
        print(f"  {code} {jour} : DHI {dhi} > GHI {ghi}")
    if incompletes:
        raise SystemExit(f"Grandeurs non gravables (complétude stricte impossible) : {incompletes}")


if __name__ == "__main__":
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    lots = parseur.add_mutually_exclusive_group()
    lots.add_argument("--extension", action="store_true", help="prolonger 2021-2025")
    lots.add_argument(
        "--departements", action="store_true", help="108 départements hors pilotes, 1991-2025"
    )
    parseur.add_argument(
        "--cache", type=Path, help="dossier des réponses JSON brutes (--departements)"
    )
    parseur.add_argument(
        "--paralleles", type=int, default=4, help="requêtes simultanées (≤ 4, --departements)"
    )
    args = parseur.parse_args()
    if args.departements:
        main_departements(args.cache, max(1, min(args.paralleles, 4)))
    elif args.extension:
        main(CONTRATS_NASA_JOURNALIERS_EXTENSION, LOT_EXTENSION)
    else:
        main(CONTRATS_NASA_JOURNALIERS, LOT_JOURNALIER)
