"""Calcul à la volée de la grandeur F1 ``ghi_exceedance``.

Exceedance inter-annuelle de l'irradiation annuelle, dérivée de la série
GHI mensuelle 1991-2020 NASA POWER (climatologie OMM, 6 villes pilotes).

Méthode :

1. **Totaux annuels** (orchestrateur amont) : pour chaque année y de la
   fenêtre 1991-2020, le total annuel est calculé par pondération
   journalière de la valeur mensuelle (unité source kWh/m²/jour) :

       total_annuel(y) = Σ_mois [GHI(y, m) x nb_jours(m, y)]

   ``nb_jours`` vient de ``calendar.monthrange(y, m)[1]`` (stdlib),
   années bissextiles incluses (1992, 1996, 2000, 2004, 2008, 2012,
   2016, 2020 = 8 sur 30).

2. **Percentiles** (fonction pure ci-dessous) : sur les 30 totaux annuels,
   extraction de deux percentiles via ``numpy.percentile`` (interpolation
   ``'linear'``, méthode par défaut) :

   - **P50** = percentile 50 = médiane (irradiation annuelle typique)
   - **P90** = percentile **10** = valeur dépassée 90 % des années
     (scénario conservateur, fréquemment utilisé en bancable)

**Piège documenté** : P90 = dépassement 90 % => 10ᵉ percentile (et non
90ᵉ). La fonction garantit ``P90 < P50`` par construction.

Niveau de confiance : ``'B'`` (modèle satellitaire NASA POWER, cohérent
avec les autres grandeurs F1/F2).

Pattern fonctions pures + orchestrateur I/O : la fonction
``calculer_ghi_exceedance`` est pure (``Sequence[float]`` en entrée,
``ResultatGhiExceedance`` en sortie), aucune dépendance SQL.
L'orchestrateur de lecture (helper local dans ``api/v1/grandeurs.py``)
charge la série mensuelle et calcule les totaux annuels avant l'appel.

Limites documentées (cf. champ ``limite`` de la réponse API) :

- exceedance **inter-annuelle uniquement** (variabilité année à année),
  ne propage pas l'incertitude de modèle satellitaire. Ce n'est pas un
  P90 bancable complet (qui nécessiterait un modèle d'erreur explicite,
  type PRUVE, et idéalement une calibration sol).
- Kindia et Mamou tombent dans le même pixel CERES SYN1deg NASA POWER
  (110 km à 10° N) ; leurs séries mensuelles 1991-2020 sont
  strictement identiques et leurs P50/P90 le sont donc aussi. Note
  ajoutée au champ ``limite`` pour ces deux villes.
- base 30 ans, **incertitude d'échantillonnage** sur P90 (10ᵉ
  percentile sur 30 valeurs = 3 valeurs en queue). Mention qualitative
  dans le champ ``limite``.

Référence bibliographique : exceedance probabiliste P50/P90, pratique
courante en évaluation de ressource solaire bancable (cf. IEA PVPS
Task 16 / "Best Practices for Solar Resource Assessment").
"""

from __future__ import annotations

import calendar
from collections.abc import Sequence
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

# === Constantes module ====================================================

UNITE_GHI_EXCEEDANCE: str = "kWh/m²/an"
"""Unité de sortie : irradiation annuelle (énergie cumulée sur l'année)."""

NIVEAU_CONFIANCE_DERIVE: Literal["B"] = "B"
"""Niveau de confiance uniforme : modèle satellitaire NASA POWER."""

PERCENTILE_P50: float = 50.0
"""Médiane : irradiation annuelle typique."""

PERCENTILE_P90: float = 10.0
"""P90 (exceedance) = 10ᵉ percentile : valeur dépassée 90 % des années."""

METHODE_PERCENTILE: Literal["linear"] = "linear"
"""Méthode d'interpolation numpy.percentile (défaut, IEEE).

Typée ``Literal["linear"]`` (et non ``str``) pour satisfaire les
overloads stricts de ``numpy.percentile`` côté mypy strict.
"""

ANNEE_DEBUT_CLIMATOLOGIE: int = 1991
ANNEE_FIN_CLIMATOLOGIE: int = 2020
"""Bornes de la fenêtre climatologique OMM 1991-2020."""

