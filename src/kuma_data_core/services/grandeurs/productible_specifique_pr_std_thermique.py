"""Grandeur F2 dérivée : productible spécifique climatologique mensuel avec
PR standard hors thermique et correction thermique linéaire jour par jour.

Vocation
--------
Produire, pour une unité géographique, **12 valeurs mensuelles en kWh/kWc**
représentant la production PV-out attendue sur un mois moyen 1991-2020, en
appliquant :

- le **PR_STD scellé dans la méthode v1.1** (0.78975, formule
  ``rend_onduleur × rend_mppt × (1 − pertes_diverses_pct / 100)``),
- une **correction thermique Dierauf 2013** appliquée jour par jour (où
  elle est linéairement valide), puis agrégation mensuelle sur 30 ans.

Alimente la clé ``pspNormalesKwhParKwc[12]`` du pack v1.1 (WP8 lecture
climatique). Ne s'applique **pas** au dimensionnement crête (méthode §6
inchangée : la règle bancable reste calée sur le mois défavorable via
``ghiNormales``).

Pourquoi pas ``productible_pr_fourni_mensuel`` directement
---------------------------------------------------------
Le service mensuel de ``productible_pr_fourni`` interdit la correction
thermique par assertion, parce que le facteur NOCT dépend non-linéairement
de l'irradiance : appliquer la thermique à une moyenne mensuelle biaise
silencieusement. Cette grandeur contourne la restriction en faisant le
calcul thermique **jour par jour** (linéarité respectée à la journée), puis
en n'agrégeant qu'après.

Réutilise ``_temperature_cellule_noct`` (Ross 1980) : source canonique du
modèle thermique dans le KDC.

Références
----------
[1] Marion et al. 2005, NREL/CP-520-37358 (PR brut).
[2] Dierauf et al. 2013, NREL/TP-5200-57991 (PR_T temperature-corrected).
[3] Ross R.G. Jr. 1980. Flat-plate PV array design optimization
    (modèle NOCT, réutilisé depuis ``productible_correction_thermique``).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final, TypedDict

from kuma_data_core.services.grandeurs.productible_correction_thermique import (
    _temperature_cellule_noct,
)

# === Constantes module ====================================================

UNITE_SORTIE: Final[str] = "kWh/kWc"
"""Unité de sortie : énergie mensuelle par kWc de crête installée."""

TEMPERATURE_STC_DEGC: Final[float] = 25.0
"""Température STC de référence (°C), identique à ``productible_pr_fourni``."""

NB_MOIS: Final[int] = 12


# === TypedDict d'entrée ===================================================


class MesureJourGhiTamb(TypedDict):
    """Mesure journalière GHI + T_amb pour un point donné.

    ``ghi_kwh_par_m2_jour`` : irradiation globale horizontale intégrée sur la
    journée. ``t_amb_degc`` : température ambiante moyenne 24 h.
    """

    annee: int
    mois: int  # 1..12
    ghi_kwh_par_m2_jour: float
    t_amb_degc: float


# === Fonction publique pure ==============================================


def calculer_productible_specifique_pr_std_thermique_mensuel(
    mesures: Sequence[MesureJourGhiTamb],
    pr_std: float,
    noct_degc: float,
    coeff_temp_pct_par_degc: float,
) -> list[float]:
    """Retourne 12 valeurs mensuelles en kWh/kWc (janvier=index 0).

    Chaque valeur est la moyenne des sommes journalières du mois calendaire
    correspondant sur toutes les années présentes dans ``mesures``. Le PR_STD
    scellé et la correction thermique NOCT (Dierauf 2013) sont appliqués jour
    par jour avant agrégation.

    - ``pr_std`` : PR standard hors thermique (méthode v1.1, valeur scellée
      0.78975).
    - ``noct_degc`` : NOCT du module (méthode : 45.0).
    - ``coeff_temp_pct_par_degc`` : coefficient de température P_max
      (méthode : −0.4 % / °C).

    Retourne une liste de 12 float. Un mois sans mesure donne 0.0
    (l'appelant doit garantir la couverture complète 1991-2020 pour une
    grandeur climatologique digne de ce nom).

    Pure, aucune I/O.
    """
    # Somme journalière par (année, mois)
    sommes: dict[tuple[int, int], float] = {}
    compteurs: dict[int, set[int]] = {m: set() for m in range(1, NB_MOIS + 1)}

    for m in mesures:
        annee = m["annee"]
        mois = m["mois"]
        ghi = m["ghi_kwh_par_m2_jour"]
        t_amb = m["t_amb_degc"]

        # Correction thermique linéaire jour par jour (Dierauf 2013).
        # Conversion kWh/m²/jour -> W/m² moyen 24 h, cohérent avec
        # productible_pr_fourni._productible_pr_t_jour.
        irradiance_w_par_m2 = ghi * 1000.0 / 24.0
        t_cell = _temperature_cellule_noct(
            t_amb_degc=t_amb,
            irradiance_w_par_m2=irradiance_w_par_m2,
            noct_degc=noct_degc,
        )
        ratio_thermique = 1.0 + coeff_temp_pct_par_degc / 100.0 * (t_cell - TEMPERATURE_STC_DEGC)
        # Productible journalier pour 1 kWc, en kWh :
        #   P_STC (1 kWc) × GHI (kWh/m²/j) / G_STC (1 kW/m²) × PR × ratio
        productible_jour = ghi * pr_std * ratio_thermique
        productible_jour = max(0.0, productible_jour)

        cle = (annee, mois)
        sommes[cle] = sommes.get(cle, 0.0) + productible_jour
        compteurs[mois].add(annee)

    # Moyenne par mois calendaire sur les années couvertes.
    resultats: list[float] = [0.0] * NB_MOIS
    for mois in range(1, NB_MOIS + 1):
        annees = compteurs[mois]
        if not annees:
            resultats[mois - 1] = 0.0
            continue
        total = sum(sommes[(annee, mois)] for annee in annees)
        resultats[mois - 1] = total / len(annees)

    return resultats
