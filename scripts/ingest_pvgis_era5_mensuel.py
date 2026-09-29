#!/usr/bin/env python3
"""Ingesteur reproductible : GHI et DNI mensuels ERA5 via PVGIS (2005-2020), CIV.

Récupère, en **une requête par point**, l'irradiation globale horizontale (GHI,
``H(h)_m``) et l'irradiation directe normale (DNI, ``Hb(n)_m``, option
``mr_dni=1``) mensuelles de **PVGIS-ERA5** (réanalyse ECMWF servie par le JRC)
aux coordonnées des localités ivoiriennes retenues, et **régénère** un module de
seed par grandeur que les migrations lisent (les migrations n'accèdent jamais au
réseau — cf. README) :

- ``src/kuma_data_core/db/seeds/series_pvgis_era5_ghi_mensuel_civ.py`` ;
- ``src/kuma_data_core/db/seeds/series_pvgis_era5_dni_mensuel_civ.py``.

Contrats de série : ``docs/decisions/0010-triangulation-ghi-era5-troisieme-source.md``
(GHI) et ``docs/decisions/0012-triangulation-dni-pvgis-sarah3-era5.md`` (DNI) —
source ``era5_pvgis``, méthode ``reanalyse`` ; conventions partagées : ADR-0007,
normalisation : ADR-0008. ERA5 est une source de **comparaison**, jamais une
référence (ADR-0010).

**Normalisation** : PVGIS renvoie ``H(h)_m`` et ``Hb(n)_m`` = irradiations
**mensuelles totales** (kWh/m²/mois). On les ramène en **moyenne journalière**
(÷ nombre de jours réel du mois) pour respecter l'unité des grandeurs ``ghi`` et
``dni`` (``kwh_par_m2_jour``), comparables à NASA POWER, SARAH-3 et CAMS.
Conversion déterministe, pas une estimation.

Couverture : PVGIS-ERA5 démarre en 2005 ; on grave la fenêtre commune aux
autres sources, soit **2005-2020** (192 mois).

Usage : ``uv run python scripts/ingest_pvgis_era5_mensuel.py`` ; ``--lot regions``
pour un lot national (CSV gzip ``seeds/donnees/``, ADR-0015).
(mettre ``SSL_CERT_FILE`` si un proxy TLS d'entreprise intercepte la sortie).
"""

from __future__ import annotations

import argparse
import calendar
import json
import os
import ssl
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from kuma_data_core.db.seeds.localites_civ_seed_data import LOCALITES_SEED
from kuma_data_core.db.seeds.lots_civ import CONTRATS_ERA5, points_lot
from kuma_data_core.db.seeds.series_csv import ecrire_series

SOURCE_CODE = "era5_pvgis"
GRANULARITE = "mensuel"
METHODE_COLLECTE = "reanalyse"
NIVEAU_CONFIANCE = "B"  # réanalyse (A réservé au sol)
RADDATABASE = "PVGIS-ERA5"
ANNEE_DEBUT = 2005
ANNEE_FIN = 2020
POINTS: tuple[str, ...] = ("civ_dep_abidjan", "civ_dep_yamoussoukro", "civ_dep_korhogo")

# --- Grandeurs ingérées (une seule requête MRcalc par point) ------------------
# colonne : champ PVGIS (kWh/m²/mois) ; borne_max : plafond physique de la
# moyenne journalière (kWh/m²/jour), garde-fou de sanité ; entete : corps du
# docstring du seed généré (contrat de série de la grandeur).
GRANDEURS: tuple[dict[str, Any], ...] = (
    {
        "code": "ghi",
        "label": "GHI",
        "colonne": "H(h)_m",
        "borne_max": 7.0,
        "entete": (
            "**Fichier généré** par ``scripts/ingest_pvgis_era5_mensuel.py`` ; ne pas\n"
            "éditer à la main. Contrat de série : ADR-0010 (3ᵉ source, triangulation ;\n"
            "conventions : ADR-0007, normalisation : ADR-0008).\n\n"
            "Chaque mesure ``(annee, mois, valeur)`` est la **moyenne journalière** du mois\n"
            "en **kWh/m²/jour** (grandeur ``ghi`` -> unité ``kwh_par_m2_jour``), obtenue en\n"
            "divisant l'irradiation mensuelle totale PVGIS-ERA5 (``H(h)_m``, kWh/m²/mois)\n"
            "par le nombre de jours du mois. Source ``era5_pvgis`` (réanalyse ECMWF via JRC),\n"
            "méthode ``reanalyse``, confiance **B**. 12 mois/an,\n"
            "2005-2020 (192 mesures/série)."
        ),
    },
    {
        "code": "dni",
        "label": "DNI",
        "colonne": "Hb(n)_m",
        "borne_max": 9.0,
        "entete": (
            "**Fichier généré** par ``scripts/ingest_pvgis_era5_mensuel.py`` ; ne pas\n"
            "éditer à la main. Contrat de série : ADR-0012 (conventions : ADR-0007,\n"
            "normalisation : ADR-0008, statut de comparaison ERA5 : ADR-0010).\n\n"
            "Chaque mesure ``(annee, mois, valeur)`` est la **moyenne journalière** du mois\n"
            "en **kWh/m²/jour** (grandeur ``dni`` -> unité ``kwh_par_m2_jour``), obtenue en\n"
            "divisant l'irradiation directe normale mensuelle totale PVGIS-ERA5\n"
            "(``Hb(n)_m``, option ``mr_dni=1``, kWh/m²/mois) par le nombre de jours du mois.\n"
            "Source ``era5_pvgis`` (réanalyse ECMWF via JRC), méthode ``reanalyse``,\n"
            "confiance **B**. Source de COMPARAISON, jamais une référence. 12 mois/an,\n"
            "2005-2020 (192 mesures/série)."
        ),
    },
)

