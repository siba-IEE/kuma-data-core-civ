"""Calcul à la volée du proxy de salissure (grandeur F1).

Expose la perte de transmission par salissure des modules PV, en **% de perte**
= ``(1 - ratio_hsu) x 100``, estimée par le modèle **HSU** (``pvlib.soiling.hsu``,
Coello & Boyle 2019) à partir des **PM2.5/PM10** (EAC4) et de la **pluie**
(NASA POWER). Grandeur F1 ``calculee_volee``, confiance dérivée ``'B'``.

Pattern fonction publique pure (``pvlib`` / ``pandas``, aucune dépendance
SQL). L'orchestration (résolution des séries PM2.5/PM10 + pluie, alignement) vit
dans l'endpoint.

**Unités (vérifiées contre la signature réelle pvlib 0.15.1, 2026-06-19)** :
``pvlib.soiling.hsu`` attend les PM en **g/m3** (docstring : ``[g/m^3]``), la pluie
en **mm**, le tilt en **degrés**, et renvoie un **ratio de salissure** (Series, 1 =
propre, ``1 - perte de transmission``). Notre donnée PM est en **µg/m³** : on
**convertit µg/m³ -> g/m³ (x 1e-6)** avant de la passer à hsu. Sans cette conversion,
la salissure serait 1e6x trop forte (vérifié empiriquement : 34 % de perte au lieu
de 2 %). C'est une divergence assumée entre la donnée Kuma (µg/m³, standard qualité
de l'air) et l'entrée attendue par pvlib (g/m³).

``rain_accum_period = 1 jour`` : la pluie est déjà cumulée à la journée ; un jour de
pluie au-delà du seuil ``cleaning_threshold`` nettoie le module ce jour-là.

Référence : Coello M. & Boyle L. 2019, "Simple Model For Predicting Time Series
Soiling of Photovoltaic Panels", IEEE Journal of Photovoltaics, DOI :
10.1109/JPHOTOV.2019.2919628.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Literal, TypedDict

import pandas as pd  # type: ignore[import-untyped]
from pvlib import soiling  # type: ignore[import-untyped]
from pydantic import BaseModel

from kuma_data_core.api.v1.schemas.grandeurs import MesureSoilingJour

# === Constantes (defauts F1 "soiling de site", documentes) =================

SURFACE_TILT_DEFAUT: float = 10.0
"""Inclinaison fixe par défaut (degrés) : tilt latitude représentatif Guinée
(9-10 deg N). F1 soiling de site ; un parc à tilt différent salit différemment.
Une version F2 paramétrable est une refonte ultérieure consciente."""

CLEANING_THRESHOLD_DEFAUT_MM: float = 1.0
"""Hauteur de pluie (mm) sur une période d'accumulation suffisante à nettoyer le
module (défaut HSU usuel)."""

NIVEAU_CONFIANCE: Literal["B"] = "B"
"""Niveau de confiance dérivé uniforme (proxy modèle satellitaire, pas mesure)."""

RAIN_ACCUM_PERIOD = pd.Timedelta("1D")
"""Période d'accumulation de la pluie (1 jour : pas journalier, pluie déjà cumulée
à la journée). Recommandé par pvlib entre 1 h et 24 h."""

GRAMMES_PAR_MICROGRAMME: float = 1e-6
"""Conversion µg/m³ (donnée Kuma) -> g/m³ (entrée attendue par pvlib.soiling.hsu)."""

CAVEAT_SPIN_UP: str = (
    "Modele HSU initialise propre (salissure nulle) : les premiers jours de la "
    "fenetre sous-estiment la salissure reelle (spin-up, L-SOIL-3). Proxy modele, "
    "pas une mesure de salissure (L-SOIL-1, terrain D-67) ; PM EAC4 grille grossiere "
    "0,75 deg (L-SOIL-4)."
)


# === Entree / sortie =======================================================


class MesureEntreeSoiling(TypedDict):
    """Mesure journalière alignée consommée par le proxy de salissure.

    ``pm2_5`` / ``pm10`` en **µg/m³** (donnée EAC4 Kuma), ``rainfall_mm`` en **mm**.
    """

    instant_mesure: date
    rainfall_mm: float
    pm2_5: float
    pm10: float


class ResultatSoiling(BaseModel):
    """Résultat du proxy de salissure : pertes journalières + caveat."""

    mesures: list[MesureSoilingJour]
    limite: str


# === Fonction publique pure (cœur HSU) =====================================


def calculer_taux_salissure_proxy(
    mesures: Sequence[MesureEntreeSoiling],
    surface_tilt_deg: float = SURFACE_TILT_DEFAUT,
    cleaning_threshold_mm: float = CLEANING_THRESHOLD_DEFAUT_MM,
) -> ResultatSoiling:
    """Perte de salissure journalière (% = (1 - ratio_hsu) x 100, bornée [0, 100]).

    Applique ``pvlib.soiling.hsu`` sur la fenêtre journalière alignée. Convertit les
    PM µg/m³ -> g/m³ (entrée attendue par pvlib). Pure, idempotente.
    """
    if not mesures:
        return ResultatSoiling(mesures=[], limite=CAVEAT_SPIN_UP)

    mesures_tri = sorted(mesures, key=lambda m: m["instant_mesure"])
    index = pd.DatetimeIndex([m["instant_mesure"] for m in mesures_tri])
    rainfall = pd.Series([m["rainfall_mm"] for m in mesures_tri], index=index, dtype=float)
    # Conversion µg/m³ -> g/m³ (cf. docstring module : pvlib attend des g/m³).
    pm2_5_g = (
        pd.Series([m["pm2_5"] for m in mesures_tri], index=index, dtype=float)
        * GRAMMES_PAR_MICROGRAMME
    )
    pm10_g = (
        pd.Series([m["pm10"] for m in mesures_tri], index=index, dtype=float)
        * GRAMMES_PAR_MICROGRAMME
    )

    ratio = soiling.hsu(
        rainfall=rainfall,
        cleaning_threshold=cleaning_threshold_mm,
        surface_tilt=surface_tilt_deg,
        pm2_5=pm2_5_g,
        pm10=pm10_g,
        rain_accum_period=RAIN_ACCUM_PERIOD,
    )
    perte = ((1.0 - ratio) * 100.0).clip(lower=0.0, upper=100.0)

    mesures_out = [
        MesureSoilingJour(
            instant=pd.Timestamp(instant).date(),
            perte_pct=float(valeur),
            niveau_confiance=NIVEAU_CONFIANCE,
        )
        for instant, valeur in perte.items()
    ]
    return ResultatSoiling(mesures=mesures_out, limite=CAVEAT_SPIN_UP)
