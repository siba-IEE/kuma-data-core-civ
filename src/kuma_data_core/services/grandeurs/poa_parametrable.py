"""Calcul à la volée du POA paramétrable (grandeur F2).

Plane-of-Array (POA) calculé pour un plan d'inclinaison ``beta`` et
d'orientation ``gamma`` (azimut) à partir des composantes d'irradiance
mesurées en plan horizontal (GHI, et si disponible DNI / DHI).

Modèles retenus en v1 :

- **Modèle primaire Perez 1990** [1] : décomposition diffus du ciel en
  3 zones (isotropique de fond, circumsolaire, horizon). Utilisé
  lorsque les composantes DNI et DHI sont disponibles dans la série
  source F1.

- **Modèle fallback Liu-Jordan 1963** [2] (isotrope) : utilisé
  lorsque seul le GHI est disponible (cas typique des séries
  ``mesures_ressource_mensuelles`` SARAH-3 ICDR ou NASA POWER monthly
  climato 1991-2020). La décomposition GHI -> (DNI estimé, DHI estimé)
  est réalisée via la corrélation Erbs 1982 [3] intégrée à pvlib.

Implémentation via la bibliothèque ``pvlib`` (v0.15+) pour les fonctions
de position solaire, décomposition GHI et transposition POA. Citée par
PVsyst et NREL SAM comme référence industrielle. Approche midi solaire
local (jour représentatif) pour la granularité journalière - biais de
moyennage acté.

Niveau de confiance dérivé uniforme ``'B'``.

Pattern fonction publique pure ``calculer_poa_parametrable`` +
fonctions privées. Aucune dépendance SQL, testable unitairement.

Limitations documentées :

- coefficients Perez non recalibrés Afrique de l'Ouest.
- fallback Liu-Jordan dégrade la précision 10-15% sous ciel
  partiellement couvert.
- pas de prise en compte d'ombrage local.

Références bibliographiques :

[1] Perez R., Ineichen P., Seals R., Michalsky J., Stewart R. 1990.
    "Modeling daylight availability and irradiance components from
    direct and global irradiance." Solar Energy 44(5), 271-289.
    DOI : 10.1016/0038-092X(90)90055-H.

[2] Liu B.Y.H., Jordan R.C. 1963. "The long-term average performance
    of flat-plate solar-energy collectors." Solar Energy 7, 53-74.
    DOI : 10.1016/0038-092X(63)90006-9.

[3] Erbs D.G., Klein S.A., Duffie J.A. 1982. "Estimation of the diffuse
    radiation fraction for hourly, daily and monthly-average global
    radiation." Solar Energy 28(4), 293-302.
    DOI : 10.1016/0038-092X(82)90302-4.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Literal, TypedDict

import pandas as pd  # type: ignore[import-untyped]
import pvlib  # type: ignore[import-untyped]

from kuma_data_core.api.v1.schemas.grandeurs import (
    ParametresPOA,
    ResultatJournalier,
)

# === Constantes module ====================================================

UNITE_POA: str = "kWh/m²/jour"
"""Unité de sortie POA en granularité journalière."""

NIVEAU_CONFIANCE_DERIVE_F2_V1: Literal["B"] = "B"
"""Niveau de confiance uniforme v1."""

MODELE_PEREZ: Literal["perez"] = "perez"
"""Identifiant pvlib du modèle Perez 1990."""

MODELE_ISOTROPE: Literal["isotropic"] = "isotropic"
"""Identifiant pvlib du modèle isotrope Liu-Jordan 1963."""


# === TypedDict d'entree ===================================================


class MesureJourPOA(TypedDict):
    """Mesure d'irradiance journalière consommée par le calcul POA.

    ``ghi`` est obligatoire ; ``dni`` et ``dhi`` sont optionnels. Si
    ces deux derniers sont ``None``, le fallback Liu-Jordan est
    déclenché pour ce jour.
    """

    instant_mesure: date
    ghi: float
    dni: float | None
    dhi: float | None


class MesureHeurePOA(TypedDict):
    """Mesure d'irradiance horaire consommée par le POA en intégration horaire.

    GHI/DNI/DHI tous obligatoires (l'appelant n'aligne que les instants
    complets ; cf. ``calculer_poa_parametrable_horaire``).
    """

    instant_mesure: datetime
    ghi: float
    dni: float
    dhi: float


# === Fonctions privees pures ==============================================


def _midi_solaire_utc(jour: date, longitude_deg: float) -> datetime:
    """Renvoie l'instant de midi solaire approximatif (UTC) pour un jour donné.

    Approximation pragmatique : midi solaire ≈ 12:00 UTC - longitude/15.
    Suffisant pour application du modèle POA à granularité journalière
    (biais de moyennage acté).
    """
    decalage_heures = -longitude_deg / 15.0
    return datetime(jour.year, jour.month, jour.day, 12, 0, 0, tzinfo=UTC) + timedelta(
        hours=decalage_heures
    )


def _calculer_poa_jour(
    mesure: MesureJourPOA,
    latitude_deg: float,
    longitude_deg: float,
    parametres: ParametresPOA,
) -> float:
    """Calcule le POA journalier pour une mesure unique.

    Choisit dynamiquement le modèle Perez ou Liu-Jordan selon la
    disponibilité de DNI / DHI dans la mesure :

    - DNI ET DHI disponibles -> Perez 1990 [1]
    - DNI OU DHI manquant -> Liu-Jordan isotrope avec décomposition
      GHI -> (DNI estimé, DHI estimé) via Erbs 1982 [3]

    Renvoie la valeur POA dans la même unité que la GHI d'entrée
    (typiquement kWh/m²/jour pour séries journalières NASA POWER).
    """
    instant_utc = _midi_solaire_utc(mesure["instant_mesure"], longitude_deg)
    times = pd.DatetimeIndex([instant_utc])
    solpos = pvlib.solarposition.get_solarposition(times, latitude_deg, longitude_deg)

    dni_a_utiliser: float
    dhi_a_utiliser: float
    modele: str
    if mesure["dni"] is not None and mesure["dhi"] is not None:
        dni_a_utiliser = mesure["dni"]
        dhi_a_utiliser = mesure["dhi"]
        modele = MODELE_PEREZ
    else:
        # Fallback Liu-Jordan : décomposition GHI -> (DNI estimé, DHI estimé)
        # via corrélation Erbs 1982 intégrée à pvlib.
        decomposition = pvlib.irradiance.erbs(
            ghi=mesure["ghi"],
            zenith=solpos["zenith"].iloc[0],
            datetime_or_doy=instant_utc,
        )
        dni_a_utiliser = float(decomposition["dni"])
        dhi_a_utiliser = float(decomposition["dhi"])
        modele = MODELE_ISOTROPE

    # dni_extra (irradiance extra-atmosphérique) requise par Perez
    # (pvlib lève ValueError sans). Calculée via pvlib.irradiance.get_extra_radiation.
    dni_extra = float(pvlib.irradiance.get_extra_radiation(instant_utc))

    resultat_poa = pvlib.irradiance.get_total_irradiance(
        surface_tilt=parametres.inclinaison_deg,
        surface_azimuth=parametres.orientation_deg,
        solar_zenith=solpos["zenith"].iloc[0],
        solar_azimuth=solpos["azimuth"].iloc[0],
        dni=dni_a_utiliser,
        ghi=mesure["ghi"],
        dhi=dhi_a_utiliser,
        dni_extra=dni_extra,
        albedo=parametres.albedo_sol,
        model=modele,
    )

    poa_global = float(resultat_poa["poa_global"])
    # Garde-fou : pvlib peut retourner NaN si position solaire dégénérée
    # (nuit, polaire). En contexte Guinée à midi solaire, sans risque.
    if pd.isna(poa_global) or poa_global < 0:
        return 0.0
    return poa_global


# === Fonction publique ====================================================


def calculer_poa_parametrable(
    mesures: Sequence[MesureJourPOA],
    latitude_deg: float,
    longitude_deg: float,
    parametres: ParametresPOA,
) -> list[ResultatJournalier]:
    """Calcule le POA paramétrable pour une série F1 source journalière.

    Itère sur les mesures journalières dans la fenêtre demandée et
    applique le modèle Perez (DNI+DHI disponibles) ou Liu-Jordan
    fallback (GHI seul). Retourne une liste ordonnée de
    :class:`ResultatJournalier`.

    Paramètres :
        mesures : séquence de mesures journalières GHI (+ DNI / DHI
            optionnels). Filtrés en amont sur la fenêtre temporelle.
        latitude_deg : latitude de la localité (degrés, plage [-90, 90]).
        longitude_deg : longitude de la localité (degrés, plage [-180, 180]).
        parametres : paramètres techniques POA fournis par l'appelant
            (inclinaison, orientation, albedo).

    Renvoie :
        Liste de :class:`ResultatJournalier` ordonnée par
        ``instant_mesure`` croissante. Liste vide si ``mesures`` est
        vide.

    Aucune dépendance SQL, idempotent, pur. Le niveau de confiance
    dérivé est uniformément ``'B'``.
    """
    resultats: list[ResultatJournalier] = []
    for mesure in mesures:
        poa_valeur = _calculer_poa_jour(
            mesure=mesure,
            latitude_deg=latitude_deg,
            longitude_deg=longitude_deg,
            parametres=parametres,
        )
        resultats.append(
            ResultatJournalier(
                instant=mesure["instant_mesure"],
                valeur=poa_valeur,
                unite=UNITE_POA,
                niveau_confiance=NIVEAU_CONFIANCE_DERIVE_F2_V1,
            )
        )
    return resultats


def calculer_poa_parametrable_horaire(
    mesures: Sequence[MesureHeurePOA],
    latitude_deg: float,
    longitude_deg: float,
    parametres: ParametresPOA,
) -> list[ResultatJournalier]:
    """Calcule le POA journalier par **intégration horaire** (modèle Perez 1990).

    Applique Perez heure par heure (géométrie solaire réelle de chaque
    heure) puis somme sur la journée calendaire (UTC) pour obtenir un POA
    journalier. Contrairement à la méthode journalière (Perez au midi
    solaire appliqué au total du jour), l'intégration horaire ne surestime
    pas le gain d'un plan incliné : elle lève le biais de moyennage
    (+16 % mesuré pour un plan incliné).

    Vectorisé via ``pvlib`` (position solaire + transposition sur tous les
    instants en une passe). GHI/DNI/DHI horaires obligatoires (l'appelant
    n'aligne que les instants complets). Sortie : un :class:`ResultatJournalier`
    par jour présent (unité ``kWh/m²/jour``, identique à la méthode
    journalière).

    Pure (pandas/pvlib, aucune dépendance SQL), idempotente. Niveau de
    confiance dérivé uniforme ``'B'``.
    """
    if not mesures:
        return []

    index = pd.DatetimeIndex([m["instant_mesure"] for m in mesures])
    ghi = pd.Series([m["ghi"] for m in mesures], index=index, dtype=float)
    dni = pd.Series([m["dni"] for m in mesures], index=index, dtype=float)
    dhi = pd.Series([m["dhi"] for m in mesures], index=index, dtype=float)

    solpos = pvlib.solarposition.get_solarposition(index, latitude_deg, longitude_deg)
    dni_extra = pvlib.irradiance.get_extra_radiation(index)
    poa_global = pvlib.irradiance.get_total_irradiance(
        surface_tilt=parametres.inclinaison_deg,
        surface_azimuth=parametres.orientation_deg,
        solar_zenith=solpos["zenith"],
        solar_azimuth=solpos["azimuth"],
        dni=dni,
        ghi=ghi,
        dhi=dhi,
        dni_extra=dni_extra,
        albedo=parametres.albedo_sol,
        model=MODELE_PEREZ,
    )["poa_global"]

    # W/m² horaires (≈ Wh/m² par heure ; nuit/horizon -> NaN ou négatif clampé
    # à 0) sommés par jour -> Wh/m²/jour ; /1000 -> kWh/m²/jour.
    poa_horaire = poa_global.clip(lower=0).fillna(0.0)
    poa_par_jour = poa_horaire.groupby(poa_horaire.index.date).sum() / 1000.0

    return [
        ResultatJournalier(
            instant=jour,
            valeur=float(valeur),
            unite=UNITE_POA,
            niveau_confiance=NIVEAU_CONFIANCE_DERIVE_F2_V1,
        )
        for jour, valeur in poa_par_jour.items()
    ]
