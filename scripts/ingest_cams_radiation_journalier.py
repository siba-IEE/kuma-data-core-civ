#!/usr/bin/env python3
"""Ingesteur reproductible : GHI, DNI et DHI journaliers CAMS Radiation, 142 localités, CIV.

Télécharge l'irradiation **tous ciels** journalière de **CAMS Radiation**
(Heliosat-4 + McClear, ADS Copernicus) aux 142 localités (``points_nationaux``)
du 2005-01-01 au 2025-12-31 et écrit un CSV gzip par grandeur
(``seeds/donnees/cams_<grandeur>_journalier_civ142.csv.gz``, ADR-0015) que la
migration 0054 lit hors-ligne (les migrations n'accèdent jamais au réseau).

Contrats : ``kuma_data_core.db.seeds.rayonnement_cams_journalier_civ`` —
source ``cams_radiation`` (id 13), méthode ``modele_satellitaire``,
confiance B, 2005-2025.

**Faits API** (jeu ``cams-solar-radiation-timeseries``, sondage du 2026-10-28,
service « CAMS Radiation Service v4.6 ») : une requête par localité,
``time_step=1day``, ``time_reference=universal_time``, CSV ``;``-séparé, en-têtes
``#`` ; colonnes **repérées par nom** (``GHI``, ``BNI``, ``DHI``,
``Reliability``), en Wh/m² intégrés au jour.

**Conversion** : Wh/m²/jour ÷ 1000 → kWh/m²/jour (``kwh_par_jour``).

**Garde-fous** : en-tête conforme (version du service, pas d'intégration d'un
jour, temps universel, unité Wh m-2, coordonnées servies = demandées), jours
complets et dans l'ordre, aucune valeur manquante, bornes du contrat (relecture
par ``series_csv.lire_series_journalieres``). La moyenne des jours de chaque
mois est comparée au mensuel CAMS gravé (pilotes, lots et extension
2021-2025) : l'écart est publié et le script échoue au-delà de
``TOLERANCE_MENSUEL``. La fiabilité journalière (``Reliability``) est résumée,
non gravée.

**Accès ADS (clé obligatoire)** : variable d'environnement ``ADS_API_KEY`` ; à
défaut ``~/.cdsapirc``. Les CSV bruts restent dans le cache (``--cache``, hors
dépôt), chaque téléchargement dans un sous-dossier temporaire vide, pour
reprendre après une interruption ; régénérer depuis le cache redonne les mêmes
octets.

Usage : ``ADS_API_KEY=... uv run python -I scripts/ingest_cams_radiation_journalier.py --cache .cache/cams_jour``
"""

from __future__ import annotations

import argparse
import math
import os
import tempfile
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import cdsapi  # type: ignore[import-untyped]

from kuma_data_core.db.seeds import (
    series_cams_dhi_mensuel_civ,
    series_cams_dni_mensuel_civ,
    series_cams_ghi_mensuel_civ,
)
from kuma_data_core.db.seeds.lots_civ import (
    CONTRATS_CAMS,
    LOT_EXTENSION,
    contrat_extension,
    points_nationaux,
)
from kuma_data_core.db.seeds.rayonnement_cams_journalier_civ import (
    ANNEE_DEBUT_CAMS_JOURNALIER,
    ANNEE_FIN_CAMS_JOURNALIER,
    COLONNES_CAMS,
    CONTRATS_CAMS_JOURNALIERS,
    GRANDEURS_CAMS,
    JEU_ADS,
    LOT_CAMS_JOURNALIER,
    kwh_par_jour,
)
from kuma_data_core.db.seeds.series_csv import ecrire_series_journalieres, lire_series

