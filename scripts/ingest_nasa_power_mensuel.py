#!/usr/bin/env python3
"""Ingesteur reproductible : irradiation mensuelle NASA POWER, CIV.

Récupère, aux coordonnées des localités ivoiriennes retenues, les grandeurs
d'irradiation mensuelles de **NASA POWER** (communauté ``RE``) et **régénère**
les modules de seed que les migrations lisent (les migrations n'accèdent jamais
au réseau — cf. README). Grandeurs couvertes :

- ``ghi`` (``ALLSKY_SFC_SW_DWN``), 1991-2020
  -> ``series_nasa_power_ghi_mensuel_civ.py`` ;
- ``dni`` (``ALLSKY_SFC_SW_DNI``), 2001-2020
  -> ``series_nasa_power_dni_mensuel_civ.py``.

La **période diffère par grandeur** : NASA POWER ne fournit le DNI qu'à partir
de 2001 (avant, la série est remplie de -999). Le garde-fou anti-remplissage
échoue explicitement plutôt que de graver un trou.

Contrat de série : ``docs/decisions/0007-serie-climatologie-nasa-power.md``.

Sémantique NASA POWER mensuel :
- la valeur d'un mois est la **moyenne journalière** de ce mois, en
  **kWh/m²/jour** (unité ``kwh_par_m2_jour``, id 63) — pas un cumul mensuel ;
- la clé ``AAAA13`` est la **moyenne annuelle** : ignorée (on ne stocke que
  12 mois/an ; la table impose ``mois BETWEEN 1 AND 12``).

Usage : ``uv run python scripts/ingest_nasa_power_mensuel.py``
(mettre ``SSL_CERT_FILE`` si un proxy TLS d'entreprise intercepte la sortie).
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from kuma_data_core.db.seeds.localites_civ_seed_data import LOCALITES_SEED

# --- Contrat partagé (identique pour toutes les grandeurs) --------------------
SOURCE_CODE = "nasa_power"
GRANULARITE = "mensuel"
METHODE_COLLECTE = "modele_satellitaire"
NIVEAU_CONFIANCE = "B"  # satellite/réanalyse (A réservé au sol)
# Points d'ingestion (niveau département : sud / centre / nord).
POINTS: tuple[str, ...] = ("civ_dep_abidjan", "civ_dep_yamoussoukro", "civ_dep_korhogo")

# --- Grandeurs ingérées -------------------------------------------------------
# borne_max : plafond physique de l'irradiation journalière moyenne (kWh/m²/jour)
# pour un garde-fou de sanité. annee_debut/annee_fin : couverture NASA POWER de
# la grandeur (le DNI ne commence qu'en 2001).
GRANDEURS: tuple[dict[str, Any], ...] = (
    {
        "code": "ghi",
        "parametre": "ALLSKY_SFC_SW_DWN",
        "label": "GHI",
        "borne_max": 7.0,
        "annee_debut": 1991,
        "annee_fin": 2020,
    },
    {
        "code": "dni",
        "parametre": "ALLSKY_SFC_SW_DNI",
        "label": "DNI",
        "borne_max": 9.0,
        "annee_debut": 2001,
        "annee_fin": 2020,
    },
)

_SEEDS_DIR = Path(__file__).resolve().parents[1] / "src/kuma_data_core/db/seeds"


def _coord(code: str) -> tuple[str, float, float]:
    for e in LOCALITES_SEED:
        if e["code"] == code:
            return e["nom"], float(e["latitude"]), float(e["longitude"])
    raise SystemExit(f"Localité introuvable dans LOCALITES_SEED : {code!r}")


def _fetch(
    parametre: str, lat: float, lon: float, annee_debut: int, annee_fin: int
) -> dict[str, float]:
    query = urllib.parse.urlencode(
        {
            "parameters": parametre,
            "community": "RE",
            "longitude": lon,
            "latitude": lat,
            "start": annee_debut,
            "end": annee_fin,
            "format": "JSON",
        }
    )
    url = f"https://power.larc.nasa.gov/api/temporal/monthly/point?{query}"
    cafile = os.environ.get("SSL_CERT_FILE")
    ctx = ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()
    with urllib.request.urlopen(url, timeout=90, context=ctx) as reponse:
        data = json.load(reponse)
    return data["properties"]["parameter"][parametre]


def _mesures(
    brut: dict[str, float], annee_debut: int, annee_fin: int
) -> list[tuple[int, int, float]]:
    mesures: list[tuple[int, int, float]] = []
    for cle, valeur in brut.items():
        annee, mois = int(cle[:4]), int(cle[4:6])
        if mois == 13:  # moyenne annuelle NASA POWER : dérivable, non stockée
            continue
        if valeur <= -900:  # valeur de remplissage NASA POWER (-999)
            raise SystemExit(f"Valeur de remplissage NASA POWER à {annee}-{mois:02d}")
        mesures.append((annee, mois, round(float(valeur), 4)))
    mesures.sort()
    attendu = (annee_fin - annee_debut + 1) * 12
    if len(mesures) != attendu:
        raise SystemExit(f"Attendu {attendu} mois, obtenu {len(mesures)}")
    return mesures


def main() -> None:
    for grandeur in GRANDEURS:
        debut, fin = grandeur["annee_debut"], grandeur["annee_fin"]
        series: list[dict[str, Any]] = []
        for code in POINTS:
            nom, lat, lon = _coord(code)
            mesures = _mesures(_fetch(grandeur["parametre"], lat, lon, debut, fin), debut, fin)
            vmin = min(v for _, _, v in mesures)
            vmax = max(v for _, _, v in mesures)
            if not (vmin >= 0.0 and vmax <= grandeur["borne_max"]):
                raise SystemExit(f"{grandeur['label']} hors bornes pour {code} : [{vmin}, {vmax}]")
            series.append(
                {
                    "code": f"nasa_power_{grandeur['code']}_mensuel_{code}",
                    "libelle": (f"{grandeur['label']} mensuel NASA POWER — {nom} ({debut}-{fin})"),
                    "localite_code": code,
                    "latitude": lat,
                    "longitude": lon,
                    "mesures": mesures,
                }
            )
            print(f"{grandeur['code']} {code}: {len(mesures)} mois, ∈ [{vmin}, {vmax}] kWh/m²/jour")
        cible = _ecrire_seed(grandeur, series)
        print(f"Seed régénéré : {cible}")


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
    gcode = grandeur["code"]
    label = grandeur["label"]
    borne = grandeur["borne_max"]
    debut, fin = grandeur["annee_debut"], grandeur["annee_fin"]
    contenu = f'''"""Séries {label} mensuel NASA POWER (climatologie {debut}-{fin}) — instance CIV.