NOMBRE_ANNEES_BASE: int = ANNEE_FIN_CLIMATOLOGIE - ANNEE_DEBUT_CLIMATOLOGIE + 1
"""30 années : base d'échantillonnage des percentiles."""


# === Constantes co-localisation ===========================================

PAIRES_COLOCALISEES_D29: dict[str, str] = {
    "gin_kindia": "gin_mamou",
    "gin_mamou": "gin_kindia",
}
"""Paires de villes co-localisées dans le même pixel CERES SYN1deg NASA
POWER (110 km à 10° N). Pour ces villes, P50/P90 sont strictement
identiques à la ville jumelle. Mention au champ ``limite`` de la
réponse API."""


# === Modele de resultat ===================================================


class ResultatGhiExceedance(BaseModel):
    """Résultat structuré du calcul P50/P90 d'une ville."""

    p50: float = Field(
        ...,
        description="Mediane (percentile 50) de l'irradiation annuelle, kWh/m²/an.",
    )
    p90: float = Field(
        ...,
        description=(
            "Exceedance P90 = percentile 10 (valeur depassee 90 % des annees), "
            "kWh/m²/an. Toujours < P50 par construction."
        ),
    )


# === Fonction publique pure ===============================================


def calculer_ghi_exceedance(
    totaux_annuels: Sequence[float],
) -> ResultatGhiExceedance:
    """Calcule P50 et P90 (exceedance) sur une série de totaux annuels.

    Args:
        totaux_annuels : Séquence de totaux annuels en kWh/m²/an
            (typiquement 30 valeurs pour la climatologie OMM 1991-2020).
            Le caller (orchestrateur) calcule ces totaux par pondération
            journalière de la série mensuelle (kWh/m²/jour).

    Returns:
        ResultatGhiExceedance avec ``p50`` (médiane) et ``p90``
        (percentile 10 = dépassement 90 %).

    Raises:
        ValueError : si la séquence est vide ou contient moins de 2
            valeurs (percentile non défini).

    Note : P90 < P50 par construction (10ᵉ percentile < 50ᵉ percentile
    sur une distribution non dégénérée). Garantie testée unitairement.
    """
    if len(totaux_annuels) < 2:
        raise ValueError(
            f"calculer_ghi_exceedance requiert au moins 2 totaux annuels, "
            f"recu : {len(totaux_annuels)}."
        )
    valeurs = np.asarray(totaux_annuels, dtype=float)
    p50 = float(np.percentile(valeurs, PERCENTILE_P50, method=METHODE_PERCENTILE))
    p90 = float(np.percentile(valeurs, PERCENTILE_P90, method=METHODE_PERCENTILE))
    return ResultatGhiExceedance(p50=p50, p90=p90)


# === Utilitaires de l'orchestrateur (pures, sans I/O) =====================


def calculer_totaux_annuels(
    mesures_mensuelles: Sequence[tuple[int, int, float]],
) -> dict[int, float]:
    """Reconstruit les totaux annuels à partir des mesures mensuelles.

    Pondère chaque valeur mensuelle (kWh/m²/jour) par le nombre réel de
    jours du mois (``calendar.monthrange(annee, mois)[1]``, stdlib) ;
    années bissextiles correctement traitées (février = 29 jours en
    1992, 1996, 2000, 2004, 2008, 2012, 2016, 2020).

    Args:
        mesures_mensuelles : Séquence de tuples ``(annee, mois, valeur)``
            avec ``valeur`` en kWh/m²/jour. Typiquement 360 lignes
            pour la climatologie 1991-2020.

    Returns:
        Dict ``{annee: total_annuel_kwh_par_m2}``. Une année est présente
        dans le résultat dès qu'elle a au moins une mesure mensuelle ;
        c'est au caller de filtrer les années incomplètes si requis.
    """
    totaux: dict[int, float] = {}
    for annee, mois, valeur in mesures_mensuelles:
        nb_jours = calendar.monthrange(annee, mois)[1]
        totaux[annee] = totaux.get(annee, 0.0) + valeur * nb_jours
    return totaux
