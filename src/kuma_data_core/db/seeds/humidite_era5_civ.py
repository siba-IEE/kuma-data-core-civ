"""Contrats de l'humidité relative ERA5 (CDS Copernicus) aux 142 localités.

Deuxième source de l'humidité relative à 2 m, à côté de NASA POWER (``RH2M`` :
réanalyse MERRA-2, gravée en 0034, 0035 et 0047). ERA5 ne sert pas d'humidité
relative au sol : elle se calcule depuis la température ``2m_temperature``
(``t2m``) et le point de rosée ``2m_dewpoint_temperature`` (``d2m``), en
kelvins. La recalculer depuis des moyennes de T et de Td est biaisée, car la
formule n'est pas linéaire (−1,77 point en moyenne aux pilotes, ADR-0021) :
l'humidité est donc calculée **heure par heure**, puis moyennée.

**Produit** : valeurs **horaires instantanées** ERA5 lues point par point dans le
jeu ``reanalysis-era5-single-levels-timeseries`` du CDS, au nœud 0,25° le plus
proche de chaque localité (``meteo_era5_civ.maille_era5``, mêmes 110 mailles
que la température et le vent journaliers 0053, ADR-0034).

**Humidité horaire** (formule d'ECMWF, fonctions Metview
``relative_humidity_from_dewpoint`` et ``saturation_vapour_pressure``, phase
eau) : ``HR = 100 · e_sat(Td) / e_sat(T)``, avec la formule de Tetens sur l'eau
``e_sat(T) = a1 · exp(a3 · (T − T0) / (T − a4))``, a1 = 611,21 Pa, a3 = 17,502,
a4 = 32,19 K, T0 = 273,16 K. La Côte d'Ivoire ne gèle pas : la phase eau suffit.
Aucune valeur n'est écrêtée à 100 %.

**Jour J** (jour civil UTC, local en Côte d'Ivoire) : moyenne des 24 humidités
horaires datées de 00 h à 23 h de J, comme la température 0053. **Mois** :
moyenne de toutes les humidités horaires du mois, égale à la moyenne de ses
jours. Sommes exactes (``math.fsum``), arrondi à 4 décimales à l'écriture du CSV.

Période **1991-2025**, source ``ecmwf_era5`` (id 2), méthode ``reanalyse``,
confiance B, unité ``pourcent``. Bornes de sanité : celles de NASA POWER
(``meteo_civ``, 100 %), borne basse 0.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from kuma_data_core.db.seeds.meteo_civ import PARAMETRES_METEO_NASA
from kuma_data_core.db.seeds.meteo_era5_civ import ANNEE_DEBUT_ERA5, ANNEE_FIN_ERA5, LOT_METEO_ERA5
from kuma_data_core.db.seeds.meteo_era5_journaliere_civ import HEURES_PAR_JOUR
from kuma_data_core.db.seeds.series_csv import ContratSerie

LOT_HUMIDITE_ERA5: str = LOT_METEO_ERA5
"""Suffixe des CSV : les 142 localités en un seul fichier par granularité (``civ142``)."""

GRANDEUR: str = "rh2m"
VARIABLES_CDS_HUMIDITE: tuple[str, ...] = ("2m_temperature", "2m_dewpoint_temperature")
UNITES_SOURCE_HUMIDITE: dict[str, str] = {"t2m": "K", "d2m": "K"}
"""Nom de chaque variable dans le netCDF servi → unité servie."""

# Formule de Tetens sur l'eau, constantes d'ECMWF (Metview, ``saturation_vapour_pressure``).
A1_PA: float = 611.21
A3: float = 17.502
A4_K: float = 32.19
T0_K: float = 273.16


def _contrat(granularite: str) -> ContratSerie:
    _, _, _, libelle, borne_mois, borne_jour = PARAMETRES_METEO_NASA[GRANDEUR]
    return ContratSerie(
        source_code="ecmwf_era5",
        source_id=2,
        source_libelle="ERA5 (CDS)",
        prefixe_code=f"ecmwf_era5_{GRANDEUR}_{granularite}",
        grandeur_code=GRANDEUR,
        methode_collecte="reanalyse",
        annee_debut=ANNEE_DEBUT_ERA5,
        annee_fin=ANNEE_FIN_ERA5,
        borne_max=borne_mois if granularite == "mensuel" else borne_jour,
        granularite=granularite,
        libelle_grandeur=libelle,
    )


CONTRAT_HUMIDITE_ERA5_JOURNALIER: ContratSerie = _contrat("journalier")
CONTRAT_HUMIDITE_ERA5_MENSUEL: ContratSerie = _contrat("mensuel")


def pression_vapeur_saturante_eau(t_k: float) -> float:
    """Pression de vapeur saturante sur l'eau (Pa) à la température ``t_k`` (K), Tetens."""
    return A1_PA * math.exp(A3 * (t_k - T0_K) / (t_k - A4_K))


def humidite_relative(t_k: float, td_k: float) -> float:
    """Humidité relative (%) depuis la température et le point de rosée (K), sans écrêtage."""
    return 100.0 * pression_vapeur_saturante_eau(td_k) / pression_vapeur_saturante_eau(t_k)


def humidites_horaires(t_k: Sequence[float], td_k: Sequence[float]) -> list[float]:
    """Humidité relative (%) de chaque heure, depuis les séries horaires de T et Td (K)."""
    return [humidite_relative(t, td) for t, td in zip(t_k, td_k, strict=True)]


def humidite_journaliere(heures: Sequence[float]) -> float:
    """Moyenne des 24 humidités horaires (%) du jour."""
    if len(heures) != HEURES_PAR_JOUR:
        raise ValueError(f"{len(heures)} valeurs horaires, {HEURES_PAR_JOUR} attendues.")
    return math.fsum(heures) / HEURES_PAR_JOUR


def humidite_mensuelle(heures: Sequence[float], nb_jours_mois: int) -> float:
    """Moyenne des humidités horaires (%) d'un mois complet de ``nb_jours_mois`` jours."""
    if len(heures) != HEURES_PAR_JOUR * nb_jours_mois:
        raise ValueError(
            f"{len(heures)} valeurs horaires, {HEURES_PAR_JOUR * nb_jours_mois} attendues."
        )
    return math.fsum(heures) / len(heures)