**Fichier généré** par ``scripts/ingest_nasa_power_mensuel.py`` ; ne pas éditer
à la main. Contrat de série : ADR-0007.

Chaque mesure ``(annee, mois, valeur)`` est la **moyenne journalière** du mois
en **kWh/m²/jour** (grandeur ``{gcode}`` -> unité ``kwh_par_m2_jour``), source
``nasa_power`` (``{grandeur["parametre"]}``), confiance **{NIVEAU_CONFIANCE}**
(satellite/réanalyse). 12 mois/an, {debut}-{fin}.
"""

from __future__ import annotations

from typing import Any

SOURCE_CODE: str = {_dq(SOURCE_CODE)}
GRANDEUR_CODE: str = {_dq(gcode)}
GRANULARITE: str = {_dq(GRANULARITE)}
METHODE_COLLECTE: str = {_dq(METHODE_COLLECTE)}
NIVEAU_CONFIANCE: str = {_dq(NIVEAU_CONFIANCE)}
PARAMETRE_NASA: str = {_dq(grandeur["parametre"])}
PERIODE_DEBUT: str = "{debut}-01-01"
PERIODE_FIN: str = "{fin}-12-31"
ANNEE_DEBUT: int = {debut}
ANNEE_FIN: int = {fin}

SERIES: list[dict[str, Any]] = [
{corps}
]


_ATTENDU = (ANNEE_FIN - ANNEE_DEBUT + 1) * 12
for _s in SERIES:
    assert len(_s["mesures"]) == _ATTENDU, (_s["code"], len(_s["mesures"]))
    for _annee, _mois, _valeur in _s["mesures"]:
        assert 1 <= _mois <= 12 and ANNEE_DEBUT <= _annee <= ANNEE_FIN
        assert 0.0 <= _valeur <= {borne}
_codes = {{_s["code"] for _s in SERIES}}
assert len(_codes) == len(SERIES), "codes de série dupliqués"
del _s, _annee, _mois, _valeur, _codes, _ATTENDU
'''
    cible = _SEEDS_DIR / f"series_nasa_power_{gcode}_mensuel_civ.py"
    cible.write_text(contenu, encoding="utf-8")
    return cible


if __name__ == "__main__":
    main()
