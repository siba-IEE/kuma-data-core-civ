#!/usr/bin/env python3
"""Ingesteur reproductible : météo mensuelle NASA POWER aux 142 localités, CIV.

Interroge l'API NASA POWER **mensuelle** (``/api/temporal/monthly/point``,
communauté ``RE``) aux 142 localités des séries mensuelles (``points_nationaux`` :
3 pilotes + 31 régions + 108 départements), **une requête par localité** pour les
6 paramètres, et écrit un CSV gzip par grandeur
(``seeds/donnees/nasa_power_<grandeur>_mensuel_civ142.csv.gz``) que la migration
lit hors-ligne (ADR-0015, ADR-0019).

| Grandeur | Paramètre | Origine | Unité servie | Période |
|---|---|---|---|---|
| ``t2m`` | ``T2M`` | MERRA-2 | °C | 1991-2025 |
| ``rh2m`` | ``RH2M`` | MERRA-2 | % | 1991-2025 |
| ``vent_2m`` | ``WS2M`` | MERRA-2 | m/s | 1991-2025 |
| ``vent_10m`` | ``WS10M`` | MERRA-2 | m/s | 1991-2025 |
| ``precipitation`` | ``PRECTOTCORR`` | MERRA-2 | mm/jour | 1991-2025 |
| ``albedo_surface`` | ``ALLSKY_SRF_ALB`` | CERES SYN1deg | sans dimension | 2001-2025 |

Contrats : ``meteo_civ.CONTRATS_METEO_NASA_MENSUELS`` (borne des précipitations à
60 mm/jour pour graver tel quel le mois aberrant de septembre 2022, ADR-0019).

Sémantique NASA POWER mensuel (vérifiée contre le journalier, ADR-0019) : la
valeur d'un mois est la **moyenne des jours** du mois, arrondie à 0,01 — y
compris pour ``PRECTOTCORR``, servi en **mm/jour** (pas un cumul mensuel), et
pour l'albédo. La clé ``AAAA13`` (moyenne annuelle) est écartée : la table impose
``mois BETWEEN 1 AND 12``.

Garde-fous : unité servie par NASA identique à l'unité de la grandeur au
référentiel (sinon arrêt, aucune conversion) ; aucune valeur de remplissage
(-999) dans la période du contrat (l'albédo, servi en -999 avant 2001, n'est
gravé qu'à partir de 2001) ; complétude (12 mois × années du contrat) ; bornes
et relecture validée par ``series_csv``.

Usage : ``uv run python scripts/ingest_nasa_power_meteo_mensuel.py`` ; ``--cache``
garde les réponses JSON brutes pour reprendre après une interruption,
``--paralleles`` (4 au plus) règle le nombre de requêtes simultanées.
(mettre ``SSL_CERT_FILE`` si un proxy TLS d'entreprise intercepte la sortie).
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.meteo_civ import (
    ANNEE_DEBUT_METEO,
    ANNEE_FIN_METEO,
    CONTRATS_METEO_NASA_MENSUELS,
    LOT_METEO_MENSUEL,
    PARAMETRES_METEO_NASA,
    UNITES_NASA,
)
from kuma_data_core.db.seeds.series_csv import ecrire_series

URL_API = "https://power.larc.nasa.gov/api/temporal/monthly/point"
NB_LOCALITES: int = 142
REMPLISSAGE: float = -900.0  # NASA POWER code l'absence par -999
MOIS_ANNUEL: int = 13  # clé AAAA13 : moyenne annuelle, non stockée
PARALLELES_MAX: int = 4  # politesse envers l'API
TENTATIVES: int = 4

Serie = tuple[str, float, float, list[tuple[int, int, float]]]


def _parametre(grandeur: str) -> str:
    return PARAMETRES_METEO_NASA[grandeur][0]


def _telecharger(lat: float, lon: float) -> dict[str, Any]:
    """Réponse JSON brute de NASA POWER pour un point (6 paramètres, 1991-2025)."""
    query = urllib.parse.urlencode(
        {
            "parameters": ",".join(_parametre(g) for g in CONTRATS_METEO_NASA_MENSUELS),
            "community": "RE",
            "longitude": lon,
            "latitude": lat,
            "start": ANNEE_DEBUT_METEO,
            "end": ANNEE_FIN_METEO,
            "format": "JSON",
        }
    )
    cafile = os.environ.get("SSL_CERT_FILE")
    ctx = ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()
    for tentative in range(1, TENTATIVES + 1):
        try:
            with urllib.request.urlopen(f"{URL_API}?{query}", timeout=180, context=ctx) as rep:
                donnees: dict[str, Any] = json.load(rep)
            return donnees
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if tentative == TENTATIVES:
                raise
            time.sleep(10 * tentative)  # l'API limite le débit : on espace les reprises
    raise AssertionError("inatteignable : la dernière tentative lève ou renvoie")


def _extraire(code: str, brut: dict[str, Any]) -> dict[str, list[tuple[int, int, float]]]:
    """Mesures ``(annee, mois, valeur)`` par grandeur, validées contre le contrat."""
    unites = brut["parameters"]
    valeurs = brut["properties"]["parameter"]
    sortie: dict[str, list[tuple[int, int, float]]] = {}
    for grandeur, contrat in CONTRATS_METEO_NASA_MENSUELS.items():
        parametre = _parametre(grandeur)
        servie = unites[parametre]["units"]
        if servie != UNITES_NASA[grandeur]:
            raise SystemExit(
                f"{code}/{parametre} : unité servie {servie!r}, "
                f"{UNITES_NASA[grandeur]!r} attendue (aucune conversion n'est faite)."
            )
        mesures: list[tuple[int, int, float]] = []
        for cle, valeur in valeurs[parametre].items():
            annee, mois = int(cle[:4]), int(cle[4:6])
            if mois == MOIS_ANNUEL or not contrat.annee_debut <= annee <= contrat.annee_fin:
                continue
            if valeur <= REMPLISSAGE:
                raise SystemExit(f"{code}/{parametre} : valeur de remplissage à {annee}-{mois:02d}")
            mesures.append((annee, mois, float(valeur)))
        mesures.sort()
        if len(mesures) != contrat.nb_mois:
            raise SystemExit(
                f"{code}/{parametre} : {len(mesures)} mois, {contrat.nb_mois} attendus."
            )
        sortie[grandeur] = mesures
    return sortie


def _en_cache(code: str, lat: float, lon: float, cache: Path) -> dict[str, Any]:
    """Réponse brute d'un point, relue du cache si elle y est déjà et valide."""
    chemin = cache / f"nasa_meteo_mensuel_{code}.json"
    if chemin.exists():
        try:
            brut: dict[str, Any] = json.loads(chemin.read_text(encoding="utf-8"))
            _extraire(code, brut)
            return brut
        except (SystemExit, ValueError, KeyError):
            chemin.unlink()  # cache corrompu ou incomplet : on redemande
    brut = _telecharger(lat, lon)
    partiel = chemin.with_suffix(".partiel")
    partiel.write_text(json.dumps(brut), encoding="utf-8")
    partiel.replace(chemin)
    return brut


