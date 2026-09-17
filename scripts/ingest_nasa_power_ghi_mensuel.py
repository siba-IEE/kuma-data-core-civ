#!/usr/bin/env python3
"""Ingesteur reproductible : GHI mensuel NASA POWER (1991-2020) aux points CIV.

Récupère l'irradiation globale horizontale (GHI) mensuelle de **NASA POWER**
(paramètre ``ALLSKY_SFC_SW_DWN``, communauté ``RE``) aux coordonnées des
localités ivoiriennes retenues, et **régénère** le module de seed
``src/kuma_data_core/db/seeds/series_nasa_power_ghi_mensuel_civ.py`` que la
migration lit (les migrations n'accèdent jamais au réseau — cf. README).

Contrat de série : voir ``docs/decisions/0007-serie-climatologie-nasa-power.md``.

Sémantique NASA POWER mensuel :
- la valeur d'un mois est la **moyenne journalière** de ce mois, en
  **kWh/m²/jour** (unité ``kwh_par_m2_jour``, id 63) — pas un cumul mensuel ;
- la clé ``AAAA13`` est la **moyenne annuelle** : elle est ignorée (on ne
  stocke que 12 mois/an ; la table impose d'ailleurs ``mois BETWEEN 1 AND 12``).

Usage : ``uv run python scripts/ingest_nasa_power_ghi_mensuel.py``
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

# --- Paramètres du lot ---------------------------------------------------------
PARAMETRE_NASA = "ALLSKY_SFC_SW_DWN"  # GHI (All Sky Surface Shortwave Downward Irradiance)
GRANDEUR_CODE = "ghi"
SOURCE_CODE = "nasa_power"
GRANULARITE = "mensuel"
METHODE_COLLECTE = "modele_satellitaire"
NIVEAU_CONFIANCE = "B"  # satellite/réanalyse (A réservé au sol)
ANNEE_DEBUT = 1991
ANNEE_FIN = 2020
# Points d'ingestion (niveau département : sud / centre / nord).
POINTS: tuple[str, ...] = ("civ_dep_abidjan", "civ_dep_yamoussoukro", "civ_dep_korhogo")

_CIBLE = (
    Path(__file__).resolve().parents[1]
    / "src/kuma_data_core/db/seeds/series_nasa_power_ghi_mensuel_civ.py"
)


def _coord(code: str) -> tuple[str, float, float]:
    for e in LOCALITES_SEED:
        if e["code"] == code:
            return e["nom"], float(e["latitude"]), float(e["longitude"])
    raise SystemExit(f"Localité introuvable dans LOCALITES_SEED : {code!r}")


def _fetch(lat: float, lon: float) -> dict[str, float]:
    query = urllib.parse.urlencode(
        {
            "parameters": PARAMETRE_NASA,
            "community": "RE",
            "longitude": lon,
            "latitude": lat,
            "start": ANNEE_DEBUT,
            "end": ANNEE_FIN,
            "format": "JSON",
        }
    )
    url = f"https://power.larc.nasa.gov/api/temporal/monthly/point?{query}"
    cafile = os.environ.get("SSL_CERT_FILE")
    ctx = ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()
    with urllib.request.urlopen(url, timeout=90, context=ctx) as reponse:
        data = json.load(reponse)
    return data["properties"]["parameter"][PARAMETRE_NASA]


def _mesures(brut: dict[str, float]) -> list[tuple[int, int, float]]:
    mesures: list[tuple[int, int, float]] = []
    for cle, valeur in brut.items():
        annee, mois = int(cle[:4]), int(cle[4:6])
        if mois == 13:  # moyenne annuelle NASA POWER : dérivable, non stockée
            continue
        if valeur <= -900:  # valeur de remplissage NASA POWER (-999)
            raise SystemExit(f"Valeur de remplissage NASA POWER à {annee}-{mois:02d}")
        mesures.append((annee, mois, round(float(valeur), 4)))
    mesures.sort()
    attendu = (ANNEE_FIN - ANNEE_DEBUT + 1) * 12
    if len(mesures) != attendu:
        raise SystemExit(f"Attendu {attendu} mois, obtenu {len(mesures)}")
    return mesures


def main() -> None:
    series: list[dict[str, Any]] = []
    for code in POINTS:
        nom, lat, lon = _coord(code)
        mesures = _mesures(_fetch(lat, lon))
        vmin = min(v for _, _, v in mesures)
        vmax = max(v for _, _, v in mesures)
        if not (vmin >= 0.0 and vmax <= 7.0):  # borne physique GHI journalier CIV
            raise SystemExit(f"GHI hors bornes physiques pour {code} : [{vmin}, {vmax}]")
        series.append(
            {
                "code": f"nasa_power_ghi_mensuel_{code}",
                "libelle": f"GHI mensuel NASA POWER — {nom} ({ANNEE_DEBUT}-{ANNEE_FIN})",
                "localite_code": code,
                "latitude": lat,
                "longitude": lon,
                "mesures": mesures,
            }
        )
        print(f"{code}: {len(mesures)} mois, GHI ∈ [{vmin}, {vmax}] kWh/m²/jour")

    _ecrire_seed(series)
    print(f"Seed régénéré : {_CIBLE}")


def _dq(valeur: str) -> str:
    """Chaîne littérale en guillemets doubles (style ruff), unicode conservé."""
    return '"' + valeur.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ecrire_seed(series: list[dict[str, Any]]) -> None:
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
    contenu = f'''"""Séries GHI mensuel NASA POWER (climatologie 1991-2020) — instance CIV.

