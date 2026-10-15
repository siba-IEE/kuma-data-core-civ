"""Contrat de la pluie journalière ERA5 (CDS Copernicus) aux 142 localités.

Deuxième source journalière de la pluie, à côté de NASA POWER
(``PRECTOTCORR``, MERRA-2, gravée en 0035 et 0047) : la réanalyse **ERA5**
(ECMWF, Copernicus C3S), dont la pluie mensuelle est déjà gravée en 0036
(``meteo_era5_civ``, ADR-0021). Elle sert à recouper jour par jour les pluies
NASA POWER douteuses (jours au-delà de 200 mm, rupture des fortes pluies vers
2017, ADR-0020 et ADR-0031).

**Produit** : cumuls horaires ERA5 ``total_precipitation`` (jeu
``reanalysis-era5-single-levels``), lus point par point dans le jeu
``reanalysis-era5-single-levels-timeseries`` du CDS, qui sert les mêmes valeurs
au nœud 0,25° demandé (identité à l'octet près vérifiée aux 110 nœuds sur
5 904 heures chacun, de 2000 à 2026, en ERA5 définitif), et **sommés sur le
jour civil UTC**.

**Convention des cumuls** (documentation ECMWF, « ERA5: data documentation » et
« ERA5 family post-processed daily statistics ») : un cumul horaire ERA5 daté
HH couvre l'heure qui **finit** à HH ; le cumul daté 00 h du jour J + 1 couvre
donc 23 h → 24 h du jour J. Le cumul du jour J somme les 24 cumuls horaires
datés de **01 h le jour J à 00 h le jour J + 1** (``DECALAGE_HEURES``), soit
00 h → 24 h UTC. La Côte d'Ivoire étant en UTC+0, c'est le jour civil local.
C'est aussi la convention du produit dérivé
``derived-era5-single-levels-daily-statistics`` (``daily_sum``, fuseau
``utc+00:00``, décalage d'une heure pour les variables cumulées), écarté pour
son coût : une année par requête, calculée à la demande, requête d'essai encore
en file après une heure au sondage du 2026-10-15.

Vérification : hors mois de raccord entre expériences de production ERA5
(``MOIS_TRANSITION_ERA5``), la moyenne des jours du mois redonne le mensuel 0036
à 0,0036 mm/jour près (57 226 mois) ; sommer 00 h → 23 h donnerait jusqu'à
0,48 mm/jour d'écart.

Valeur servie en mètres d'eau par heure ; somme des 24 heures (``math.fsum``,
indépendante de l'ordre) puis × 1000 → mm/jour, arrondi à 4 décimales à
l'écriture du CSV. Aucune interpolation, aucune valeur bouchée.

Même extraction que le mensuel 0036 : valeur au **point de grille 0,25° le plus
proche** de chaque localité (``meteo_era5_civ.maille_era5``), sans
interpolation ; les 142 localités (``points_nationaux``) tombent dans 110
mailles. Période **1991-2025**, source ``ecmwf_era5`` (id 2), méthode
``reanalyse``, confiance B. La borne de sanité est celle de la pluie journalière
NASA POWER (1000 mm/jour), borne basse 0 : un garde-fou, pas une valeur
attendue.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from kuma_data_core.db.seeds.meteo_civ import BORNE_PRECIPITATION_JOURNALIERE
from kuma_data_core.db.seeds.meteo_era5_civ import (
    ANNEE_DEBUT_ERA5,
    ANNEE_FIN_ERA5,
    LOT_METEO_ERA5,
)
from kuma_data_core.db.seeds.series_csv import ContratSerie

LOT_PLUIE_ERA5_JOURNALIERE: str = LOT_METEO_ERA5
"""Suffixe du CSV : les 142 localités en un seul fichier (``civ142``)."""

JEU_CDS: str = "reanalysis-era5-single-levels-timeseries"
"""Séries horaires ponctuelles ERA5 (mêmes valeurs que ``reanalysis-era5-single-levels``)."""
VARIABLE_CDS: str = "total_precipitation"
NOM_NETCDF: str = "tp"
UNITE_SOURCE: str = "m"
"""Unité servie : mètres d'eau cumulés sur l'heure qui finit à l'instant daté."""
UNITE_REFERENTIEL: str = "mm_par_jour"
FACTEUR_MM: float = 1000.0
"""m/jour → mm/jour."""
HEURES_PAR_JOUR: int = 24
DECALAGE_HEURES: int = 1
"""Le jour J somme les cumuls datés de J 01 h à J + 1 00 h : décalage d'une heure."""

MOIS_TRANSITION_ERA5: frozenset[tuple[int, int]] = frozenset(
    {
        (1993, 8),
        (1995, 9),
        (2000, 1),
        (2000, 10),
        (2001, 10),
        (2002, 10),
        (2003, 10),
        (2004, 10),
        (2005, 10),
        (2006, 10),
        (2008, 1),
        (2010, 1),
        (2015, 1),
        (2019, 3),
        (2021, 9),
        (2022, 1),
        (2022, 10),
    }
)
"""Mois où commence une expérience de production ERA5 (HRES), 1991-2025.

D'après la documentation ECMWF (« ERA5: data documentation », « Production
experiments ») : l'ERA5 historique a été produit par expériences parallèles
raboutées, avec des discontinuités possibles aux raccords. C'est dans certains
de ces mois, et seulement là, que la moyenne mensuelle du CDS (0036) s'écarte
nettement de la somme des cumuls horaires.
"""

CONTRAT_PLUIE_ERA5_JOURNALIERE: ContratSerie = ContratSerie(
    source_code="ecmwf_era5",
    source_id=2,
    source_libelle="ERA5 (CDS)",
    prefixe_code="ecmwf_era5_precipitation_journalier",
    grandeur_code="precipitation",
    methode_collecte="reanalyse",
    annee_debut=ANNEE_DEBUT_ERA5,
    annee_fin=ANNEE_FIN_ERA5,
    borne_max=BORNE_PRECIPITATION_JOURNALIERE,
    granularite="journalier",
    libelle_grandeur="Précipitations",
)


def cumul_journalier_mm(cumuls_horaires_m: Sequence[float]) -> float:
    """Cumul du jour en mm/jour depuis ses 24 cumuls horaires (m), datés 01 h → 00 h (J + 1)."""
    if len(cumuls_horaires_m) != HEURES_PAR_JOUR:
        raise ValueError(f"{len(cumuls_horaires_m)} cumuls horaires, {HEURES_PAR_JOUR} attendus.")
    return math.fsum(cumuls_horaires_m) * FACTEUR_MM