ADS_URL = "https://ads.atmosphere.copernicus.eu/api"
PREMIER_JOUR = date(ANNEE_DEBUT_CAMS_JOURNALIER, 1, 1)
DERNIER_JOUR = date(ANNEE_FIN_CAMS_JOURNALIER, 12, 31)
NB_JOURS = (DERNIER_JOUR - PREMIER_JOUR).days + 1
PLAGE = f"{PREMIER_JOUR.isoformat()}/{DERNIER_JOUR.isoformat()}"
VERSION_SERVICE = "CAMS Radiation Service v4.6"
TOLERANCE_MENSUEL = 0.001  # kWh/m²/jour : moyenne des jours - mensuel gravé
ANNEES_REVISEES = range(2021, 2026)
"""Années que CAMS a révisées depuis la gravure du mensuel (sondage du 2026-09-30, ADR-0018) :
le mensuel servi le 2026-10-28 redonne la moyenne des jours, plus le mensuel gravé."""
ESSAIS = 30
ATTENTE_S = 60
FILE_PLEINE = "Maximum number queued requests"
"""Refus du Copernicus quand la file de l'utilisateur est pleine : pas un échec."""
SEEDS_PILOTES = {
    "ghi": series_cams_ghi_mensuel_civ,
    "dni": series_cams_dni_mensuel_civ,
    "dhi": series_cams_dhi_mensuel_civ,
}

Mesures = dict[str, list[tuple[date, float | None]]]


def _client() -> cdsapi.Client:
    """Client cdsapi sur l'ADS : clé depuis ADS_API_KEY, repli ~/.cdsapirc."""
    cle = os.environ.get("ADS_API_KEY")
    if not cle:
        rc_path = os.path.expanduser("~/.cdsapirc")
        if not os.path.exists(rc_path):
            raise SystemExit(
                "Clé ADS absente : définir ADS_API_KEY (secret d'environnement) "
                "ou fournir ~/.cdsapirc. Cf. ADR-0011."
            )
        rc: dict[str, str] = {}
        with open(rc_path) as f:
            for line in f:
                if line.strip() and ":" in line:
                    k, v = line.split(":", 1)
                    rc[k.strip()] = v.strip()
        cle = rc["key"]
    return cdsapi.Client(url=ADS_URL, key=cle, quiet=True)


def _entete(lignes: list[str], cle: str) -> str:
    for ln in lignes:
        if ln.startswith(f"# {cle}"):
            return ln.split(":", 1)[1].strip()
    raise SystemExit(f"En-tête CAMS : « {cle} » introuvable.")


def _extraire(chemin: Path, lat: float, lon: float) -> tuple[Mesures, list[float]]:
    """GHI, DNI, DHI journaliers (kWh/m²/jour) et fiabilités du CSV CAMS ; contrôles."""
    lignes = chemin.read_text(encoding="utf-8", errors="replace").splitlines()
    if not any(VERSION_SERVICE in ln for ln in lignes[:5]):
        raise SystemExit(f"{chemin.name} : service autre que « {VERSION_SERVICE} ».")
    controles = {
        "Time reference": "Universal time (UT)",
        "Summarization (integration) period": "0 year 0 month 1 day 0 h 0 min 0 s",
        "Latitude (positive North, ISO 19115)": f"{lat:.4f}",
        "Longitude (positive East, ISO 19115)": f"{lon:.4f}",
    }
    for cle, attendu in controles.items():
        if _entete(lignes, cle) != attendu:
            raise SystemExit(f"{chemin.name} : {cle} = {_entete(lignes, cle)!r}, {attendu!r}.")
    if not any('uom:"Wh m-2"' in ln for ln in lignes):
        raise SystemExit(f"{chemin.name} : unité autre que Wh m-2.")
    noms = next(
        [c.strip() for c in ln.lstrip("#").split(";")]
        for ln in lignes
        if ln.startswith("# Observation period;")
    )
    col = {g: noms.index(c) for g, c in COLONNES_CAMS.items()}
    i_fiab = noms.index("Reliability")
    mesures: Mesures = {g: [] for g in GRANDEURS_CAMS}
    fiabilites: list[float] = []
    attendu = PREMIER_JOUR
    for ln in lignes:
        if not ln or ln.startswith("#"):
            continue
        cols = ln.split(";")
        debut, fin = (datetime.fromisoformat(p) for p in cols[0].split("/"))
        if debut != datetime.combine(attendu, datetime.min.time()) or fin - debut != timedelta(1):
            raise SystemExit(f"{chemin.name} : période {cols[0]}, jour {attendu} attendu.")
        for g, i in col.items():
            wh = float(cols[i])
            if math.isnan(wh):  # jour non servi (images manquantes) : lacune, jamais bouchée
                mesures[g].append((attendu, None))
                continue
            if not math.isfinite(wh) or wh < 0:
                raise SystemExit(f"{chemin.name} : {g} invalide le {attendu} ({cols[i]!r}).")
            mesures[g].append((attendu, kwh_par_jour(wh)))
        fiabilites.append(float(cols[i_fiab]))
        attendu += timedelta(1)
    if attendu != DERNIER_JOUR + timedelta(1):
        raise SystemExit(f"{chemin.name} : {(attendu - PREMIER_JOUR).days} jours, {NB_JOURS}.")
    return mesures, fiabilites


