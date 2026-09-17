"""Calcul à la volée des degrés-jours de climatisation (grandeur F2).

Indicateur climatique mensuel quantifiant les besoins de refroidissement
d'un bâtiment selon une base de référence T_b en °C définie par
l'appelant. Représente l'intégrale au-dessus de la base sur la période
considérée.

Modèle retenu v1 :

- **Méthode de la moyenne journalière** [1, 2] (Erbs et al. 1983,
  Schoenau & Kehrig 1990) :

    DJC_mois = somme sur les jours du mois de max(0, T_moy_jour - T_b)

  Avec T_moy_jour = température moyenne quotidienne (T2M NASA POWER
  agrégé jour, déjà journalier dans ``mesures_ressource``).

Agrégation : la grandeur produit un résultat **mensuel** par sommation
des écarts journaliers positifs. La réponse expose donc des
:class:`ResultatMensuel` au format ``instant="YYYY-MM"`` même si la
source est journalière.

Limitations documentées :

- la moyenne journalière sous-estime le DJC en climat à fort cycle
  diurne (-5 à -15% en tropical humide). Mitigation via intégration
  horaire.
- pas de norme de base T_b consolidée pour la Guinée. Les valeurs
  typiques (18.3 °C ASHRAE, 24-26 °C CEDEAO, 24 °C RTAA DOM) sont des
  références régionales partiellement transposables.
- T_amb = T2M MERRA-2 : sous-estimation altitude pour Labé / Mamou
  (Fouta-Djalon).
- Balanced Point Method (ASHRAE) hors périmètre F2.

Niveau de confiance dérivé uniforme ``'B'``.

Pattern fonction publique pure ``calculer_degre_jour_climatisation`` +
fonctions privées. Aucune dépendance SQL, testable unitairement.

Références bibliographiques :

[1] Erbs D.G., Klein S.A., Beckman W.A. 1983. "Estimation of degree-days
    and ambient temperature bin data from monthly-average temperatures."
    ASHRAE Journal 25(6), 60-65.

[2] Schoenau G.J., Kehrig R.A. 1990. "Method for calculating degree-days
    to any base temperature." Energy and Buildings 14(4), 299-302.
    DOI : 10.1016/0378-7788(90)90092-W.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Literal, TypedDict

from kuma_data_core.api.v1.schemas.grandeurs import (
    ParametresDegreJourClimatisation,
    ResultatMensuel,
)

# === Constantes module ====================================================

UNITE_DJC: str = "°C·j"
"""Unité de sortie : degrés-jours cumulés sur le mois."""

HEURES_PAR_JOUR: float = 24.0
"""Diviseur de l'intégration horaire : convertit la somme d'écarts horaires
(°C) en degrés-jours (°C·j). Méthode Erbs 1983."""

NIVEAU_CONFIANCE_DERIVE_F2_V1: Literal["B"] = "B"
"""Niveau de confiance uniforme v1."""


# === TypedDict d'entree ===================================================


class MesureJourTemperature(TypedDict):
    """Mesure journalière de température moyenne consommée par le calcul DJC."""

    instant_mesure: date
    t_moy_degc: float


class MesureHeureTemperature(TypedDict):
    """Mesure horaire de température consommée par l'intégration horaire."""

    instant_mesure: datetime
    t_degc: float


# === Fonctions privees pures ==============================================


def _ecart_jour(t_moy_degc: float, base_temperature_degc: float) -> float:
    """Calcule l'écart positif à la base pour un jour.

    ecart_jour = max(0, T_moy_jour - T_b)

    Le DJC ne comptabilise que les jours où la température moyenne
    dépasse la base (besoin de refroidissement). Les jours froids
    (T_moy_jour < T_b) contribuent 0.
    """
    return max(0.0, t_moy_degc - base_temperature_degc)


def _cle_mois(jour: date) -> str:
    """Formate un mois calendaire au format ``YYYY-MM`` (ResultatMensuel)."""
    return f"{jour.year:04d}-{jour.month:02d}"


