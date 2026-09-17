"""Calcul à la volée du PR réaliste saisonnier (grandeur F1).

PR effectif site-spécifique ``pr_realiste`` = ``PR_fourni x ratio_T x
(1 - perte_soiling/100)`` (ratio sans dimension). Sa **courbe mensuelle est la
"PR saisonnière"** : le creux Harmattan (PM élevées Dec-Fev) y apparaît, la remontée
mousson (lessivage) aussi.

**Composition, pas de réimplémentation** :

- facteur thermique ``ratio_T`` : réutilise la logique NOCT canonique
  (``_temperature_cellule_noct``, Ross 1980, ``productible_correction_thermique`` ;
  même facteur que le PR_T de ``productible_pr_fourni``) ;
- facteur salissure : réutilise la fonction pure ``calculer_taux_salissure_proxy``
  (modèle HSU) ; un seul appel, perte % -> ``(1 - perte/100)``.

**Doctrine PR-référence (anti double-comptage)** : le ``PR_fourni`` est supposé
**hors salissure ET hors température**. Les deux corrections se superposent en
facteurs multiplicatifs **séparables** sur cette référence. Un PR plaque tout-compris
(qui embarque déjà une allocation salissure/température) double-compterait : l'appelant
qui en dispose ne doit pas activer les corrections.

Modes (``correction``) :

- ``aucune`` : ``pr_realiste = PR_fourni`` (écho, baseline) ;
- ``temperature`` : ``x ratio_T`` (compagne T2M) ;
- ``salissure`` : ``x (1 - perte/100)`` (compagnes PM2.5/PM10/pluie) ;
- ``temperature_salissure`` : les deux (défaut).

Pattern fonction publique pure (aucune dépendance SQL). v1 : facteurs
**indépendants** (couplage 2e ordre G -> T_cell -> rendement ignoré).

Référence : Dierauf et al. 2013 (PR temperature-corrected, NREL/TP-5200-57991) +
Ross 1980 (NOCT) + Coello & Boyle 2019 (HSU).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from typing import Literal, TypedDict

from pydantic import BaseModel

from kuma_data_core.api.v1.schemas.grandeurs import (
    MesureJourPR,
    MesureMoisPR,
    ModeCorrectionPR,
)
from kuma_data_core.services.grandeurs.productible_correction_thermique import (
    TEMPERATURE_STC_DEGC,
    _temperature_cellule_noct,
)
from kuma_data_core.services.grandeurs.soiling_hsu import (
    MesureEntreeSoiling,
    calculer_taux_salissure_proxy,
)

# === Types / constantes ====================================================

_BESOIN_THERMIQUE: frozenset[str] = frozenset({"temperature", "temperature_salissure"})
_BESOIN_SALISSURE: frozenset[str] = frozenset({"salissure", "temperature_salissure"})

NIVEAU_CONFIANCE: Literal["B"] = "B"
"""Niveau de confiance dérivé uniforme (proxy modèle satellitaire)."""

_HEURES_PAR_JOUR: float = 24.0
_WATT_PAR_KILOWATT: float = 1000.0

_CAVEAT_PR_REFERENCE: str = (
    "PR_fourni suppose hors salissure ET hors temperature (corrections "
    "multiplicatives separables ; un PR plaque tout-compris double-compterait, "
    "doctrine PR-reference L-PR-2). Proxy API confiance B, pas un PR mesure sol "
    "(D-67, L-PR-1). v1 : facteurs thermique et salissure independants (L-PR-3)."
)
_CAVEAT_SPIN_UP: str = (
    " Salissure : modele HSU initialise propre, premiers jours de la fenetre "
    "sous-estimes (spin-up, L-SOIL-3) ; fenetre bornee a l'overlap PM EAC4 (L-PR-4)."
)
_CAVEAT_L_TR_6: str = (
    " Thermique : le facteur ratio_T herite du biais L-TR-6 (la moyenne 24 h "
    "sous-estime le pic d'irradiance de midi, donc T_cell, donc surestime legerement "
    "le PR : 'realiste' un poil optimiste cote chaleur)."
)


# === Entree / sortie =======================================================


class MesureJourPRRealiste(TypedDict):
    """Mesure journalière alignée consommée par le PR réaliste.

    Champs requis **selon le mode** (None sinon) : ``ghi_kwh_par_m2_jour`` + ``t_amb_degc``
    pour la température ; ``rainfall_mm`` + ``pm2_5`` + ``pm10`` (µg/m³) pour la
    salissure.
    """

    instant_mesure: date
    ghi_kwh_par_m2_jour: float | None
    t_amb_degc: float | None
    rainfall_mm: float | None
    pm2_5: float | None
    pm10: float | None


class ResultatPRRealiste(BaseModel):
    """Résultat du PR réaliste : PR effectif journalier + caveat."""

    mesures: list[MesureJourPR]
    limite: str


# === Helpers purs ==========================================================


def _exiger_present(valeur: float | None, nom: str, mode: str) -> float:
    if valeur is None:
        raise ValueError(f"Champ {nom!r} requis pour la correction {mode!r}, recu None.")
    return valeur


def _ratio_thermique_jour(
    ghi_kwh_par_m2_jour: float, t_amb_degc: float, noct_degc: float, gamma_pmax_pct: float
) -> float:
    """Facteur de correction thermique ``ratio_T`` (NOCT Ross 1980, cf. tête de module)."""
    irradiance_w_par_m2 = ghi_kwh_par_m2_jour * _WATT_PAR_KILOWATT / _HEURES_PAR_JOUR
    t_cell = _temperature_cellule_noct(
        t_amb_degc=t_amb_degc, irradiance_w_par_m2=irradiance_w_par_m2, noct_degc=noct_degc
    )
    return 1.0 + gamma_pmax_pct / 100.0 * (t_cell - TEMPERATURE_STC_DEGC)


def _limite(correction: ModeCorrectionPR) -> str:
    suite = ""
    if correction in _BESOIN_SALISSURE:
        suite += _CAVEAT_SPIN_UP
    if correction in _BESOIN_THERMIQUE:
        suite += _CAVEAT_L_TR_6
    return _CAVEAT_PR_REFERENCE + suite


# === Fonction publique pure ================================================


def calculer_pr_realiste(
    mesures: Sequence[MesureJourPRRealiste],
    pr_fourni: float,
    correction: ModeCorrectionPR = "temperature_salissure",
    noct_degc: float | None = None,
    gamma_pmax_pct: float | None = None,
) -> ResultatPRRealiste:
    """PR effectif journalier = ``PR_fourni x ratio_T x (1 - perte/100)`` selon le mode.

    Compose ``_temperature_cellule_noct`` (thermique) et ``calculer_taux_salissure_proxy``
    (salissure). Pure, idempotente. Borne basse douce à 0.
    """
    if not mesures:
        return ResultatPRRealiste(mesures=[], limite=_limite(correction))

    mesures_tri = sorted(mesures, key=lambda m: m["instant_mesure"])

    if correction in _BESOIN_THERMIQUE and (noct_degc is None or gamma_pmax_pct is None):
        raise ValueError(f"noct_degc et gamma_pmax_pct requis pour la correction {correction!r}.")

    facteur_salissure: dict[date, float] = {}
    if correction in _BESOIN_SALISSURE:
        entrees_soiling: list[MesureEntreeSoiling] = [
            {
                "instant_mesure": m["instant_mesure"],
                "rainfall_mm": _exiger_present(m["rainfall_mm"], "rainfall_mm", correction),
                "pm2_5": _exiger_present(m["pm2_5"], "pm2_5", correction),
                "pm10": _exiger_present(m["pm10"], "pm10", correction),
            }
            for m in mesures_tri
        ]
        resultat_soiling = calculer_taux_salissure_proxy(entrees_soiling)
        facteur_salissure = {
            ms.instant: 1.0 - ms.perte_pct / 100.0 for ms in resultat_soiling.mesures
        }

    sorties: list[MesureJourPR] = []
    for m in mesures_tri:
        jour = m["instant_mesure"]
        ratio_t = 1.0
        if correction in _BESOIN_THERMIQUE:
            assert noct_degc is not None and gamma_pmax_pct is not None
            ratio_t = _ratio_thermique_jour(
                _exiger_present(m["ghi_kwh_par_m2_jour"], "ghi_kwh_par_m2_jour", correction),
                _exiger_present(m["t_amb_degc"], "t_amb_degc", correction),
                noct_degc,
                gamma_pmax_pct,
            )
        sf = facteur_salissure.get(jour, 1.0) if correction in _BESOIN_SALISSURE else 1.0
        pr = max(0.0, pr_fourni * ratio_t * sf)
        sorties.append(
            MesureJourPR(instant=jour, pr_realiste=pr, niveau_confiance=NIVEAU_CONFIANCE)
        )

    return ResultatPRRealiste(mesures=sorties, limite=_limite(correction))


def agreger_pr_mensuel(mesures_jour: Sequence[MesureJourPR]) -> list[MesureMoisPR]:
    """Agrège le PR réaliste journalier en **moyenne mensuelle**.

    La courbe mensuelle résultante est la « PR saisonnière » (creux Harmattan). Pure,
    triée chronologiquement (``YYYY-MM``).
    """
    par_mois: dict[str, list[float]] = defaultdict(list)
    for m in mesures_jour:
        par_mois[f"{m.instant.year:04d}-{m.instant.month:02d}"].append(m.pr_realiste)
    return [
        MesureMoisPR(
            instant=mois,
            pr_realiste=sum(valeurs) / len(valeurs),
            niveau_confiance=NIVEAU_CONFIANCE,
        )
        for mois, valeurs in sorted(par_mois.items())
    ]