_SEEDS_DIR = Path(__file__).resolve().parents[1] / "src/kuma_data_core/db/seeds"


def _coord(code: str) -> tuple[str, float, float]:
    for e in LOCALITES_SEED:
        if e["code"] == code:
            return e["nom"], float(e["latitude"]), float(e["longitude"])
    raise SystemExit(f"Localité introuvable dans LOCALITES_SEED : {code!r}")


def _fetch(lat: float, lon: float) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(
        {
            "lat": lat,
            "lon": lon,
            "raddatabase": RADDATABASE,
            "horirrad": 1,  # H(h)_m : GHI
            "mr_dni": 1,  # Hb(n)_m : DNI (plan toujours normal aux rayons)
            "startyear": ANNEE_DEBUT,
            "endyear": ANNEE_FIN,
            "outputformat": "json",
        }
    )
    url = f"https://re.jrc.ec.europa.eu/api/v5_3/MRcalc?{query}"
    cafile = os.environ.get("SSL_CERT_FILE")
    ctx = ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()
    with urllib.request.urlopen(url, timeout=90, context=ctx) as reponse:
        data = json.load(reponse)
    return data["outputs"]["monthly"]


def _mesures(brut: list[dict[str, Any]], colonne: str) -> list[tuple[int, int, float]]:
    mesures: list[tuple[int, int, float]] = []
    for row in brut:
        annee, mois = int(row["year"]), int(row["month"])
        if row.get(colonne) is None:
            raise SystemExit(f"Colonne {colonne} absente de la réponse PVGIS à {annee}-{mois:02d}")
        total_mensuel = float(row[colonne])  # kWh/m²/mois
        if total_mensuel <= 0:
            raise SystemExit(
                f"Valeur ERA5 {colonne} non physique à {annee}-{mois:02d} : {total_mensuel}"
            )
        moyenne_journaliere = total_mensuel / calendar.monthrange(annee, mois)[1]
        mesures.append((annee, mois, round(moyenne_journaliere, 4)))
    mesures.sort()
    attendu = (ANNEE_FIN - ANNEE_DEBUT + 1) * 12
    if len(mesures) != attendu:
        raise SystemExit(f"Attendu {attendu} mois, obtenu {len(mesures)}")
    return mesures


def main() -> None:
    par_grandeur: dict[str, list[dict[str, Any]]] = {g["code"]: [] for g in GRANDEURS}
    for code in POINTS:
        nom, lat, lon = _coord(code)
        brut = _fetch(lat, lon)
        for grandeur in GRANDEURS:
            label = grandeur["label"]
            mesures = _mesures(brut, grandeur["colonne"])
            vmin = min(v for _, _, v in mesures)
            vmax = max(v for _, _, v in mesures)
            if not (vmin >= 0.0 and vmax <= grandeur["borne_max"]):
                raise SystemExit(f"{label} ERA5 hors bornes pour {code} : [{vmin}, {vmax}]")
            par_grandeur[grandeur["code"]].append(
                {
                    "code": f"era5_{grandeur['code']}_mensuel_{code}",
                    "libelle": (
                        f"{label} mensuel ERA5 (PVGIS) — {nom} ({ANNEE_DEBUT}-{ANNEE_FIN})"
                    ),
                    "localite_code": code,
                    "latitude": lat,
                    "longitude": lon,
                    "mesures": mesures,
                }
            )
            print(f"{code}: {len(mesures)} mois, {label} ∈ [{vmin}, {vmax}] kWh/m²/jour")
    for grandeur in GRANDEURS:
        cible = _ecrire_seed(grandeur, par_grandeur[grandeur["code"]])
        print(f"Seed régénéré : {cible}")


