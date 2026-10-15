"""Contrats des séries météorologiques NASA POWER sur la Côte d'Ivoire.

Grandeurs déjà présentes au référentiel (0002) : température (``t2m``), humidité
relative (``rh2m``), vent à 2 et 10 m (``vent_2m``, ``vent_10m``), précipitations
(``precipitation``) et albédo de surface (``albedo_surface``). Elles alimentent
les grandeurs métier (correction thermique du productible, humidex, degrés-jours,
salissure, POA bifacial).

Origine des paramètres NASA POWER (sondage du 2026-10-15) :

- ``T2M``, ``RH2M``, ``WS2M``, ``WS10M``, ``PRECTOTCORR`` : réanalyse **MERRA-2**
  (méthode ``reanalyse``), servis sans lacune depuis 1981 ;
- ``ALLSKY_SRF_ALB`` : **CERES SYN1deg** (méthode ``modele_satellitaire``), valeur
  de remplissage avant 2001 — même rupture que le DNI et le DHI (ADR-0013).

Périodes alignées sur le GHI : **1991-2025** (normale OMM 1991-2020 prolongée,
ADR-0018), albédo **2001-2025**. Mêmes périmètres que le rayonnement : mensuel aux
**142 localités** (``points_nationaux``), journalier aux **34 localités**
(``points_journalier`` : 3 pilotes + 31 régions).

Les bornes sont des garde-fous de sanité (rejet à la lecture du CSV), pas des
valeurs attendues ; la borne basse est 0 pour toutes les grandeurs. Celles des
précipitations (60 mm/jour en mensuel, 1000 en journalier) couvrent des valeurs
**aberrantes servies telles quelles** par NASA POWER — San-Pédro, septembre 2022 :
56,28 mm/jour en moyenne mensuelle, 726,74 mm le 16 (ERA5 du CDS : 8,3 à 12,8 mm) —
gravées sans correction et signalées dans la note publique des séries (ADR-0019,
ADR-0032).

Unités : aucune conversion. L'unité servie par NASA POWER
(``parameters.<P>.units``) et l'unité de la grandeur au référentiel doivent
correspondre (``UNITES_NASA``, ``UNITES_REFERENTIEL``) ; un écart arrête
l'ingesteur ou la migration.
"""

from __future__ import annotations

from kuma_data_core.db.seeds.series_csv import ContratSerie

LOT_METEO_MENSUEL: str = "civ142"
"""Suffixe des CSV mensuels : les 142 localités en un seul fichier par grandeur."""

LOT_METEO_JOURNALIER: str = "pilotes_regions"
"""Suffixe des CSV journaliers : mêmes 34 localités que le rayonnement journalier."""

ANNEE_DEBUT_METEO: int = 1991
ANNEE_FIN_METEO: int = 2025

BORNE_PRECIPITATION_MENSUELLE: float = 60.0
"""mm/jour : couvre le maximum servi (56,28, San-Pédro 2022-09), environ 1 800 mm/mois."""

BORNE_PRECIPITATION_JOURNALIERE: float = 1000.0
"""mm/jour : couvre le maximum servi (726,74, San-Pédro le 16/09/2022)."""

# grandeur -> (paramètre NASA POWER, méthode, première année, libellé,
#              borne mensuelle, borne journalière)
PARAMETRES_METEO_NASA: dict[str, tuple[str, str, int, str, float, float]] = {
    "t2m": ("T2M", "reanalyse", 1991, "Température à 2 m", 45.0, 50.0),
    "rh2m": ("RH2M", "reanalyse", 1991, "Humidité relative à 2 m", 100.0, 100.0),
    "vent_2m": ("WS2M", "reanalyse", 1991, "Vent à 2 m", 15.0, 25.0),
    "vent_10m": ("WS10M", "reanalyse", 1991, "Vent à 10 m", 20.0, 30.0),
    "precipitation": (
        "PRECTOTCORR",
        "reanalyse",
        1991,
        "Précipitations",
        BORNE_PRECIPITATION_MENSUELLE,
        BORNE_PRECIPITATION_JOURNALIERE,
    ),
    "albedo_surface": (
        "ALLSKY_SRF_ALB",
        "modele_satellitaire",
        2001,
        "Albédo de surface",
        1.0,
        1.0,
    ),
}


def _contrat(grandeur: str, granularite: str) -> ContratSerie:
    _, methode, debut, libelle, borne_mois, borne_jour = PARAMETRES_METEO_NASA[grandeur]
    return ContratSerie(
        source_code="nasa_power",
        source_id=1,
        source_libelle="NASA POWER",
        prefixe_code=f"nasa_power_{grandeur}_{granularite}",
        grandeur_code=grandeur,
        methode_collecte=methode,
        annee_debut=debut,
        annee_fin=ANNEE_FIN_METEO,
        borne_max=borne_mois if granularite == "mensuel" else borne_jour,
        granularite=granularite,
        libelle_grandeur=libelle,
    )


CONTRATS_METEO_NASA_MENSUELS: dict[str, ContratSerie] = {
    g: _contrat(g, "mensuel") for g in PARAMETRES_METEO_NASA
}
CONTRATS_METEO_NASA_JOURNALIERS: dict[str, ContratSerie] = {
    g: _contrat(g, "journalier") for g in PARAMETRES_METEO_NASA
}

# Unité servie par NASA POWER (``parameters.<P>.units``, sondage du 2026-10-15).
UNITES_NASA: dict[str, str] = {
    "t2m": "C",
    "rh2m": "%",
    "vent_2m": "m/s",
    "vent_10m": "m/s",
    "precipitation": "mm/day",
    "albedo_surface": "dimensionless",
}

# Code de l'unité de chaque grandeur au référentiel (``unites.code``, seed 0002).
UNITES_REFERENTIEL: dict[str, str] = {
    "t2m": "degree_celsius",
    "rh2m": "pourcent",
    "vent_2m": "metre_par_seconde",
    "vent_10m": "metre_par_seconde",
    "precipitation": "mm_par_jour",
    "albedo_surface": "sans_unite",
}