**Fichier généré** par ``scripts/ingest_nasa_power_ghi_mensuel.py`` ; ne pas
éditer à la main. Contrat de série : ADR-0007.

Chaque mesure ``(annee, mois, valeur)`` est la **moyenne journalière** du mois
en **kWh/m²/jour** (grandeur ``ghi`` -> unité ``kwh_par_m2_jour``), source
``nasa_power`` (``{PARAMETRE_NASA}``), confiance **{NIVEAU_CONFIANCE}**
(satellite/réanalyse). 12 mois/an, {ANNEE_DEBUT}-{ANNEE_FIN} (360 mesures/série).
"""

from __future__ import annotations

from typing import Any

SOURCE_CODE: str = {_dq(SOURCE_CODE)}
GRANDEUR_CODE: str = {_dq(GRANDEUR_CODE)}
GRANULARITE: str = {_dq(GRANULARITE)}
METHODE_COLLECTE: str = {_dq(METHODE_COLLECTE)}
NIVEAU_CONFIANCE: str = {_dq(NIVEAU_CONFIANCE)}
PARAMETRE_NASA: str = {_dq(PARAMETRE_NASA)}
PERIODE_DEBUT: str = "{ANNEE_DEBUT}-01-01"
PERIODE_FIN: str = "{ANNEE_FIN}-12-31"

SERIES: list[dict[str, Any]] = [
{corps}
]


_ATTENDU = ({ANNEE_FIN} - {ANNEE_DEBUT} + 1) * 12
for _s in SERIES:
    assert len(_s["mesures"]) == _ATTENDU, (_s["code"], len(_s["mesures"]))
    for _annee, _mois, _valeur in _s["mesures"]:
        assert 1 <= _mois <= 12 and {ANNEE_DEBUT} <= _annee <= {ANNEE_FIN}
        assert 0.0 <= _valeur <= 7.0
_codes = {{_s["code"] for _s in SERIES}}
assert len(_codes) == len(SERIES), "codes de série dupliqués"
del _s, _annee, _mois, _valeur, _codes, _ATTENDU
'''
    _CIBLE.write_text(contenu, encoding="utf-8")


if __name__ == "__main__":
    main()
