"""Contrats des séries de particules CAMS EAC4 (PM2.5, PM10) sur la Côte d'Ivoire.

Source ``cams_eac4`` (id 15) et grandeurs ``pm2_5`` / ``pm10`` (unité
``microgramme_par_metre_cube``) déjà présentes au référentiel (0002). Elles
alimentent le proxy de salissure (``taux_salissure_proxy``, modèle HSU) et le PR
réaliste de l'API, qui consomment des PM **journalières** ``cams_eac4``
(ADR-0022).

Origine (ADS Copernicus, sondage du 2026-10-15) : réanalyse de composition
atmosphérique **EAC4** (méthode ``reanalyse``), grille régulière **0,75°**,
servie de **2003 à 2025** (dernière année complète) :

- **mensuel** : ``cams-global-reanalysis-eac4-monthly`` (``monthly_mean``, moyenne
  des analyses du mois), aux **142 localités** (``points_nationaux``) ;
- **journalier** : ``cams-global-reanalysis-eac4`` (analyses 3-horaires
  00-21 UTC), moyenne des 8 analyses du jour civil UTC (la Côte d'Ivoire est en
  UTC+0), aux **34 localités** (``points_journalier`` : 3 pilotes + 31 régions),
  mêmes points que la pluie NASA journalière dont le HSU a besoin.

Valeurs extraites au **point de grille le plus proche**, converties de kg/m³ en
µg/m³ (× 1e9). Les bornes sont des garde-fous de sanité (rejet à la lecture du
CSV), pas des valeurs attendues : larges, car les épisodes de poussière
d'Harmattan peuvent porter les PM10 au-delà de 1000 µg/m³. Borne basse 0 :
l'EAC4 sert des analyses nulles, comprises telles quelles dans les moyennes.
"""

from __future__ import annotations

from kuma_data_core.db.seeds.series_csv import ContratSerie

SOURCE_CODE: str = "cams_eac4"
SOURCE_ID: int = 15
SOURCE_LIBELLE: str = "CAMS EAC4"
UNITE_CODE: str = "microgramme_par_metre_cube"

LOT_AEROSOLS_MENSUEL: str = "civ142"
"""Suffixe des CSV mensuels : les 142 localités en un seul fichier par grandeur."""

LOT_AEROSOLS_JOURNALIER: str = "pilotes_regions"
"""Suffixe des CSV journaliers : mêmes 34 localités que le rayonnement journalier."""

ANNEE_DEBUT_EAC4: int = 2003  # début de la réanalyse EAC4
ANNEE_FIN_EAC4: int = 2025  # dernière année complète servie (sondage du 2026-10-15)

# grandeur -> (variable ADS, nom netCDF, libellé, borne mensuelle, borne journalière),
# bornes en µg/m³.
PARAMETRES_EAC4: dict[str, tuple[str, str, str, float, float]] = {
    "pm2_5": ("particulate_matter_2.5um", "pm2p5", "PM2.5", 1000.0, 3000.0),
    "pm10": ("particulate_matter_10um", "pm10", "PM10", 2000.0, 6000.0),
}


def _contrat(grandeur: str, granularite: str) -> ContratSerie:
    _, _, libelle, borne_mois, borne_jour = PARAMETRES_EAC4[grandeur]
    return ContratSerie(
        source_code=SOURCE_CODE,
        source_id=SOURCE_ID,
        source_libelle=SOURCE_LIBELLE,
        prefixe_code=f"cams_eac4_{grandeur}_{granularite}",
        grandeur_code=grandeur,
        methode_collecte="reanalyse",
        annee_debut=ANNEE_DEBUT_EAC4,
        annee_fin=ANNEE_FIN_EAC4,
        borne_max=borne_mois if granularite == "mensuel" else borne_jour,
        granularite=granularite,
        libelle_grandeur=libelle,
    )


CONTRATS_EAC4_MENSUELS: dict[str, ContratSerie] = {
    g: _contrat(g, "mensuel") for g in PARAMETRES_EAC4
}
CONTRATS_EAC4_JOURNALIERS: dict[str, ContratSerie] = {
    g: _contrat(g, "journalier") for g in PARAMETRES_EAC4
}