def main(cache: Path, paralleles: int) -> None:
    points = points_nationaux()
    if len(points) != NB_LOCALITES:
        raise SystemExit(f"{len(points)} localités, {NB_LOCALITES} attendues.")
    cache.mkdir(parents=True, exist_ok=True)

    def traiter(point: tuple[str, str, float, float]) -> tuple[str, float, float, Any]:
        code, _, lat, lon = point
        mesures = _extraire(code, _en_cache(code, lat, lon, cache))
        print(f"{code}: " + ", ".join(f"{g} {len(m)} mois" for g, m in mesures.items()), flush=True)
        return code, lat, lon, mesures

    with ThreadPoolExecutor(max_workers=min(paralleles, PARALLELES_MAX)) as pool:
        resultats = list(pool.map(traiter, points))

    for grandeur, contrat in CONTRATS_METEO_NASA_MENSUELS.items():
        series: list[Serie] = [(code, lat, lon, m[grandeur]) for code, lat, lon, m in resultats]
        cible = ecrire_series(contrat, LOT_METEO_MENSUEL, series)
        valeurs = [v for _, _, _, mesures in series for _, _, v in mesures]
        print(
            f"{grandeur}: {len(series)} séries, {len(valeurs)} mesures "
            f"∈ [{min(valeurs)}, {max(valeurs)}] -> {cible.name}"
        )


if __name__ == "__main__":
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--cache", type=Path, default=Path(".cache/nasa_power_meteo"))
    parseur.add_argument("--paralleles", type=int, default=PARALLELES_MAX)
    args = parseur.parse_args()
    main(args.cache, args.paralleles)
