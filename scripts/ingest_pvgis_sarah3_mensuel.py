#!/usr/bin/env python3
"""Ingesteur reproductible : GHI mensuel SARAH-3 via PVGIS (2005-2020), CIV.

Récupère l'irradiation globale horizontale (GHI) mensuelle de **PVGIS-SARAH3**
(service JRC/CM SAF) aux coordonnées des localités ivoiriennes retenues, et
**régénère** le module de seed
``src/kuma_data_core/db/seeds/series_pvgis_sarah3_ghi_mensuel_civ.py`` que la
migration lit (les migrations n'accèdent jamais au réseau — cf. README).

Contrat de série : ``docs/decisions/0008-serie-sarah3-pvgis.md`` (source
``sarah3_monthly`` id 11 ; conventions partagées : ADR-0007).

**Normalisation** : PVGIS renvoie ``H(h)_m`` = irradiation **mensuelle totale**
(kWh/m²/mois). On la ramène en **moyenne journalière** (÷ nombre de jours réel
du mois) pour respecter l'unité de la grandeur ``ghi`` (``kwh_par_m2_jour``,
kWh/m²/jour), comparable au GHI NASA POWER. Conversion déterministe, pas une
estimation.

Couverture : SARAH-3 via PVGIS démarre en 2005 ; on grave le recouvrement avec
le GHI NASA POWER, soit **2005-2020** (192 mois).

Usage : ``uv run python scripts/ingest_pvgis_sarah3_mensuel.py``
(mettre ``SSL_CERT_FILE`` si un proxy TLS d'entreprise intercepte la sortie).
"""

from __future__ import annotations

import calendar
import json
import os
import ssl
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from kuma_data_core.db.seeds.localites_civ_seed_data import LOCALITES_SEED

SOURCE_CODE = "sarah3_monthly"
GRANDEUR_CODE = "ghi"
GRANULARITE = "mensuel"
METHODE_COLLECTE = "modele_satellitaire"
NIVEAU_CONFIANCE = "B"  # satellite (A réservé au sol)
RADDATABASE = "PVGIS-SARAH3"
ANNEE_DEBUT = 2005
ANNEE_FIN = 2020
BORNE_MAX = 7.0  # GHI journalier moyen (kWh/m²/jour), garde-fou de sanité
POINTS: tuple[str, ...] = ("civ_dep_abidjan", "civ_dep_yamoussoukro", "civ_dep_korhogo")

_CIBLE = (
    Path(__file__).resolve().parents[1]
    / "src/kuma_data_core/db/seeds/series_pvgis_sarah3_ghi_mensuel_civ.py"
)


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
            "horirrad": 1,
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


def _mesures(brut: list[dict[str, Any]]) -> list[tuple[int, int, float]]:
    mesures: list[tuple[int, int, float]] = []
    for row in brut:
        annee, mois = int(row["year"]), int(row["month"])
        total_mensuel = float(row["H(h)_m"])  # kWh/m²/mois
        if total_mensuel <= 0:
            raise SystemExit(f"Valeur SARAH-3 non physique à {annee}-{mois:02d} : {total_mensuel}")
        moyenne_journaliere = total_mensuel / calendar.monthrange(annee, mois)[1]
        mesures.append((annee, mois, round(moyenne_journaliere, 4)))
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
        if not (vmin >= 0.0 and vmax <= BORNE_MAX):
            raise SystemExit(f"GHI SARAH-3 hors bornes pour {code} : [{vmin}, {vmax}]")
        series.append(
            {
                "code": f"sarah3_ghi_mensuel_{code}",
                "libelle": f"GHI mensuel SARAH-3 (PVGIS) — {nom} ({ANNEE_DEBUT}-{ANNEE_FIN})",
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
    contenu = f'''"""Séries GHI mensuel SARAH-3 (PVGIS) 2005-2020 — instance CIV.

**Fichier généré** par ``scripts/ingest_pvgis_sarah3_mensuel.py`` ; ne pas
éditer à la main. Contrat de série : ADR-0008 (conventions : ADR-0007).

Chaque mesure ``(annee, mois, valeur)`` est la **moyenne journalière** du mois
en **kWh/m²/jour** (grandeur ``ghi`` -> unité ``kwh_par_m2_jour``), obtenue en
divisant l'irradiation mensuelle totale PVGIS-SARAH3 (``H(h)_m``, kWh/m²/mois)
par le nombre de jours du mois. Source ``sarah3_monthly`` (id 11), confiance
**{NIVEAU_CONFIANCE}** (satellite). 12 mois/an, {ANNEE_DEBUT}-{ANNEE_FIN}
(192 mesures/série).
"""

from __future__ import annotations

from typing import Any

SOURCE_CODE: str = {_dq(SOURCE_CODE)}
GRANDEUR_CODE: str = {_dq(GRANDEUR_CODE)}
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
        assert 0.0 <= _valeur <= {BORNE_MAX}
_codes = {{_s["code"] for _s in SERIES}}
assert len(_codes) == len(SERIES), "codes de série dupliqués"
del _s, _annee, _mois, _valeur, _codes, _ATTENDU
'''
    _CIBLE.write_text(contenu, encoding="utf-8")


if __name__ == "__main__":
    main()
