"""Calcul à la volée du productible avec PR fourni (grandeur F2).

Productible PV calculé en appliquant un Performance Ratio (PR) fourni
par l'appelant à la production théorique "plaque" du système. Le PR
quantifie l'ensemble des pertes par rapport au cas idéal STC.

Modèles retenus v1 :

- **PR brut** [1] (Marion et al. 2005, NREL/CP-520-37358) : ratio
  E_AC / (P_STC * H_POA / 1000). Aucune correction.
- **PR_T temperature-corrected** [2] (Dierauf et al. 2013,
  NREL/TP-5200-57991) : intercale un facteur de correction thermique
  (modèle NOCT simple Ross 1980, cf. ``productible_correction_thermique``)
  entre le PR fourni et la production calculée.

Les variantes **PR_W (weather-corrected)** et **PR_C
(climate-corrected)** documentées par Dierauf et al. 2013 ne sont pas
exposées en v1 (différées, TMY Guinée non disponible publiquement).

Endpoint paramétré par ``correction = 'aucune' | 'temperature'`` :

- ``correction='aucune'`` :
    E_AC = P_STC * G / G_STC * PR_fourni
- ``correction='temperature'`` :
    T_cell = T_amb + (NOCT - 20) * G / 800
    ratio_T = 1 + gamma_Pmax / 100 * (T_cell - 25)
    E_AC = P_STC * G / G_STC * PR_fourni * ratio_T

Niveau de confiance dérivé uniforme ``'B'``.

Pattern fonction publique pure ``calculer_productible_pr_fourni`` +
fonctions privées. Aucune dépendance SQL, testable unitairement.

Références bibliographiques :

[1] Marion B., Adelstein J., Boyle K., Hayden H., Hammond B.,
    Fletcher T., Canada B., Narang D., Shugar D., Wenger H., Kimber A.,
    Mitchell L., Rich G., Townsend T. 2005. "Performance parameters for
    grid-connected PV systems." NREL Conference Paper NREL/CP-520-37358,
    31st IEEE PVSC. Open NREL : docs.nrel.gov/docs/fy05osti/37358.pdf.

[2] Dierauf T., Growitz A., Kurtz S., Cruz J.L.B., Riley E., Hansen C.
    2013. "Weather-Corrected Performance Ratio." NREL Technical Report
    NREL/TP-5200-57991. DOI : 10.2172/1078057. Open NREL.

[3] Ross R.G. Jr. 1980. "Flat-plate photovoltaic array design
    optimization." 14th IEEE PVSC, p. 1126-1132. JPL/NASA open access.
    (Modèle NOCT pour T_cell, réutilisé depuis
    ``productible_correction_thermique``.)
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Literal, TypedDict

from kuma_data_core.api.v1.schemas.grandeurs import (
    ParametresProductiblePRFourni,
    ResultatJournalier,
    ResultatMensuel,
)

# Import délibéré d'une fonction privée cross-module : la logique NOCT
# (``_temperature_cellule_noct``) est conceptuellement liée au modèle
# thermique Ross 1980, dont ``productible_correction_thermique`` est la
# source canonique. Le PR_T (Dierauf 2013) en dérive directement. Aucune
# duplication de formule. À reconsidérer si un 3e consommateur apparaît
# - candidat naturel : une implémentation Faiman ultérieure (modèle
# thermique alternatif partageant ``t_amb``).
from kuma_data_core.services.grandeurs.productible_correction_thermique import (
    _temperature_cellule_noct,
)

# === Constantes module ====================================================

UNITE_PRODUCTIBLE: str = "kWh"
"""Unité de sortie : énergie cumulée journalière en kWh."""

NIVEAU_CONFIANCE_DERIVE_F2_V1: Literal["B"] = "B"
"""Niveau de confiance uniforme v1."""

TEMPERATURE_STC_DEGC: float = 25.0
"""Température STC de référence (°C)."""


# === TypedDict d'entree ===================================================


class MesureJourPRFourni(TypedDict):
    """Mesure journalière consommée par le calcul productible PR fourni.

    ``t_amb_degc`` est obligatoire uniquement si ``correction='temperature'``.
    Sinon, il est ignoré par le calcul. Pour simplifier l'orchestration en
    amont (couche routeur), il est conservé dans le TypedDict comme
    ``float | None``.
    """

    instant_mesure: date
    irradiance_kwh_par_m2_jour: float
    t_amb_degc: float | None


class MesureMoisPRFourni(TypedDict):
    """Mesure mensuelle consommée par le calcul productible PR fourni
    sur série climato.

    ``irradiance_kwh_par_m2_jour`` est ici une **moyenne quotidienne**
    sur le mois (sémantique NASA POWER monthly + SARAH-3 ICDR + climato
    OMM). Aucun champ ``t_amb_degc`` : la branche mensuelle est limitée
    au mode ``correction='aucune'`` (le mode ``'temperature'`` est exclu,
    non-linéarité cubique du facteur thermique NOCT en G incompatible
    avec la moyenne climato).
    """

    annee: int
    mois: int
    irradiance_kwh_par_m2_jour: float


class MesureHeurePRFourni(TypedDict):
    """Mesure horaire consommée par le productible PR fourni en intégration horaire.

    ``irradiance_w_par_m2`` est l'irradiance horaire (GHI, W/m² ≈ Wh/m² par
    heure) ; ``t_amb_degc`` la température ambiante horaire, obligatoire
    uniquement si ``correction='temperature'`` (sinon ``None``, ignoré).
    """

    instant_mesure: datetime
    irradiance_w_par_m2: float
    t_amb_degc: float | None


# === Fonctions privees pures ==============================================


def _productible_brut_jour(
    irradiance_kwh_par_m2_jour: float,
    puissance_stc_wc: float,
    pr_fourni: float,
) -> float:
    """Productible journalier PR brut Marion 2005 (formule en tête de module)."""
    return puissance_stc_wc / 1000.0 * irradiance_kwh_par_m2_jour * pr_fourni


def _productible_pr_t_jour(
    mesure: MesureJourPRFourni,
    parametres: ParametresProductiblePRFourni,
) -> float:
    """Calcule le productible journalier PR_T temperature-corrected (Dierauf 2013).

    Combine le PR brut avec un facteur de correction thermique NOCT
    (Ross 1980). Nécessite ``noct_degc``, ``coeff_temp_pourcent_par_degc``
    et ``mesure['t_amb_degc']`` non-None (validation effectuée en amont
    par le schéma Pydantic ``model_validator``).
    """
    assert parametres.noct_degc is not None
    assert parametres.coeff_temp_pourcent_par_degc is not None
    assert mesure["t_amb_degc"] is not None

    # Conversion kWh/m²/jour -> W/m² moyen 24h (cohérent avec
    # productible_correction_thermique pour reproductibilité).
    irradiance_w_par_m2 = mesure["irradiance_kwh_par_m2_jour"] * 1000.0 / 24.0

    t_cell = _temperature_cellule_noct(
        t_amb_degc=mesure["t_amb_degc"],
        irradiance_w_par_m2=irradiance_w_par_m2,
        noct_degc=parametres.noct_degc,
    )

    ratio_temperature = 1.0 + parametres.coeff_temp_pourcent_par_degc / 100.0 * (
        t_cell - TEMPERATURE_STC_DEGC
    )

    productible_brut = _productible_brut_jour(
        irradiance_kwh_par_m2_jour=mesure["irradiance_kwh_par_m2_jour"],
        puissance_stc_wc=parametres.puissance_stc_wc,
        pr_fourni=parametres.pr_fourni,
    )

    return productible_brut * ratio_temperature


# === Fonction publique ====================================================


def calculer_productible_pr_fourni(
    mesures: Sequence[MesureJourPRFourni],
    parametres: ParametresProductiblePRFourni,
) -> list[ResultatJournalier]:
    """Calcule le productible PV avec PR fourni (brut ou temperature-corrected).

    Itère sur les mesures journalières et applique le calcul selon
    ``parametres.correction`` :

    - ``'aucune'`` : PR brut (Marion 2005).
    - ``'temperature'`` : PR_T temperature-corrected (Dierauf 2013).

    Renvoie une liste ordonnée de :class:`ResultatJournalier`. Liste vide
    si ``mesures`` est vide. Le niveau de confiance dérivé est
    uniformément ``'B'``.

    Aucune dépendance SQL, idempotent, pur.
    """
    resultats: list[ResultatJournalier] = []
    for mesure in mesures:
        if parametres.correction == "aucune":
            productible = _productible_brut_jour(
                irradiance_kwh_par_m2_jour=mesure["irradiance_kwh_par_m2_jour"],
                puissance_stc_wc=parametres.puissance_stc_wc,
                pr_fourni=parametres.pr_fourni,
            )
        else:
            productible = _productible_pr_t_jour(mesure=mesure, parametres=parametres)

        resultats.append(
            ResultatJournalier(
                instant=mesure["instant_mesure"],
                valeur=max(0.0, productible),
                unite=UNITE_PRODUCTIBLE,
                niveau_confiance=NIVEAU_CONFIANCE_DERIVE_F2_V1,
            )
        )
    return resultats


def calculer_productible_pr_fourni_mensuel(
    mesures: Sequence[MesureMoisPRFourni],
    parametres: ParametresProductiblePRFourni,
) -> list[ResultatMensuel]:
    """Calcule le productible PV avec PR fourni sur série mensuelle climato.

    Branche unique mode ``correction='aucune'``. L'entrée
    ``irradiance_kwh_par_m2_jour`` est une **moyenne quotidienne sur le
    mois** (sémantique climato NASA POWER monthly / SARAH-3 ICDR) : la
    sortie est donc un **productible quotidien moyen pour le mois**
    (option A actée, pas de multiplication par nb_jours).

    Unité runtime ``'kWh'`` identique à la branche journalière - même
    sémantique « kWh par jour pour un système de puissance ``P_STC`` »
    (la cohérence d'interface F2 est préservée entre journalier et
    mensuel).

    Renvoie une liste ordonnée de :class:`ResultatMensuel` au format
    ``instant='YYYY-MM'``. Liste vide si ``mesures`` est vide. Le niveau
    de confiance dérivé est uniformément ``'B'``.

    Aucune dépendance SQL, idempotent, pur.

    Raises:
        AssertionError : si ``parametres.correction != 'aucune'``. Le
            mode ``'temperature'`` est exclu de la branche mensuelle
            (non-linéarité cubique du facteur thermique NOCT en G,
            incompatible avec la moyenne climato). Le garde-fou côté
            orchestrateur (HTTP 400) intercepte en amont ; cette
            assertion est un garde-fou défensif de fonction pure.
    """
    assert parametres.correction == "aucune", (
        "calculer_productible_pr_fourni_mensuel : seul le mode "
        "correction='aucune' est supporte en lot 2 (mode 'temperature' "
        "non-lineaire incompatible avec moyenne climato mensuelle)."
    )
    resultats: list[ResultatMensuel] = []
    for mesure in mesures:
        productible = _productible_brut_jour(
            irradiance_kwh_par_m2_jour=mesure["irradiance_kwh_par_m2_jour"],
            puissance_stc_wc=parametres.puissance_stc_wc,
            pr_fourni=parametres.pr_fourni,
        )
        resultats.append(
            ResultatMensuel(
                instant=f"{mesure['annee']:04d}-{mesure['mois']:02d}",
                valeur=max(0.0, productible),
                unite=UNITE_PRODUCTIBLE,
                niveau_confiance=NIVEAU_CONFIANCE_DERIVE_F2_V1,
            )
        )
    return resultats


def calculer_productible_pr_fourni_horaire(
    mesures: Sequence[MesureHeurePRFourni],
    parametres: ParametresProductiblePRFourni,
) -> list[ResultatJournalier]:
    """Calcule le productible PR fourni par **intégration horaire**.

    Applique le calcul **heure par heure** (PR brut ou PR_T avec ``T_cell``
    calculé sur l'irradiance horaire réelle), puis somme l'énergie sur la
    journée calendaire (UTC).

    Honnêteté : pour ``correction='aucune'`` (PR brut), le calcul
    est **linéaire** en G - la somme horaire égale exactement le journalier
    (aucun biais de moyennage à lever ; mode exposé pour la seule cohérence
    d'interface). Le gain réel ne porte que sur ``correction='temperature'``
    (PR_T, ``T_cell`` non-linéaire, Dierauf 2013), où l'intégration horaire
    lève le biais de Jensen.

    Entrée : GHI horaire (+ T2M horaire si PR_T) alignés par l'appelant.
    Sortie : un :class:`ResultatJournalier` par jour (unité ``kWh``). Pure
    arithmétique (pas de géométrie solaire).
    """
    energie_par_jour: dict[date, float] = {}
    for mesure in mesures:
        irradiance_w = mesure["irradiance_w_par_m2"]
        # Énergie horaire brute (kWh) = P_STC (kWc) x (irradiance W/m² x 1 h /1000
        #                               -> kWh/m²) x PR.
        productible = (
            parametres.puissance_stc_wc / 1000.0 * (irradiance_w / 1000.0) * parametres.pr_fourni
        )
        if parametres.correction == "temperature":
            assert parametres.noct_degc is not None
            assert parametres.coeff_temp_pourcent_par_degc is not None
            assert mesure["t_amb_degc"] is not None
            t_cell = _temperature_cellule_noct(
                t_amb_degc=mesure["t_amb_degc"],
                irradiance_w_par_m2=irradiance_w,
                noct_degc=parametres.noct_degc,
            )
            ratio_temperature = 1.0 + parametres.coeff_temp_pourcent_par_degc / 100.0 * (
                t_cell - TEMPERATURE_STC_DEGC
            )
            productible *= ratio_temperature
        jour = mesure["instant_mesure"].date()
        energie_par_jour[jour] = energie_par_jour.get(jour, 0.0) + productible

    return [
        ResultatJournalier(
            instant=jour,
            valeur=max(0.0, energie),
            unite=UNITE_PRODUCTIBLE,
            niveau_confiance=NIVEAU_CONFIANCE_DERIVE_F2_V1,
        )
        for jour, energie in energie_par_jour.items()
    ]
