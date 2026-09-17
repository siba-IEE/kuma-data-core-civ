"""Calcul à la volée du POA bifacial (grandeur F2).

POA global **bifacial** d'un champ de rangées, modèle **infinite-sheds**
(view-factor row-aware, ``pvlib.bifacial.infinite_sheds``). Distinct du
``poa_parametrable`` mono-plan : modélise la **géométrie de rangées** (gcr,
hauteur, pitch) et la **face arrière** captant le rayonnement réfléchi par le
sol (albedo). La grandeur expose ``poa_global`` = la sortie bifaciale du modèle
(face avant + gain arrière, **bifacialité appliquée en interne par pvlib** ;
vérifié : ``bifaciality=0`` -> ``poa_global == poa_front``).

Modèle de diffus ciel : isotrope (défaut infinite-sheds ; moins anisotrope que
le Perez du POA mono-plan). Niveau de confiance dérivé uniforme ``'B'``
(doctrine F2 v1).

Pattern fonctions publiques pures (``pvlib`` / ``pandas``, aucune dépendance
SQL). Le biais de moyennage est acté pour la méthode journalière
(infinite-sheds au midi solaire appliqué aux totaux du jour) et **levé** par la
méthode horaire.

Références :

[1] Mikofski M., Darawali R., Hamer M., Neubert A., Newmiller J. 2019.
    "Bifacial Performance Modeling in Large Arrays." 46th IEEE PVSC. (Modèle
    infinite-sheds, implémenté dans ``pvlib.bifacial.infinite_sheds``.)
[2] Marion B. et al. 2017. "A Practical Irradiance Model for Bifacial PV
    Modules." 44th IEEE PVSC. DOI : 10.1109/PVSC.2017.8366263.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Literal, TypedDict

import pandas as pd  # type: ignore[import-untyped]
import pvlib  # type: ignore[import-untyped]
from pvlib.bifacial import infinite_sheds  # type: ignore[import-untyped]

from kuma_data_core.api.v1.schemas.grandeurs import (
    ParametresBifacial,
    ResultatJournalier,
)

# Réutilise le helper midi solaire du POA mono-plan : même approche journalière
# (géométrie du midi appliquée aux totaux du jour, biais de moyennage acté). Import
# privé cross-module assumé (pattern déjà utilisé : productible_pr_fourni importe
# _temperature_cellule_noct). Aucune duplication de formule.
from kuma_data_core.services.grandeurs.poa_parametrable import _midi_solaire_utc

# === Constantes module ====================================================

UNITE_POA_BIFACIAL: str = "kWh/m²/jour"
"""Unité de sortie (POA global bifacial journalier)."""

NIVEAU_CONFIANCE_DERIVE_F2_V1: Literal["B"] = "B"
"""Niveau de confiance uniforme v1 (doctrine F2)."""


# === TypedDict d'entree ===================================================


class MesureJourBifacial(TypedDict):
    """Mesure journaliere consommee par le POA bifacial (GHI/DNI/DHI + albedo)."""

    instant_mesure: date
    ghi: float
    dni: float
    dhi: float
    albedo: float


class MesureHeureBifacial(TypedDict):
    """Mesure horaire consommée par le POA bifacial en intégration horaire.

    GHI/DNI/DHI horaires (W/m²) ; ``albedo`` est l'albedo **du jour** (broadcast
    intra-journée : l'albedo n'existe qu'en journalier).
    """

    instant_mesure: datetime
    ghi: float
    dni: float
    dhi: float
    albedo: float


# === Repli albedo (pur, testable) =========================================


def albedo_du_jour(albedo_par_jour: dict[date, float], jour: date, albedo_repli: float) -> float:
    """Albedo d'un jour : valeur réelle de la série ``albedo_surface`` si présente,
    sinon **repli** sur ``albedo_repli`` (``params.albedo_sol``).

    Capture la règle de repli : quand la série compagne ``albedo_surface``
    est absente (ou ne couvre pas le jour), le calcul bifacial utilise l'albedo
    utilisateur par défaut plutôt que d'échouer.
    """
    return albedo_par_jour.get(jour, albedo_repli)


# === Fonction privee pure (cœur infinite-sheds) ===========================


def _poa_global_infinite_sheds(
    index: pd.DatetimeIndex,
    ghi: pd.Series,
    dni: pd.Series,
    dhi: pd.Series,
    albedo: pd.Series,
    latitude_deg: float,
    longitude_deg: float,
    parametres: ParametresBifacial,
) -> pd.Series:
    """Applique infinite-sheds vectorisé -> Series ``poa_global``.

    Sortie dans la **même unité** que les irradiances d'entrée (le modèle est
    linéaire en irradiance) : kWh/m²/jour pour des entrées journalières au midi
    solaire, W/m² pour des entrées horaires.
    """
    solpos = pvlib.solarposition.get_solarposition(index, latitude_deg, longitude_deg)
    resultat = infinite_sheds.get_irradiance(
        surface_tilt=parametres.inclinaison_deg,
        surface_azimuth=parametres.orientation_deg,
        solar_zenith=solpos["apparent_zenith"],
        solar_azimuth=solpos["azimuth"],
        gcr=parametres.gcr,
        height=parametres.hauteur_m,
        pitch=parametres.pitch_m,
        ghi=ghi,
        dhi=dhi,
        dni=dni,
        albedo=albedo,
        bifaciality=parametres.bifacialite,
    )
    return resultat["poa_global"]


# === Fonctions publiques ==================================================


def calculer_poa_bifacial(
    mesures: Sequence[MesureJourBifacial],
    latitude_deg: float,
    longitude_deg: float,
    parametres: ParametresBifacial,
) -> list[ResultatJournalier]:
    """POA bifacial journalier (infinite-sheds au midi solaire).

    Applique infinite-sheds à la géométrie du **midi solaire** sur les totaux
    journaliers (modèle linéaire -> sortie kWh/m²/jour). Biais de moyennage
    acté (cf. ``poa_parametrable``) ; levé par la méthode horaire.

    Pure, idempotente. Niveau de confiance uniforme ``'B'``.
    """
    if not mesures:
        return []
    jours = [m["instant_mesure"] for m in mesures]
    index = pd.DatetimeIndex([_midi_solaire_utc(j, longitude_deg) for j in jours])
    ghi = pd.Series([m["ghi"] for m in mesures], index=index, dtype=float)
    dni = pd.Series([m["dni"] for m in mesures], index=index, dtype=float)
    dhi = pd.Series([m["dhi"] for m in mesures], index=index, dtype=float)
    albedo = pd.Series([m["albedo"] for m in mesures], index=index, dtype=float)

    poa = _poa_global_infinite_sheds(
        index, ghi, dni, dhi, albedo, latitude_deg, longitude_deg, parametres
    )
    valeurs = poa.clip(lower=0).fillna(0.0).to_numpy()
    return [
        ResultatJournalier(
            instant=jours[i],
            valeur=float(valeurs[i]),
            unite=UNITE_POA_BIFACIAL,
            niveau_confiance=NIVEAU_CONFIANCE_DERIVE_F2_V1,
        )
        for i in range(len(jours))
    ]


def calculer_poa_bifacial_horaire(
    mesures: Sequence[MesureHeureBifacial],
    latitude_deg: float,
    longitude_deg: float,
    parametres: ParametresBifacial,
) -> list[ResultatJournalier]:
    """POA bifacial par **intégration horaire** (infinite-sheds par heure, somme/jour).

    Applique infinite-sheds heure par heure (géométrie solaire réelle) puis somme
    sur la journée calendaire (UTC). Lève le biais de moyennage.
    L'``albedo`` est fourni **par jour** (broadcast intra-journée).

    Pure, idempotente. Niveau de confiance uniforme ``'B'``.
    """
    if not mesures:
        return []
    index = pd.DatetimeIndex([m["instant_mesure"] for m in mesures])
    ghi = pd.Series([m["ghi"] for m in mesures], index=index, dtype=float)
    dni = pd.Series([m["dni"] for m in mesures], index=index, dtype=float)
    dhi = pd.Series([m["dhi"] for m in mesures], index=index, dtype=float)
    albedo = pd.Series([m["albedo"] for m in mesures], index=index, dtype=float)

    poa = _poa_global_infinite_sheds(
        index, ghi, dni, dhi, albedo, latitude_deg, longitude_deg, parametres
    )
    # W/m² horaires (≈ Wh/m² par heure ; nuit/horizon clampé à 0) sommés par jour
    # -> Wh/m²/jour ; /1000 -> kWh/m²/jour.
    poa_horaire = poa.clip(lower=0).fillna(0.0)
    poa_par_jour = poa_horaire.groupby(poa_horaire.index.date).sum() / 1000.0

    return [
        ResultatJournalier(
            instant=jour,
            valeur=float(valeur),
            unite=UNITE_POA_BIFACIAL,
            niveau_confiance=NIVEAU_CONFIANCE_DERIVE_F2_V1,
        )
        for jour, valeur in poa_par_jour.items()
    ]
