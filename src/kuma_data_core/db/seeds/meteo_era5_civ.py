"""Contrats des séries météorologiques ERA5 (CDS Copernicus) sur la Côte d'Ivoire.

Deuxième source des grandeurs météo, à côté de NASA POWER (``meteo_civ``) : la
réanalyse **ERA5** (ECMWF, Copernicus C3S), lue dans les **moyennes mensuelles**
du Climate Data Store (jeu ``reanalysis-era5-single-levels-monthly-means``,
produit ``monthly_averaged_reanalysis``). Source ``ecmwf_era5`` (id 2, seedée en
0002), méthode ``reanalyse``, confiance B (ADR-0021).

Grandeurs, variable CDS et conversion (documentation ERA5, section « Monthly
means ») :

- ``t2m`` : ``2m_temperature``, moyenne des 24 heures UTC de chaque jour du mois,
  en kelvins ; − 273,15 → °C ;
- ``vent_10m`` : ``10m_wind_speed`` (paramètre 207), moyenne des **vitesses**
  horaires, en m/s, sans conversion — et non la norme des composantes ``u`` et
  ``v`` moyennes, plus faible dès que la direction varie ;
- ``precipitation`` : ``total_precipitation``, cumul du mois entier (00 UTC le
  1ᵉʳ → 00 UTC le 1ᵉʳ du mois suivant) ramené à un jour, en mètres d'eau par
  jour ; × 1000 → mm/jour.

Abstentions motivées (ADR-0021) : ``rh2m`` (ERA5 ne la sert pas ; la recalculer
depuis les moyennes mensuelles de T et Td est biaisée) et ``albedo_surface``
(``forecast_albedo`` ne vaut que pour le rayonnement diffus).

Valeur au **point de grille 0,25° le plus proche** de chaque localité, sans
interpolation : les 142 localités (``points_nationaux``) tombent dans 110 mailles
distinctes. Période **1991-2025** (normale OMM 1991-2020 prolongée, comme NASA
POWER, ADR-0018). Les bornes sont les garde-fous de sanité de NASA POWER mensuel
(``meteo_civ``), borne basse 0.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from kuma_data_core.db.seeds.meteo_civ import BORNE_PRECIPITATION_MENSUELLE, LOT_METEO_MENSUEL
from kuma_data_core.db.seeds.series_csv import ContratSerie

LOT_METEO_ERA5: str = LOT_METEO_MENSUEL
"""Suffixe des CSV : les 142 localités en un seul fichier par grandeur (``civ142``)."""

ANNEE_DEBUT_ERA5: int = 1991
ANNEE_FIN_ERA5: int = 2025
PAS_GRILLE_DEG: float = 0.25
"""Résolution de la grille régulière latitude/longitude servie par le CDS."""


@dataclass(frozen=True)
class VariableEra5:
    """Une grandeur gravée : variable CDS, nom dans le netCDF et conversion affine."""

    grandeur: str
    variable_cds: str  # nom de la variable dans la requête CDS
    nom_netcdf: str  # nom de la variable dans le fichier netCDF servi
    unite_source: str  # unité servie par le CDS
    unite_referentiel: str  # code de l'unité de la grandeur au référentiel (table unites)
    facteur: float
    decalage: float
    libelle: str
    borne_max: float

    def convertir(self, valeur_source: float) -> float:
        """Unité servie → unité de la grandeur au référentiel."""
        return valeur_source * self.facteur + self.decalage


VARIABLES_ERA5: dict[str, VariableEra5] = {
    "t2m": VariableEra5(
        grandeur="t2m",
        variable_cds="2m_temperature",
        nom_netcdf="t2m",
        unite_source="K",
        unite_referentiel="degree_celsius",
        facteur=1.0,
        decalage=-273.15,
        libelle="Température à 2 m",
        borne_max=45.0,
    ),
    "vent_10m": VariableEra5(
        grandeur="vent_10m",
        variable_cds="10m_wind_speed",
        nom_netcdf="si10",
        unite_source="m s**-1",
        unite_referentiel="metre_par_seconde",
        facteur=1.0,
        decalage=0.0,
        libelle="Vent à 10 m",
        borne_max=20.0,
    ),
    "precipitation": VariableEra5(
        grandeur="precipitation",
        variable_cds="total_precipitation",
        nom_netcdf="tp",
        unite_source="m",  # mètres d'eau par jour dans les moyennes mensuelles
        unite_referentiel="mm_par_jour",
        facteur=1000.0,
        decalage=0.0,
        libelle="Précipitations",
        borne_max=BORNE_PRECIPITATION_MENSUELLE,
    ),
}


def _contrat(v: VariableEra5) -> ContratSerie:
    return ContratSerie(
        source_code="ecmwf_era5",
        source_id=2,
        source_libelle="ERA5 (CDS)",
        prefixe_code=f"ecmwf_era5_{v.grandeur}_mensuel",
        grandeur_code=v.grandeur,
        methode_collecte="reanalyse",
        annee_debut=ANNEE_DEBUT_ERA5,
        annee_fin=ANNEE_FIN_ERA5,
        borne_max=v.borne_max,
        libelle_grandeur=v.libelle,
    )


CONTRATS_METEO_ERA5_MENSUELS: dict[str, ContratSerie] = {
    g: _contrat(v) for g, v in VARIABLES_ERA5.items()
}


def maille_era5(latitude: float, longitude: float) -> tuple[float, float]:
    """Centre de la maille 0,25° la plus proche ; ``ValueError`` si le point est à égale distance.

    Règle sans ambiguïté : un point situé exactement à mi-chemin de deux nœuds
    est refusé plutôt que départagé arbitrairement (aucun des 142 ne l'est).
    """
    noeud: list[float] = []
    for coord in (latitude, longitude):
        pas = coord / PAS_GRILLE_DEG
        if math.isclose(abs(pas - math.floor(pas)), 0.5, abs_tol=1e-9):
            raise ValueError(f"Point ({latitude}, {longitude}) à égale distance de deux nœuds.")
        noeud.append(round(pas) * PAS_GRILLE_DEG)
    return noeud[0], noeud[1]