def main_lot(lot: str) -> None:
    """Lot national : une requête par point (GHI + DNI), sortie CSV gzip (ADR-0015)."""
    points = points_lot(lot)
    par_grandeur: dict[str, list[tuple[str, float, float, list[tuple[int, int, float]]]]] = {
        g["code"]: [] for g in GRANDEURS
    }
    for code, _, lat, lon in points:
        brut = _fetch(lat, lon)
        for grandeur in GRANDEURS:
            par_grandeur[grandeur["code"]].append(
                (code, lat, lon, _mesures(brut, grandeur["colonne"]))
            )
    for grandeur in GRANDEURS:
        contrat = CONTRATS_ERA5[grandeur["code"]]
        cible = ecrire_series(contrat, lot, par_grandeur[grandeur["code"]])
        print(f"{grandeur['code']}: {len(points)} séries -> {cible.name}")


def _dq(valeur: str) -> str:
    """Chaîne littérale en guillemets doubles (style ruff), unicode conservé."""
    return '"' + valeur.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ecrire_seed(grandeur: dict[str, Any], series: list[dict[str, Any]]) -> Path:
    lignes: list[str] = []
    for s in series:
        lignes.append("    {")
        lignes.append(f'        "code": {_dq(s["code"])},')
        lignes.append(f'        "libelle": {_dq(s["libelle"])},')
        lignes.append(f'        "localite_code": {_dq(s["localite_code"])},')
        lignes.append(f'        "latitude": {s["latitude"]!r},')
        lignes.append(f'        "longitude": {s["longitude"]!r},')
        lignes.append('        "mesures": [')
        for annee, mois, valeur in s["mesures"]:
            lignes.append(f"            ({annee}, {mois}, {valeur}),")
        lignes.append("        ],")
        lignes.append("    },")
    corps = "\n".join(lignes)
    label = grandeur["label"]
    contenu = f'''"""Séries {label} mensuel ERA5 (PVGIS) {ANNEE_DEBUT}-{ANNEE_FIN} — instance CIV.

{grandeur["entete"]}
"""

from __future__ import annotations

from typing import Any

SOURCE_CODE: str = {_dq(SOURCE_CODE)}
GRANDEUR_CODE: str = {_dq(grandeur["code"])}
GRANULARITE: str = {_dq(GRANULARITE)}
METHODE_COLLECTE: str = {_dq(METHODE_COLLECTE)}
NIVEAU_CONFIANCE: str = {_dq(NIVEAU_CONFIANCE)}
RADDATABASE: str = {_dq(RADDATABASE)}
PERIODE_DEBUT: str = "{ANNEE_DEBUT}-01-01"
PERIODE_FIN: str = "{ANNEE_FIN}-12-31"
ANNEE_DEBUT: int = {ANNEE_DEBUT}
ANNEE_FIN: int = {ANNEE_FIN}

SERIES: list[dict[str, Any]] = [
{corps}
]


_ATTENDU = (ANNEE_FIN - ANNEE_DEBUT + 1) * 12
for _s in SERIES:
    assert len(_s["mesures"]) == _ATTENDU, (_s["code"], len(_s["mesures"]))
    for _annee, _mois, _valeur in _s["mesures"]:
        assert 1 <= _mois <= 12 and ANNEE_DEBUT <= _annee <= ANNEE_FIN
        assert 0.0 <= _valeur <= {grandeur["borne_max"]}
_codes = {{_s["code"] for _s in SERIES}}
assert len(_codes) == len(SERIES), "codes de série dupliqués"
del _s, _annee, _mois, _valeur, _codes, _ATTENDU
'''
    cible = _SEEDS_DIR / f"series_pvgis_era5_{grandeur['code']}_mensuel_civ.py"
    cible.write_text(contenu, encoding="utf-8")
    return cible


if __name__ == "__main__":
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--lot", help="lot national (ex. regions) ; défaut : 3 points pilotes")
    args = parseur.parse_args()
    if args.lot:
        main_lot(args.lot)
    else:
        main()
