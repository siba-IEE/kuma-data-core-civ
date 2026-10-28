"""Contrats de la météo journalière ERA5 (CDS Copernicus) aux 142 localités.

Deuxième source journalière de la température et du vent, à côté de NASA POWER
(``T2M``, ``WS10M`` : réanalyse MERRA-2, gravés en 0035 et 0047) : la
réanalyse **ERA5** (ECMWF, Copernicus C3S), dont les moyennes mensuelles sont
gravées en 0036 (``meteo_era5_civ``, ADR-0021) et la pluie journalière en 0050.

**Produit** : valeurs **horaires instantanées** ERA5 (jeu
``reanalysis-era5-single-levels``) lues point par point dans le jeu
``reanalysis-era5-single-levels-timeseries`` du CDS, qui sert les mêmes valeurs
au nœud 0,25° demandé (même jeu que la pluie journalière, ADR-0032).

Grandeurs, variables et calcul du jour J (jour civil UTC, local en Côte
d'Ivoire, UTC+0) :

- ``t2m`` : ``2m_temperature`` (``t2m``, kelvins) ; moyenne des **24 valeurs
  horaires datées de 00 h à 23 h** du jour J, − 273,15 → °C ;
- ``vent_10m`` : composantes ``10m_u_component_of_wind`` et
  ``10m_v_component_of_wind`` (``u10``, ``v10``, m/s) ; moyenne des 24
  **vitesses** horaires ``√(u² + v²)``, datées de 00 h à 23 h — et non la norme
  des composantes moyennes, plus faible dès que la direction varie. Le jeu
  ponctuel ne sert pas la vitesse ``10m_wind_speed`` que moyenne le mensuel
  0036 : la moyenne des jours du mois reste sous lui, de 0,001 à 0,110 m/s
  (0,021 en moyenne, 59 640 mois-localités), écart publié (ADR-0034).

Pour ces variables instantanées, le jour J réunit les heures 00 h → 23 h de J
(convention du produit dérivé ``derived-era5-single-levels-daily-statistics``,
``daily_mean``, ``utc+00:00`` ; seules les variables cumulées, comme la pluie,
sont décalées d'une heure). Sommes exactes (``math.fsum``), arrondi à 4
décimales à l'écriture du CSV. Aucune interpolation, aucune valeur bouchée.

Même extraction que le mensuel 0036 et la pluie 0050 : valeur au **point de
grille 0,25° le plus proche** de chaque localité (``meteo_era5_civ.maille_era5``) ;
les 142 localités tombent dans 110 mailles. Période **1991-2025**, source
``ecmwf_era5`` (id 2), méthode ``reanalyse``, confiance B. Les bornes de sanité
sont celles de la météo journalière NASA POWER (``meteo_civ``), borne basse 0.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from kuma_data_core.db.seeds.meteo_civ import PARAMETRES_METEO_NASA
from kuma_data_core.db.seeds.meteo_era5_civ import (
    ANNEE_DEBUT_ERA5,
    ANNEE_FIN_ERA5,
    LOT_METEO_ERA5,
    VARIABLES_ERA5,
)
from kuma_data_core.db.seeds.series_csv import ContratSerie

LOT_METEO_ERA5_JOURNALIERE: str = LOT_METEO_ERA5
"""Suffixe des CSV : les 142 localités en un seul fichier par grandeur (``civ142``)."""

JEU_CDS: str = "reanalysis-era5-single-levels-timeseries"
VARIABLES_CDS: tuple[str, ...] = (
    "2m_temperature",
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
)
UNITES_SOURCE: dict[str, str] = {"t2m": "K", "u10": "m s**-1", "v10": "m s**-1"}
"""Nom de chaque variable dans le netCDF servi → unité servie."""
HEURES_PAR_JOUR: int = 24
ZERO_CELSIUS_K: float = 273.15

GRANDEURS_ERA5_JOURNALIERES: tuple[str, ...] = ("t2m", "vent_10m")


def _contrat(grandeur: str) -> ContratSerie:
    borne_jour = PARAMETRES_METEO_NASA[grandeur][5]
    return ContratSerie(
        source_code="ecmwf_era5",
        source_id=2,
        source_libelle="ERA5 (CDS)",
        prefixe_code=f"ecmwf_era5_{grandeur}_journalier",
        grandeur_code=grandeur,
        methode_collecte="reanalyse",
        annee_debut=ANNEE_DEBUT_ERA5,
        annee_fin=ANNEE_FIN_ERA5,
        borne_max=borne_jour,
        granularite="journalier",
        libelle_grandeur=VARIABLES_ERA5[grandeur].libelle,
    )


CONTRATS_METEO_ERA5_JOURNALIERS: dict[str, ContratSerie] = {
    g: _contrat(g) for g in GRANDEURS_ERA5_JOURNALIERES
}


def _exiger_24(valeurs: Sequence[float]) -> None:
    if len(valeurs) != HEURES_PAR_JOUR:
        raise ValueError(f"{len(valeurs)} valeurs horaires, {HEURES_PAR_JOUR} attendues.")


def temperature_journaliere_c(heures_k: Sequence[float]) -> float:
    """Moyenne des 24 températures horaires (K) du jour, en °C."""
    _exiger_24(heures_k)
    return math.fsum(heures_k) / HEURES_PAR_JOUR - ZERO_CELSIUS_K


def vent_journalier(u: Sequence[float], v: Sequence[float]) -> float:
    """Moyenne des 24 vitesses horaires √(u² + v²) du jour, en m/s."""
    _exiger_24(u)
    _exiger_24(v)
    return math.fsum(math.hypot(a, b) for a, b in zip(u, v, strict=True)) / HEURES_PAR_JOUR
