#!/usr/bin/env python3
"""Ingesteur reproductible : pluie journalière GPM IMERG servie par NASA POWER, 142 localités, CIV.

Interroge l'API NASA POWER **journalière** (communauté ``RE``, paramètre
``IMERG_PRECTOT``, ``time-standard=UTC``) aux **142 localités**
(``points_nationaux`` : 3 pilotes, 31 régions, 108 départements), une requête
par point du 1998-01-01 au 2025-12-31, et écrit un CSV gzip
(``seeds/donnees/gpm_imerg_precipitation_journalier_civ142.csv.gz``, ADR-0015)
que la migration 0052 lit hors-ligne (les migrations n'accèdent jamais au
réseau).

Contrat : ``kuma_data_core.db.seeds.pluie_imerg_civ`` — source ``gpm_imerg``
(id 17), méthode ``modele_satellitaire``, confiance B, 1998-2025, borne
1000 mm/jour. Valeurs telles que servies (mm/jour, 2 décimales), sans
conversion ni interpolation ; arrondi à 4 décimales à l'écriture du CSV
(``series_csv``), sans effet sur des valeurs à 2 décimales.

**Faits API** (sondage du 2026-10-15, API v2.10.0) : POWER ne sert IMERG
qu'en journalier UTC ; la réponse JSON porte ``"sources": ["IMERG"]``,
``"time_standard": "UTC"``, ``"fill_value": -999.0`` et l'unité ``mm/day``.
L'en-tête du format CSV de POWER libelle le paramètre « MERRA-2 Total
Precipitation » : c'est une erreur d'étiquette, le JSON et le dictionnaire des
paramètres (« The average IMERG total precipitation ») font foi, et les valeurs
diffèrent de ``PRECTOTCORR``.

**Garde-fous** (le script sort en erreur, rien n'est écrit) : en-tête de la
réponse (sources, standard de temps, valeur de remplissage), unité servie,
chaque jour civil de la période présent une seule fois, aucune valeur de
remplissage ni manquante (la répartition des jours manquants est affichée),
valeurs à 2 décimales au plus, bornes du contrat et relecture validée par
``series_csv.lire_series_journalieres``.

Une requête en échec (réseau, délai, réponse tronquée) est reprise jusqu'à
4 fois, à intervalles croissants ; 4 requêtes simultanées au plus. Avec
``--cache <dossier>``, les réponses JSON brutes sont gardées (écriture
atomique) : régénérer depuis le cache redonne les mêmes octets.

Usage : ``uv run python scripts/ingest_imerg_journalier.py --cache .cache/imerg_jour``
(mettre ``SSL_CERT_FILE`` si un proxy TLS d'entreprise intercepte la sortie).
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.pluie_imerg_civ import (
    COMMUNAUTE_POWER,
    CONTRAT_PLUIE_IMERG,
    DECIMALES_SERVIES,
    LOT_PLUIE_IMERG,
    PARAMETRE_POWER,
    REMPLISSAGE_POWER,
    SOURCES_SERVIES,
    STANDARD_TEMPS,
    UNITE_SERVIE,
)
from kuma_data_core.db.seeds.series_csv import ecrire_series_journalieres, nb_jours

CONTRAT = CONTRAT_PLUIE_IMERG
DEBUT = date(CONTRAT.annee_debut, 1, 1)
FIN = date(CONTRAT.annee_fin, 12, 31)
NB_JOURS = nb_jours(CONTRAT)
SEUIL_REMPLISSAGE: float = -900.0  # POWER code l'absence par -999
TENTATIVES: int = 4
URL_POWER: str = "https://power.larc.nasa.gov/api/temporal/daily/point"

Serie = tuple[str, float, float, list[tuple[date, float]]]


def _fetch(lat: float, lon: float) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "parameters": PARAMETRE_POWER,
            "community": COMMUNAUTE_POWER,
            "longitude": lon,
            "latitude": lat,
            "start": DEBUT.strftime("%Y%m%d"),
            "end": FIN.strftime("%Y%m%d"),
            "format": "JSON",
            "time-standard": STANDARD_TEMPS,
        }
    )
    url = f"{URL_POWER}?{query}"
    cafile = os.environ.get("SSL_CERT_FILE")
    ctx = ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()
    for tentative in range(1, TENTATIVES + 1):
        try:
            with urllib.request.urlopen(url, timeout=300, context=ctx) as reponse:
                data: dict[str, Any] = json.load(reponse)
            return data
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
            if tentative == TENTATIVES:
                raise
            print(f"({lat}, {lon}) : tentative {tentative} échouée ({e}) ; reprise", flush=True)
            time.sleep(10 * tentative)  # l'API limite le débit : on espace les reprises
    raise AssertionError("inatteignable : la dernière tentative lève ou renvoie")


def _reponse(code: str, lat: float, lon: float, cache: Path | None) -> dict[str, Any]:
    """Réponse JSON d'un point, relue du cache si présente (``--cache``)."""
    chemin = cache / f"power_imerg_journalier_{code}.json" if cache else None
    if chemin is not None and chemin.exists():
        data: dict[str, Any] = json.loads(chemin.read_text(encoding="utf-8"))
        return data
    data = _fetch(lat, lon)
    if chemin is not None:
        partiel = chemin.with_suffix(".partiel")
        partiel.write_text(json.dumps(data), encoding="utf-8")
        partiel.replace(chemin)
    return data


