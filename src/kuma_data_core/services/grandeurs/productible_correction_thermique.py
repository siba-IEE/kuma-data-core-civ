"""Calcul à la volée du productible avec correction thermique (grandeur F2).

Productible PV ajusté en fonction de la température opérationnelle du
module, qui dégrade la puissance par rapport aux conditions STC
(1000 W/m², 25 °C, AM1.5).

Modèle retenu en API : **NOCT simple** (Ross 1980) [1]. Température
cellule estimée à partir d'une seule constante de fiche produit (NOCT,
Nominal Operating Cell Temperature) :

    T_cell = T_amb + (NOCT - 20) * G / 800

Production électrique corrigée :

    P_AC = P_STC * (G / 1000) * [1 + gamma_Pmax / 100 * (T_cell - 25)]

Avec G = irradiance reçue par le module (GHI ou POA),
T_amb = température ambiante (T2M NASA POWER),
gamma_Pmax = coefficient température (%/°C, fiche produit, valeur
négative typique -0.4 c-Si). L'irradiance instantanée utilisée pour
le calcul de T_cell est convertie depuis l'énergie journalière par
``G_24h = G_jour * 1000 / 24`` (W/m² moyen 24 h) - biais de moyennage
acté, sous-estimation midi par moyennage 24 h acceptée par
construction.

Limitations documentées :

- NOCT simple ne prend pas en compte le vent (WS2M). Le modèle Faiman
  2008 [2] avec coefficients U0 / U1 corrige cette limitation mais
  relève du **régime terrain** : ses coefficients par défaut sont
  calibrés en climat désertique et leur transposition au climat
  guinéen tropical sans calibration locale produirait une fausse
  confiance B. Code de calcul Faiman + tests archivés sur la branche
  ``wip/faiman-terrain`` et le tag ``faiman-terrain-reserve``.
- modèles Sandia SAPM (King et al. 2004 [3]) et PVsyst plus précis
  disponibles mais nécessitent plus de paramètres entrée ou
  calibrations site. Différés.
- T_amb = T2M MERRA-2 NASA POWER avec biais d'altitude documenté -
  sous-estimation possible Labé / Mamou.

Niveau de confiance dérivé uniforme ``'B'``.

Pattern fonction publique pure
``calculer_productible_correction_thermique`` + fonctions privées.
Aucune dépendance SQL, testable unitairement.

Références bibliographiques :

[1] Ross R.G. Jr. 1980. "Flat-plate photovoltaic array design
    optimization." Conference Record of the 14th IEEE Photovoltaic
    Specialists Conference, San Diego, CA, p. 1126-1132. JPL/NASA
    open access.

[2] Faiman D. 2008. "Assessing the outdoor operating temperature of
    photovoltaic modules." Progress in Photovoltaics 16(4), 307-315.
    DOI : 10.1002/pip.813. (Modèle archivé régime terrain.)

[3] King D.L., Boyson W.E., Kratochvil J.A. 2004. "Photovoltaic Array
    Performance Model." Sandia National Laboratories Report
    SAND2004-3535. Open OSTI (ID 919131). (Référence modèle SAPM non
    utilisé.)
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Literal, TypedDict

from kuma_data_core.api.v1.schemas.grandeurs import (
    ParametresProductibleCorrectionThermique,
    ResultatJournalier,
)

# === Constantes module ====================================================

UNITE_PRODUCTIBLE: str = "kWh"
"""Unité de sortie : énergie cumulée journalière en kWh."""

NIVEAU_CONFIANCE_DERIVE_F2_V1: Literal["B"] = "B"
"""Niveau de confiance uniforme v1."""

IRRADIANCE_STC_W_PAR_M2: float = 1000.0
"""Irradiance STC de référence (W/m²)."""

TEMPERATURE_STC_DEGC: float = 25.0
"""Température STC de référence (°C)."""

TEMPERATURE_NOCT_REFERENCE_DEGC: float = 20.0
"""Température ambiante de référence du test NOCT (°C, Ross 1980)."""

IRRADIANCE_NOCT_REFERENCE_W_PAR_M2: float = 800.0
"""Irradiance de référence du test NOCT (W/m², Ross 1980)."""


# === TypedDict d'entree ===================================================


class MesureJourThermique(TypedDict):
    """Mesure journalière consommée par le calcul productible thermique.

    Combine la température ambiante T2M (NASA POWER) et l'irradiance G
    (GHI ou POA pré-calculé). G est exprimée en kWh/m²/jour (granularité
    journalière NASA POWER) ou en W/m² selon le contexte d'usage.
    """

    instant_mesure: date
    t_amb_degc: float
    irradiance_kwh_par_m2_jour: float


class MesureHeureThermique(TypedDict):
    """Mesure horaire consommée par le productible thermique en intégration horaire.

    ``irradiance_w_par_m2`` est l'irradiance horaire (GHI, W/m² ≈ Wh/m² par
    heure) ; ``t_amb_degc`` la température ambiante horaire.
    """

    instant_mesure: datetime
    t_amb_degc: float
    irradiance_w_par_m2: float


# === Fonctions privees pures ==============================================


def _temperature_cellule_noct(
    t_amb_degc: float,
    irradiance_w_par_m2: float,
    noct_degc: float,
) -> float:
    """Température cellule par le modèle NOCT simple (formule en tête de module)."""
    return t_amb_degc + (noct_degc - TEMPERATURE_NOCT_REFERENCE_DEGC) * (
        irradiance_w_par_m2 / IRRADIANCE_NOCT_REFERENCE_W_PAR_M2
    )


def _productible_jour(
    mesure: MesureJourThermique,
    parametres: ParametresProductibleCorrectionThermique,
) -> float:
    """Calcule le productible journalier (kWh) avec correction thermique.

    Approximation v1 : utilise l'irradiance journalière comme G de
    référence pour le calcul de T_cell (approche midi solaire implicite
    via la moyenne journalière). Cohérent avec biais de moyennage acté.

    Étapes :
    1. Convertir l'irradiance kWh/m²/jour en W/m² instantané équivalent
       (en supposant 24 heures de jour moyen pour le calcul T_cell).
    2. Calculer T_cell par NOCT simple.
    3. Appliquer la correction thermique à la production STC.
    """
    # Conversion kWh/m²/jour -> W/m² moyen sur 24h (approximation pour T_cell).
    irradiance_w_par_m2 = mesure["irradiance_kwh_par_m2_jour"] * 1000.0 / 24.0

    t_cell = _temperature_cellule_noct(
        t_amb_degc=mesure["t_amb_degc"],
        irradiance_w_par_m2=irradiance_w_par_m2,
        noct_degc=parametres.noct_degc,
    )

    # Correction thermique : facteur multiplicatif sur la production STC.
    facteur_thermique = 1.0 + parametres.coeff_temp_pourcent_par_degc / 100.0 * (
        t_cell - TEMPERATURE_STC_DEGC
    )

    # Productible journalier (kWh) :
    # P_STC (Wc) x irradiance (kWh/m²/jour) / G_STC (1000 W/m²) x facteur_thermique
    # = P_STC (kWc) x irradiance (kWh/m²/jour) x facteur_thermique
    productible_kwh = (
        parametres.puissance_stc_wc
        / 1000.0
        * mesure["irradiance_kwh_par_m2_jour"]
        * facteur_thermique
    )

    return max(0.0, productible_kwh)


# === Fonction publique ====================================================


def calculer_productible_correction_thermique(
    mesures: Sequence[MesureJourThermique],
    parametres: ParametresProductibleCorrectionThermique,
) -> list[ResultatJournalier]:
    """Calcule le productible PV avec correction thermique NOCT simple (Ross 1980).

    Itère sur les mesures journalières (T2M + irradiance G, GHI ou POA
    selon le contexte) et renvoie une liste ordonnée de
    :class:`ResultatJournalier`. Niveau de confiance dérivé uniforme ``'B'``.
    """
    resultats: list[ResultatJournalier] = []
    for mesure in mesures:
        productible = _productible_jour(mesure=mesure, parametres=parametres)
        resultats.append(
            ResultatJournalier(
                instant=mesure["instant_mesure"],
                valeur=productible,
                unite=UNITE_PRODUCTIBLE,
                niveau_confiance=NIVEAU_CONFIANCE_DERIVE_F2_V1,
            )
        )
    return resultats


def calculer_productible_correction_thermique_horaire(
    mesures: Sequence[MesureHeureThermique],
    parametres: ParametresProductibleCorrectionThermique,
) -> list[ResultatJournalier]:
    """Calcule le productible thermique-corrigé par **intégration horaire**.

    Applique le modèle NOCT (Ross 1980) **heure par heure** : T_cell et
    facteur thermique calculés sur l'irradiance horaire réelle (et non sur
    la moyenne 24 h), puis l'énergie horaire est sommée sur la journée
    calendaire (UTC). Lève le biais de moyennage : la moyenne 24 h
    sous-estime le pic d'irradiance de midi, donc sous-estime T_cell et
    **surestime** le productible (la perte thermique de midi est lissée).

    Entrée : GHI + T2M horaires alignés (l'appelant n'aligne que les
    instants complets). Sortie : un :class:`ResultatJournalier` par jour
    (unité ``kWh``, identique à la méthode journalière). Pure arithmétique
    (pas de géométrie solaire).
    """
    energie_par_jour: dict[date, float] = {}
    for mesure in mesures:
        irradiance_w = mesure["irradiance_w_par_m2"]
        t_cell = _temperature_cellule_noct(
            t_amb_degc=mesure["t_amb_degc"],
            irradiance_w_par_m2=irradiance_w,
            noct_degc=parametres.noct_degc,
        )
        facteur_thermique = 1.0 + parametres.coeff_temp_pourcent_par_degc / 100.0 * (
            t_cell - TEMPERATURE_STC_DEGC
        )
        # Énergie horaire (kWh) = P_STC (kWc) x (irradiance W/m² x 1 h /1000 -> kWh/m²)
        #                         / G_STC (1 kW/m², implicite) x facteur_thermique.
        energie_heure_kwh = (
            parametres.puissance_stc_wc / 1000.0 * (irradiance_w / 1000.0) * facteur_thermique
        )
        jour = mesure["instant_mesure"].date()
        energie_par_jour[jour] = energie_par_jour.get(jour, 0.0) + energie_heure_kwh

    return [
        ResultatJournalier(
            instant=jour,
            valeur=max(0.0, energie),
            unite=UNITE_PRODUCTIBLE,
            niveau_confiance=NIVEAU_CONFIANCE_DERIVE_F2_V1,
        )
        for jour, energie in energie_par_jour.items()
    ]
