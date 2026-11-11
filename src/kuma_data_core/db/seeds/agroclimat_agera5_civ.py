"""Contrats de l'agroclimat AgERA5 aux 142 localités (ADR-0040).

**AgERA5** (Copernicus C3S, Wageningen Environmental Research ; jeu CDS
``sis-agrometeorological-indicators``, version 2.0) : indicateurs
agrométéorologiques journaliers tirés des valeurs horaires d'ERA5, ramenés sur
une grille de 0,1° avec une correction d'altitude. Quatre grandeurs nouvelles
au référentiel, utiles à l'agriculture et absentes des autres sources :

| Grandeur | Variable CDS | Variable netCDF | Unité servie → référentiel |
|---|---|---|---|
| ``et0`` | ``reference_evapotranspiration`` | ``ReferenceET_PenmanMonteith_FAO56`` | mm d-1 → mm/jour |
| ``t2m_min`` | ``2m_temperature``, ``24_hour_minimum`` | ``Temperature_Air_2m_Min_24h`` | K → °C |
| ``t2m_max`` | ``2m_temperature``, ``24_hour_maximum`` | ``Temperature_Air_2m_Max_24h`` | K → °C |
| ``vpd_tmax`` | ``vapour_pressure_deficit_at_maximum_temperature`` | ``Vapour_Pressure_Deficit_at_Maximum_Temperature`` | hPa → kPa |

**Jour** : AgERA5 agrège les heures d'ERA5 sur le jour local 00 h-00 h
(attribut ``temporal_aggregation`` « 00-00LT ») ; en Côte d'Ivoire (UTC+0), le
jour civil local.

**Grille** : nœuds aux multiples de 0,1° ; chaque valeur vaut pour la maille de
0,1° centrée sur le nœud. **Maille retenue** (``maille_agera5``) : celle qui
contient la localité, en arithmétique exacte. Une localité sur une limite de
maille (coordonnée multiple impaire de 0,05°, 38 des 142) est rattachée à la
maille au sud et à l'est de la limite, convention des intervalles semi-ouverts
de GDAL déjà suivie pour CHIRPS (0055). 119 mailles pour 142 localités, toutes
terrestres (AgERA5 masque la mer).

**Mensuel** : moyenne des jours du mois (AgERA5 ne sert que du journalier),
dans l'unité du journalier.

Source ``agera5`` (**id 19**), méthode ``reanalyse``, confiance B, période
**1991-2025**. Licence CC BY 4.0 ; citation : Boogaard, H., Schubert, J.,
De Wit, A., Lazebnik, J., Hutjes, R., Van der Grijn, G. (2020) : Agrometeorological
indicators from 1979 to present derived from reanalysis, Copernicus C3S Climate
Data Store, doi:10.24381/cds.6c68c9bb.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from kuma_data_core.db.seeds.meteo_era5_civ import (
    ANNEE_DEBUT_ERA5,
    ANNEE_FIN_ERA5,
    LOT_METEO_ERA5,
)
from kuma_data_core.db.seeds.series_csv import ContratSerie

LOT_AGERA5: str = LOT_METEO_ERA5
"""Suffixe des CSV : les 142 localités en un seul fichier (``civ142``)."""

JEU_CDS: str = "sis-agrometeorological-indicators"
VERSION_CDS: str = "2_0"
VERSION_FICHIERS: str = "final-v2.0.0"
"""Marque des noms de fichiers servis (``..._AAAAMMJJ_final-v2.0.0...nc``)."""

ZONE_CDS: tuple[float, float, float, float] = (10.7, -8.6, 4.3, -2.6)
"""Nord, ouest, sud, est : couvre les 119 mailles (nœuds 10,6 à 4,3 N, 8,5 à 2,6 O)."""

SOURCE_ID: int = 19
SOURCE_CODE: str = "agera5"
SOURCE_LIBELLE: str = "AgERA5"
DOI: str = "10.24381/cds.6c68c9bb"

ZERO_CELSIUS_K: float = 273.15


@dataclass(frozen=True)
class GrandeurAgera5:
    """Une grandeur du lot : variable demandée au CDS, variable lue, unités, bornes."""

    code: str
    libelle: str
    variable_cds: str
    statistique: str | None
    variable_netcdf: str
    unite_source: str
    unite_referentiel: str
    borne_jour: float
    borne_mois: float

    def convertir(self, valeur: float) -> float:
        """Valeur servie → unité du référentiel (K → °C, hPa → kPa, mm/jour inchangé)."""
        if self.unite_source == "K":
            return valeur - ZERO_CELSIUS_K
        if self.unite_source == "hPa":
            return valeur / 10.0
        return valeur


GRANDEURS_AGERA5: dict[str, GrandeurAgera5] = {
    g.code: g
    for g in (
        GrandeurAgera5(
            "et0",
            "Évapotranspiration de référence",
            "reference_evapotranspiration",
            None,
            "ReferenceET_PenmanMonteith_FAO56",
            "mm d-1",
            "mm_par_jour",
            15.0,
            15.0,
        ),
        GrandeurAgera5(
            "t2m_min",
            "Température minimale à 2 m",
            "2m_temperature",
            "24_hour_minimum",
            "Temperature_Air_2m_Min_24h",
            "K",
            "degree_celsius",
            50.0,
            45.0,
        ),
        GrandeurAgera5(
            "t2m_max",
            "Température maximale à 2 m",
            "2m_temperature",
            "24_hour_maximum",
            "Temperature_Air_2m_Max_24h",
            "K",
            "degree_celsius",
            50.0,
            45.0,
        ),
        GrandeurAgera5(
            "vpd_tmax",
            "Déficit de pression de vapeur à la température maximale",
            "vapour_pressure_deficit_at_maximum_temperature",
            None,
            "Vapour_Pressure_Deficit_at_Maximum_Temperature",
            "hPa",
            "kilopascal",
            10.0,
            10.0,
        ),
    )
}


def requete_cds(annee: int, grandeur: str) -> dict[str, object]:
    """Requête CDS d'une grandeur sur une année entière, zone de la CIV.

    Une grandeur et une année par requête : le CDS plafonne le coût d'une requête
    à 400 (une année d'une grandeur coûte 372 ; plusieurs variables ou statistiques
    se multiplient).
    """
    g = GRANDEURS_AGERA5[grandeur]
    requete: dict[str, object] = {
        "variable": [g.variable_cds],
        "year": [str(annee)],
        "month": [f"{m:02d}" for m in range(1, 13)],
        "day": [f"{j:02d}" for j in range(1, 32)],
        "version": VERSION_CDS,
        "area": list(ZONE_CDS),
    }
    if g.statistique is not None:
        requete["statistic"] = [g.statistique]
    return requete


def _contrat(grandeur: GrandeurAgera5, granularite: str) -> ContratSerie:
    return ContratSerie(
        source_code=SOURCE_CODE,
        source_id=SOURCE_ID,
        source_libelle=SOURCE_LIBELLE,
        prefixe_code=f"{SOURCE_CODE}_{grandeur.code}_{granularite}",
        grandeur_code=grandeur.code,
        methode_collecte="reanalyse",
        annee_debut=ANNEE_DEBUT_ERA5,
        annee_fin=ANNEE_FIN_ERA5,
        borne_max=grandeur.borne_mois if granularite == "mensuel" else grandeur.borne_jour,
        granularite=granularite,
        libelle_grandeur=grandeur.libelle,
    )


CONTRATS_AGERA5_JOURNALIERS: dict[str, ContratSerie] = {
    code: _contrat(g, "journalier") for code, g in GRANDEURS_AGERA5.items()
}
CONTRATS_AGERA5_MENSUELS: dict[str, ContratSerie] = {
    code: _contrat(g, "mensuel") for code, g in GRANDEURS_AGERA5.items()
}


def _dixiemes(coordonnee: float) -> Fraction:
    """Coordonnée en dixièmes de degré, valeur décimale exacte du littéral du référentiel."""
    return Fraction(Decimal(repr(coordonnee))) * 10


def maille_agera5(latitude: float, longitude: float) -> tuple[int, int]:
    """Nœud ``(latitude, longitude)`` en dixièmes de degré de la maille qui contient le point.

    Maille de 0,1° centrée sur le nœud. Un point sur une limite appartient à la maille
    au sud (limite horizontale) et à l'est (limite verticale), comme pour CHIRPS.
    """
    demi = Fraction(1, 2)
    return math.ceil(_dixiemes(latitude) - demi), math.floor(_dixiemes(longitude) + demi)


def sur_une_limite(latitude: float, longitude: float) -> bool:
    """Vrai si le point tombe exactement sur une limite de maille de 0,1°."""
    return any((_dixiemes(c) - Fraction(1, 2)).denominator == 1 for c in (latitude, longitude))
