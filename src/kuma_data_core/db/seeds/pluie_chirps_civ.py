"""Contrat de la pluie journalière CHIRPS v3.0 aux 142 localités.

Quatrième source journalière de la pluie, à côté de NASA POWER
(``PRECTOTCORR``, 0035 et 0047), d'ERA5 (0050) et de GPM IMERG (0052) :
**CHIRPS** (Climate Hazards Center InfraRed Precipitation with Station data,
Climate Hazards Center, université de Californie à Santa Barbara ; Funk et al.),
version **3.0** (publiée le 2025-01-01 ; la version 2.0 s'arrête en
décembre 2026).

**Produit** (``README-CHIRPSv3.0.txt`` et ``daily/readme.txt`` du CHC, sondage
du 2026-10-28) : estimation satellitaire infrarouge (CHIRP3) fondue avec les
pluviomètres (plus de 90 sources de stations, corrigées du sous-captage) au pas
**pentadaire et mensuel**, sur une grille de **0,05°**. CHIRPS est d'abord un
produit pentadaire : le **journalier n'est pas un produit indépendant**. Il
répartit le cumul de chaque pentade entre ses jours selon les proportions
journalières d'un autre produit, interpolé bilinéairement sur la grille de
0,05° :

- ``rnl`` (retenu) : proportions journalières d'**ERA5**, de 1981 à nos jours ;
- ``sat`` : proportions journalières d'**IMERG Late V07**, depuis 1998.

Si ERA5 ne donne aucune pluie sur une pentade où CHIRPS en a, le cumul est
réparti également entre les jours, ce qui peut créer de faux épisodes de jours
pluvieux consécutifs. Le cumul de chaque pentade est donc la vraie information
de CHIRPS ; le calendrier des pluies dans la pentade est celui d'ERA5. Le CHC
ne recommande pas l'un ou l'autre ; ``rnl`` couvre toute la période
1991-2025, comme les autres séries journalières.

**Jour** : le jour D couvre environ 00 h UTC le jour D → 00 h UTC le jour D + 1
(convention de la désagrégation ; les fenêtres d'observation des stations
varient), soit le jour civil local en Côte d'Ivoire (UTC+0).

**Fichiers lus** : ``daily/final/rnl/cogs/<année>/chirps-v3.0.rnl.<AAAA.MM.JJ>.cog``
(GeoTIFF optimisés pour la lecture par morceaux, mêmes valeurs que les
GeoTIFF du même dossier, vérifié jour par jour sur un échantillon). Grille
quasi globale de 7 200 × 2 400 mailles de 0,05°, du 180° O au 180° E et du
60° N au 60° S, en mm/jour (``float32``), océan à −9999.

**Maille retenue** (``maille_chirps``) : la maille de 0,05° qui contient la
localité, calculée en arithmétique exacte depuis les coordonnées décimales du
référentiel. Beaucoup de coordonnées du référentiel sont des multiples de
0,05° (degrés-minutes multiples de 3′) et tombent sur une limite de maille :
la localité est alors rattachée à la maille dont elle borde le côté nord ou
ouest — la maille au sud et à l'est de la limite —, convention des intervalles
semi-ouverts de GDAL (une maille contient ses bords nord et ouest). Valeur
servie sans interpolation ni bouchage.

Source ``chirps`` (**id 18**), méthode ``modele_satellitaire`` (estimation
satellitaire fondue avec les pluviomètres), confiance B, période **1991-2025**.
La borne de sanité est celle des autres pluies journalières (1000 mm/jour).
"""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal
from fractions import Fraction

from kuma_data_core.db.seeds.meteo_civ import BORNE_PRECIPITATION_JOURNALIERE
from kuma_data_core.db.seeds.meteo_era5_civ import (
    ANNEE_DEBUT_ERA5,
    ANNEE_FIN_ERA5,
    LOT_METEO_ERA5,
)
from kuma_data_core.db.seeds.series_csv import ContratSerie

LOT_PLUIE_CHIRPS: str = LOT_METEO_ERA5
"""Suffixe du CSV : les 142 localités en un seul fichier (``civ142``)."""

VERSION_CHIRPS: str = "3.0"
DESAGREGATION: str = "rnl"
"""Proportions journalières d'ERA5 (``rnl``), et non d'IMERG (``sat``, depuis 1998)."""

URL_COG: str = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/final/rnl/cogs"
URL_TIF: str = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/final/rnl"

PAS_DEG: Fraction = Fraction(1, 20)
"""0,05° exactement."""
LONGITUDE_OUEST: int = -180
LATITUDE_NORD: int = 60
LARGEUR: int = 7200
HAUTEUR: int = 2400
VALEUR_OCEAN: float = -9999.0
UNITE_REFERENTIEL: str = "mm_par_jour"

CONTRAT_PLUIE_CHIRPS: ContratSerie = ContratSerie(
    source_code="chirps",
    source_id=18,
    source_libelle="CHIRPS v3",
    prefixe_code="chirps_precipitation_journalier",
    grandeur_code="precipitation",
    methode_collecte="modele_satellitaire",
    annee_debut=ANNEE_DEBUT_ERA5,
    annee_fin=ANNEE_FIN_ERA5,
    borne_max=BORNE_PRECIPITATION_JOURNALIERE,
    granularite="journalier",
    libelle_grandeur="Précipitations",
)


def _exact(coordonnee: float) -> Fraction:
    """Valeur décimale exacte du littéral du référentiel (``repr`` : plus courte écriture)."""
    return Fraction(Decimal(repr(coordonnee)))


def maille_chirps(latitude: float, longitude: float) -> tuple[int, int]:
    """``(ligne, colonne)`` de la maille de 0,05° qui contient le point.

    Arithmétique exacte : un point sur une limite de maille appartient à la maille
    située au sud (limite horizontale) et à l'est (limite verticale) de la limite.
    """
    ligne = math.floor((LATITUDE_NORD - _exact(latitude)) / PAS_DEG)
    colonne = math.floor((_exact(longitude) - LONGITUDE_OUEST) / PAS_DEG)
    if not (0 <= ligne < HAUTEUR and 0 <= colonne < LARGEUR):
        raise ValueError(f"Point ({latitude}, {longitude}) hors de la grille CHIRPS.")
    return ligne, colonne


def sur_une_limite(latitude: float, longitude: float) -> bool:
    """Vrai si le point tombe exactement sur une limite de maille (en latitude ou longitude)."""
    return any(
        ((_exact(c) - origine) / PAS_DEG).denominator == 1
        for c, origine in ((latitude, LATITUDE_NORD), (longitude, LONGITUDE_OUEST))
    )


def nom_fichier_jour(jour: date) -> str:
    return f"chirps-v3.0.{DESAGREGATION}.{jour:%Y.%m.%d}"


def url_cog(jour: date) -> str:
    return f"{URL_COG}/{jour.year}/{nom_fichier_jour(jour)}.cog"


def url_tif(jour: date) -> str:
    return f"{URL_TIF}/{jour.year}/{nom_fichier_jour(jour)}.tif"