def _telecharger_en_cache(code: str, lat: float, lon: float, cache: Path) -> Path:
    """Télécharge le CSV CAMS journalier d'une localité, sauf s'il est valide en cache."""
    chemin = cache / f"cams_jour_{code}_{lat:.4f}_{lon:.4f}.csv"
    if chemin.exists():
        try:
            _extraire(chemin, lat, lon)
            return chemin
        except (SystemExit, ValueError, StopIteration):
            chemin.unlink()  # cache corrompu ou incomplet : on redemande
    requete = {
        "sky_type": "observed_cloud",
        "location": {"latitude": lat, "longitude": lon},
        "altitude": ["-999."],
        "date": [PLAGE],
        "time_step": "1day",
        "time_reference": "universal_time",
        "format": "csv",
    }
    essai = 0
    while essai < ESSAIS:
        with tempfile.TemporaryDirectory(dir=cache) as tmp:
            partiel = Path(tmp) / "reponse.csv"
            try:
                _client().retrieve(JEU_ADS, requete, str(partiel))
            except Exception as erreur:  # file d'attente ADS saturée, coupure réseau…
                derniere = str(erreur).strip().splitlines()[-1] if str(erreur).strip() else ""
                if FILE_PLEINE not in derniere:  # file pleine : on attend son tour
                    essai += 1
                    print(f"{code}: essai {essai} échoué ({derniere})", flush=True)
                time.sleep(ATTENTE_S)
                continue
            _extraire(partiel, lat, lon)
            partiel.replace(chemin)
        print(f"{code}: téléchargé", flush=True)
        return chemin
    raise SystemExit(f"{code}: abandon après {ESSAIS} essais.")


def _mensuel_grave(grandeur: str) -> dict[str, dict[tuple[int, int], float]]:
    """Mensuel CAMS gravé, 2005-2025 : pilotes (module), lots et extension (CSV)."""
    par_loc: dict[str, dict[tuple[int, int], float]] = {}

    def ajouter(series: Iterable[dict[str, Any]]) -> None:
        for s in series:
            par_loc.setdefault(s["localite_code"], {}).update(
                {(a, m): v for a, m, v in s["mesures"]}
            )

    ajouter(SEEDS_PILOTES[grandeur].SERIES)
    for lot in ("regions", "departements"):
        ajouter(lire_series(CONTRATS_CAMS[grandeur], lot))
    ajouter(lire_series(contrat_extension(CONTRATS_CAMS[grandeur]), LOT_EXTENSION))
    return par_loc


