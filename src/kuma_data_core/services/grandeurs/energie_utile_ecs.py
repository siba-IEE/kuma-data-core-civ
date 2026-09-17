"""Calcul à la volée de l'énergie utile ECS (grandeur F2).

Énergie thermique utile produite par un capteur solaire eau-chaude-
sanitaire au bord du capteur, fonction des conditions d'irradiance, de
la température entrée fluide caloporteur, et des caractéristiques
optiques et thermiques du capteur fournies par l'appelant.

Modèle retenu v1 :

- **Hottel-Whillier-Bliss bord-capteur** [1, 2] : équation d'efficacité
  instantanée polynôme 2e ordre :

    eta = eta0 - a1 * dT / G - a2 * dT² / G

  avec :
  - eta : rendement instantané du capteur (sans unité)
  - eta0 : rendement optique nul-perte (fiche capteur Solar Keymark)
  - a1 : coefficient pertes linéaires (W/(m²·K))
  - a2 : coefficient pertes quadratiques (W/(m²·K²))
  - dT = T_fluide_moyenne - T_amb (K)
  - G : irradiance globale plan du capteur (W/m²)

  Énergie utile par m² par pas de temps :

    Q_utile = eta * G * Delta_t

  Avec garde-fou eta_instantane = max(0, eta) (pas d'énergie négative).

Limitations documentées :

- pas de calcul système complet (stockage, charge, fraction solaire).
  Méthode f-chart Klein 1976 [3] documentée pour grandeur F3
  ultérieure.
- pas de modulation IAM (Incidence Angle Modifier). Différé si demande
  consommateur.
- coefficients eta0, a1, a2 supposés via fiche Solar Keymark ou
  équivalent (responsabilité appelant).
- T_amb = T2M MERRA-2 avec biais altitude - sous-estimation possible
  Labé / Mamou.

Niveau de confiance dérivé uniforme ``'B'``.

Pattern fonction publique pure ``calculer_energie_utile_ecs`` +
fonctions privées. Aucune dépendance SQL, testable unitairement.

Approximation v1 : T_fluide_moyenne ≈ temperature_fluide_entree_degc
(débit massique m_dot non modélisé - l'impact sur la température de
sortie est différé).

Références bibliographiques :

[1] Hottel H.C., Whillier A. 1958. "Evaluation of flat-plate solar
    collector performance." Transactions of the Conference on the Use
    of Solar Energy, vol. 2, part 1, p. 74. University of Arizona Press.

[2] Duffie J.A., Beckman W.A., Blair N. 2020. "Solar Engineering of
    Thermal Processes, Photovoltaics and Wind", 5e ed. Wiley. ISBN
    978-1-119-54028-1. (Reference standard de l'equation HWB sous forme
    polynome 2e ordre.)

[3] Klein S.A., Beckman W.A., Duffie J.A. 1976. "A design procedure for
    solar heating systems." Solar Energy 18(2), 113-127. DOI :
    10.1016/0038-092X(76)90044-X. (Méthode f-chart, citée pour
    information F3 future.)
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Literal, TypedDict

from kuma_data_core.api.v1.schemas.grandeurs import (
    ParametresEnergieUtileECS,
    ResultatJournalier,
)

# === Constantes module ====================================================

UNITE_ENERGIE_UTILE: str = "kWh/m²"
"""Unité de sortie : énergie cumulée journalière par m² de capteur."""

NIVEAU_CONFIANCE_DERIVE_F2_V1: Literal["B"] = "B"
"""Niveau de confiance uniforme v1."""


# === TypedDict d'entree ===================================================


class MesureJourECS(TypedDict):
    """Mesure journalière consommée par le calcul énergie utile ECS.

    Combine la température ambiante T2M (NASA POWER) et l'irradiance G
    (GHI ou POA pré-calculé). G est exprimée en kWh/m²/jour.
    """

    instant_mesure: date
    t_amb_degc: float
    irradiance_kwh_par_m2_jour: float


class MesureHeureECS(TypedDict):
    """Mesure horaire consommée par l'énergie utile ECS en intégration horaire.

    ``irradiance_w_par_m2`` est l'irradiance horaire (GHI, W/m² ≈ Wh/m² par
    heure) ; ``t_amb_degc`` la température ambiante horaire.
    """

    instant_mesure: datetime
    t_amb_degc: float
    irradiance_w_par_m2: float


# === Fonctions privees pures ==============================================


def _rendement_instantane_hwb(
    eta0: float,
    a1: float,
    a2: float,
    dt_kelvin: float,
    irradiance_w_par_m2: float,
) -> float:
    """Rendement instantané HWB (formule en tête de module).

    Renvoie 0 si irradiance ≤ 0 (capteur inactif) ou si le rendement
    calculé est négatif (stagnation thermique, pas d'énergie utile).
    """
    if irradiance_w_par_m2 <= 0:
        return 0.0
    eta = eta0 - a1 * dt_kelvin / irradiance_w_par_m2 - a2 * (dt_kelvin**2) / irradiance_w_par_m2
    return max(0.0, eta)


def _energie_utile_jour(
    mesure: MesureJourECS,
    parametres: ParametresEnergieUtileECS,
) -> float:
    """Calcule l'énergie utile journalière ECS par m² de capteur (kWh/m²).

    Approche : applique le rendement HWB sur l'irradiance journalière
    en utilisant la température ambiante moyenne du jour. L'approximation
    midi solaire local (W/m² moyen 24h) est utilisée pour le calcul du
    rendement (cohérent biais de moyennage acté).
    """
    # Conversion kWh/m²/jour -> W/m² moyen sur 24h (pour le calcul du rendement
    # qui dépend de G en W/m²). Approximation : répartition uniforme sur 24h.
    irradiance_w_par_m2 = mesure["irradiance_kwh_par_m2_jour"] * 1000.0 / 24.0

    dt_kelvin = parametres.temperature_fluide_entree_degc - mesure["t_amb_degc"]

    eta = _rendement_instantane_hwb(
        eta0=parametres.rendement_optique_eta0,
        a1=parametres.pertes_lineaires_a1,
        a2=parametres.pertes_quadratiques_a2,
        dt_kelvin=dt_kelvin,
        irradiance_w_par_m2=irradiance_w_par_m2,
    )

    # Énergie utile (kWh/m²/jour) = rendement x irradiance journalière.
    return eta * mesure["irradiance_kwh_par_m2_jour"]


# === Fonction publique ====================================================


def calculer_energie_utile_ecs(
    mesures: Sequence[MesureJourECS],
    parametres: ParametresEnergieUtileECS,
) -> list[ResultatJournalier]:
    """Calcule l'énergie utile ECS bord-capteur par jour (Hottel-Whillier-Bliss).

    Itère sur les mesures journalières (T2M + irradiance) et renvoie une
    liste ordonnée de :class:`ResultatJournalier` (unité kWh/m² de
    capteur). Niveau de confiance dérivé uniforme ``'B'``.
    """
    resultats: list[ResultatJournalier] = []
    for mesure in mesures:
        energie = _energie_utile_jour(mesure=mesure, parametres=parametres)
        resultats.append(
            ResultatJournalier(
                instant=mesure["instant_mesure"],
                valeur=energie,
                unite=UNITE_ENERGIE_UTILE,
                niveau_confiance=NIVEAU_CONFIANCE_DERIVE_F2_V1,
            )
        )
    return resultats


def calculer_energie_utile_ecs_horaire(
    mesures: Sequence[MesureHeureECS],
    parametres: ParametresEnergieUtileECS,
) -> list[ResultatJournalier]:
    """Calcule l'énergie utile ECS par **intégration horaire** (Hottel-Whillier-Bliss).

    Applique le rendement HWB **heure par heure** sur l'irradiance horaire
    réelle, puis somme l'énergie utile sur la journée calendaire (UTC).
    Contrairement à la méthode journalière (rendement calculé sur la moyenne
    24 h), l'intégration horaire lève le biais de Jensen : le rendement HWB
    ``eta = eta0 - a1 dT/G - a2 dT²/G`` est **non-linéaire** en G, donc le
    rendement de la moyenne 24 h ne reproduit pas la somme horaire.

    Entrée : GHI + T2M horaires alignés par l'appelant. Sortie : un
    :class:`ResultatJournalier` par jour (unité ``kWh/m²``). Pure arithmétique
    (pas de géométrie solaire).
    """
    energie_par_jour: dict[date, float] = {}
    for mesure in mesures:
        irradiance_w = mesure["irradiance_w_par_m2"]
        dt_kelvin = parametres.temperature_fluide_entree_degc - mesure["t_amb_degc"]
        eta = _rendement_instantane_hwb(
            eta0=parametres.rendement_optique_eta0,
            a1=parametres.pertes_lineaires_a1,
            a2=parametres.pertes_quadratiques_a2,
            dt_kelvin=dt_kelvin,
            irradiance_w_par_m2=irradiance_w,
        )
        # Énergie utile horaire (kWh/m²) = eta x (irradiance W/m² x 1 h /1000 -> kWh/m²).
        energie_heure = eta * (irradiance_w / 1000.0)
        jour = mesure["instant_mesure"].date()
        energie_par_jour[jour] = energie_par_jour.get(jour, 0.0) + energie_heure

    return [
        ResultatJournalier(
            instant=jour,
            valeur=energie,
            unite=UNITE_ENERGIE_UTILE,
            niveau_confiance=NIVEAU_CONFIANCE_DERIVE_F2_V1,
        )
        for jour, energie in energie_par_jour.items()
    ]