def _agreger_djc_par_mois(
    mesures: Sequence[MesureJourTemperature],
    base_temperature_degc: float,
) -> dict[str, float]:
    """Agrège les écarts journaliers par mois calendaire.

    Renvoie un dict ``{"YYYY-MM": DJC_cumule}`` ordonné implicitement
    par insertion (Python 3.7+) - cohérent avec l'ordre chronologique
    si les mesures sont elles-mêmes ordonnées.
    """
    djc_par_mois: dict[str, float] = {}
    for mesure in mesures:
        ecart = _ecart_jour(
            t_moy_degc=mesure["t_moy_degc"],
            base_temperature_degc=base_temperature_degc,
        )
        cle = _cle_mois(mesure["instant_mesure"])
        djc_par_mois[cle] = djc_par_mois.get(cle, 0.0) + ecart
    return djc_par_mois


# === Fonction publique ====================================================


def calculer_degre_jour_climatisation(
    mesures: Sequence[MesureJourTemperature],
    parametres: ParametresDegreJourClimatisation,
) -> list[ResultatMensuel]:
    """Calcule les degrés-jours de climatisation mensuels (méthode moyenne journalière).

    Itère sur les mesures journalières T2M, calcule l'écart positif à la
    base T_b par jour, et agrège par mois calendaire. Retourne une liste
    ordonnée de :class:`ResultatMensuel` (format ``YYYY-MM``, unité
    ``°C·j``). Niveau de confiance dérivé uniforme ``'B'``.
    """
    djc_par_mois = _agreger_djc_par_mois(
        mesures=mesures,
        base_temperature_degc=parametres.base_temperature_degc,
    )
    return [
        ResultatMensuel(
            instant=cle_mois,
            valeur=djc_cumule,
            unite=UNITE_DJC,
            niveau_confiance=NIVEAU_CONFIANCE_DERIVE_F2_V1,
        )
        for cle_mois, djc_cumule in djc_par_mois.items()
    ]


def _agreger_djc_horaire_par_mois(
    mesures: Sequence[MesureHeureTemperature],
    base_temperature_degc: float,
) -> dict[str, float]:
    """Agrège les écarts horaires positifs par mois (intégration horaire).

    DJC_mois = somme sur les heures du mois de max(0, T_heure - T_b) / 24.

    Chaque heure au-dessus de la base contribue ``(T_heure - T_b) / 24``
    degrés-jours. Contrairement à la moyenne journalière, une heure chaude
    compte même si la moyenne du jour reste sous T_b (cycle diurne), ce qui
    lève la sous-estimation de la méthode journalière.
    """
    djc_par_mois: dict[str, float] = {}
    for mesure in mesures:
        ecart = max(0.0, mesure["t_degc"] - base_temperature_degc)
        cle = _cle_mois(mesure["instant_mesure"])
        djc_par_mois[cle] = djc_par_mois.get(cle, 0.0) + ecart / HEURES_PAR_JOUR
    return djc_par_mois


def calculer_degre_jour_climatisation_horaire(
    mesures: Sequence[MesureHeureTemperature],
    parametres: ParametresDegreJourClimatisation,
) -> list[ResultatMensuel]:
    """Calcule les DJC mensuels par intégration horaire (Erbs 1983).

    Itère sur les mesures horaires T2M dans la fenêtre demandée, intègre
    les écarts horaires positifs à T_b (divisés par 24 pour des
    degrés-jours), et agrège par mois calendaire. Plus juste que la
    moyenne journalière en climat à fort cycle diurne (lève le biais
    -5 à -15 % documenté).

    Paramètres :
        mesures : séquence de mesures horaires T2M (filtrées en amont sur
            la fenêtre, ordonnées chronologiquement ; heures non validées
            exclues en amont).
        parametres : paramètres techniques (base T_b ; ``methode`` non lu
            ici, le branchement est fait par l'appelant).

    Renvoie :
        Liste de :class:`ResultatMensuel` (format ``YYYY-MM``, unité
        ``°C·j``). Liste vide si ``mesures`` est vide.

    Aucune dépendance SQL, idempotent, pur. Niveau de confiance dérivé
    uniformément ``'B'`` (qualité source, pas méthode).
    """
    djc_par_mois = _agreger_djc_horaire_par_mois(
        mesures=mesures,
        base_temperature_degc=parametres.base_temperature_degc,
    )
    return [
        ResultatMensuel(
            instant=cle_mois,
            valeur=djc_cumule,
            unite=UNITE_DJC,
            niveau_confiance=NIVEAU_CONFIANCE_DERIVE_F2_V1,
        )
        for cle_mois, djc_cumule in djc_par_mois.items()
    ]