def _comparer_au_mensuel(grandeur: str, series: list[tuple[str, float, float, Any]]) -> None:
    """Moyenne des jours servis de chaque mois - mensuel gravé, par catégorie de mois.

    Mois à lacune et années révisées (``ANNEES_REVISEES``) sont publiés à part ; les
    autres mois doivent redonner le mensuel gravé à ``TOLERANCE_MENSUEL`` près.
    """
    mensuel = _mensuel_grave(grandeur)
    ecarts: dict[str, list[tuple[float, str, int, int]]] = {
        "mois à lacune": [],
        "années révisées 2021-2025": [],
        "autres mois": [],
    }
    for code, _, _, mesures in series:
        par_mois: dict[tuple[int, int], list[float | None]] = {}
        for jour, v in mesures:
            par_mois.setdefault((jour.year, jour.month), []).append(
                None if v is None else round(v, 4)
            )
        for (annee, mois), valeurs in par_mois.items():
            servis = [v for v in valeurs if v is not None]
            ecart = math.fsum(servis) / len(servis) - mensuel[code][(annee, mois)]
            if len(servis) < len(valeurs):
                categorie = "mois à lacune"
            elif annee in ANNEES_REVISEES:
                categorie = "années révisées 2021-2025"
            else:
                categorie = "autres mois"
            ecarts[categorie].append((ecart, code, annee, mois))
    for categorie, liste in ecarts.items():
        absolus = sorted(abs(e[0]) for e in liste)
        pire = max(liste, key=lambda e: abs(e[0]))
        print(
            f"{grandeur} : moyenne des jours servis - mensuel gravé, {categorie} "
            f"({len(liste)}) : moyen {math.fsum(e[0] for e in liste) / len(liste):+.6f}, "
            f"médian |écart| {absolus[len(absolus) // 2]:.6f}, max {abs(pire[0]):.6f} "
            f"kWh/m²/jour ({pire[1]} {pire[2]}-{pire[3]:02d}), au-delà de "
            f"{TOLERANCE_MENSUEL} : {sum(a > TOLERANCE_MENSUEL for a in absolus)}"
        )
    pire = max(ecarts["autres mois"], key=lambda e: abs(e[0]))
    if abs(pire[0]) > TOLERANCE_MENSUEL:
        raise SystemExit(f"{grandeur} : écart au mensuel au-delà de {TOLERANCE_MENSUEL} : {pire}.")


def main(cache: Path, paralleles: int) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    points = points_nationaux()
    print(f"{len(points)} localités, {PLAGE}, {NB_JOURS} jours")

    def traiter(point: tuple[str, str, float, float]) -> tuple[Mesures, list[float]]:
        code, _, lat, lon = point
        return _extraire(_telecharger_en_cache(code, lat, lon, cache), lat, lon)

    with ThreadPoolExecutor(max_workers=paralleles) as pool:
        resultats = list(pool.map(traiter, points))
    fiab = sorted(f for _, fiabilites in resultats for f in fiabilites)
    print(
        f"fiabilité journalière : min {fiab[0]:.4f}, médiane {fiab[len(fiab) // 2]:.4f}, "
        f"jours < 0,9 : {sum(f < 0.9 for f in fiab)}, < 0,5 : {sum(f < 0.5 for f in fiab)} "
        f"sur {len(fiab)}"
    )
    for grandeur in GRANDEURS_CAMS:
        series = [
            (code, lat, lon, mesures[grandeur])
            for (code, _, lat, lon), (mesures, _) in zip(points, resultats, strict=True)
        ]
        cible = ecrire_series_journalieres(
            CONTRATS_CAMS_JOURNALIERS[grandeur], LOT_CAMS_JOURNALIER, series
        )
        toutes = [round(v, 4) for _, _, _, m in series for _, v in m if v is not None]
        lacunes = sum(v is None for _, _, _, m in series for _, v in m)
        print(
            f"{grandeur}: {len(series)} séries × {NB_JOURS} jours -> {cible.name} "
            f"({lacunes} lacunes ; min {min(toutes)}, moyenne "
            f"{math.fsum(toutes) / len(toutes):.3f}, max {max(toutes)})"
        )
        _comparer_au_mensuel(grandeur, series)


if __name__ == "__main__":
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--cache", type=Path, default=Path(".cache/cams_jour"))
    parseur.add_argument("--paralleles", type=int, default=4, help="requêtes ADS simultanées")
    args = parseur.parse_args()
    main(args.cache, args.paralleles)