def _verifier_entete(code: str, data: dict[str, Any]) -> None:
    """Sources, standard de temps, valeur de remplissage et unité servis."""
    entete = data["header"]
    if tuple(entete["sources"]) != SOURCES_SERVIES:
        raise SystemExit(f"{code} : sources servies {entete['sources']!r} inattendues")
    if entete["time_standard"] != STANDARD_TEMPS:
        raise SystemExit(f"{code} : standard de temps {entete['time_standard']!r} inattendu")
    if entete["fill_value"] != REMPLISSAGE_POWER:
        raise SystemExit(f"{code} : valeur de remplissage {entete['fill_value']!r} inattendue")
    unite = data["parameters"][PARAMETRE_POWER]["units"]
    if unite != UNITE_SERVIE:
        raise SystemExit(f"{code} : unité servie {unite!r}, {UNITE_SERVIE!r} attendue")


def _mesures(
    code: str, data: dict[str, Any], remplis: list[tuple[str, date]]
) -> list[tuple[date, float]]:
    """Jours servis dans la période ; les valeurs de remplissage vont dans ``remplis``."""
    mesures: list[tuple[date, float]] = []
    vus: set[date] = set()
    for cle, valeur in data["properties"]["parameter"][PARAMETRE_POWER].items():
        jour = date(int(cle[:4]), int(cle[4:6]), int(cle[6:8]))
        if not DEBUT <= jour <= FIN or jour in vus:
            raise SystemExit(f"{code} : jour {jour} hors période ou en double")
        vus.add(jour)
        if valeur is None or valeur <= SEUIL_REMPLISSAGE:
            remplis.append((code, jour))
            continue
        if round(valeur, DECIMALES_SERVIES) != valeur:
            raise SystemExit(f"{code} {jour} : {valeur!r} a plus de {DECIMALES_SERVIES} décimales")
        mesures.append((jour, float(valeur)))
    if len(vus) != NB_JOURS:
        manquants = sorted({DEBUT + timedelta(days=i) for i in range(NB_JOURS)} - vus)
        raise SystemExit(f"{code} : {len(manquants)} jours non servis, dont {manquants[:5]}")
    return sorted(mesures)


def main(cache: Path | None, paralleles: int) -> None:
    points = points_nationaux()
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)

    def telecharger(point: tuple[str, str, float, float]) -> dict[str, Any]:
        code, _, lat, lon = point
        data = _reponse(code, lat, lon, cache)
        print(f"{code}: reçu", flush=True)
        return data

    with ThreadPoolExecutor(max_workers=paralleles) as pool:
        reponses = list(pool.map(telecharger, points))

    series: list[Serie] = []
    remplis: list[tuple[str, date]] = []
    for (code, _, lat, lon), data in zip(points, reponses, strict=True):
        _verifier_entete(code, data)
        series.append((code, lat, lon, _mesures(code, data, remplis)))
    if remplis:
        par_annee = collections.Counter(j.year for _, j in remplis)
        par_lieu = collections.Counter(c for c, _ in remplis)
        raise SystemExit(
            f"{len(remplis)} valeurs de remplissage ({len({j for _, j in remplis})} jours "
            f"distincts) — rien n'est écrit ; par année {dict(sorted(par_annee.items()))} ; "
            f"par localité {dict(sorted(par_lieu.items()))}"
        )

    cible = ecrire_series_journalieres(CONTRAT, LOT_PLUIE_IMERG, series)
    valeurs = [v for _, _, _, m in series for _, v in m]
    distinctes = len({tuple(v for _, v in m) for _, _, _, m in series})
    empreinte = hashlib.sha256(cible.read_bytes()).hexdigest()
    print(
        f"{len(series)} séries ({distinctes} distinctes), {len(valeurs)} jours, "
        f"min {min(valeurs)} max {max(valeurs)} -> {cible.name} (sha256 {empreinte})"
    )


if __name__ == "__main__":
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--cache", type=Path, help="dossier des réponses JSON brutes")
    parseur.add_argument("--paralleles", type=int, default=4, help="requêtes simultanées (≤ 4)")
    args = parseur.parse_args()
    main(args.cache, max(1, min(args.paralleles, 4)))
