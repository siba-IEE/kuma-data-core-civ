"""Calcul de l'indice de clarté ``kt`` (grandeur F1 stockée) - fonctions pures.

L'indice de clarté rapporte l'irradiation globale horizontale reçue au sol
``H`` (GHI) à l'irradiation extraterrestre sur plan horizontal ``H0``, celle
qui atteindrait le même lieu en l'absence d'atmosphère :

```
kt(annee, mois) := Σ GHI(t) / Σ H0(t), t ∈ jours(annee, mois)
kt(annee)       := Σ GHI(t) / Σ H0(t), t ∈ jours(annee)
```

Les séries mensuelles portent la **moyenne journalière** du mois. Sur les
jours d'un mois, ``Σ GHI = GHI_moyen × n`` et ``Σ H0 = H0_moyen × n``, donc
``kt(annee, mois) = GHI_moyen / H0_moyen`` ; sur une année,
``Σ_m GHI_m·n_m / Σ_m H0_m·n_m`` (``n_m`` = jours civils du mois). Le rapport
de sommes n'est **pas** la moyenne des rapports mensuels.

``H0`` journalier : équation 1.10.3 de Duffie & Beckman [1], intégrale de
l'éclairement extraterrestre horizontal du lever au coucher du soleil :

```
H0 = (24 / π) · Gsc · E0(n) · (cos φ cos δ sin ωs + ωs sin φ sin δ)
cos ωs = −tan φ tan δ                                      (D&B éq. 1.6.10)
```

avec ``φ`` la latitude, ``δ`` la déclinaison, ``ωs`` l'angle horaire du
coucher (radians), ``E0`` la correction d'excentricité de l'orbite et ``n``
le rang du jour dans l'année. Choix tranchés (version de formule 1, cf.
fiche ``docs/methodologie/grandeurs/kt.md`` et ADR-0026) :

- **Déclinaison et excentricité de Spencer (1971)** [2] (D&B éq. 1.6.1b et
  1.4.1b) : séries de Fourier en ``B = 2π(n − 1)/365``, erreur < 0,035° sur
  la déclinaison et ±0,01 % sur l'excentricité, contre un écart allant
  jusqu'à 1,4° pour la formule de Cooper (1969) [3] (D&B éq. 1.6.1a). Le
  modèle ``"cooper"`` (Cooper + ``1 + 0,033 cos(2πn/365)``, l'équation 1.10.3
  telle qu'écrite) reste disponible pour reproduire la table 1.10.1 de D&B.
- **Constante solaire 1361 W/m²** : valeur mesurée par SORCE/TIM (Kopp &
  Lean 2011 [4], 1360,8 ± 0,5 W/m²), retenue comme valeur nominale par l'UAI
  (résolution B3, 2015) [5]. D&B gardent la valeur WRC de 1367 W/m², 0,44 %
  plus haute ; elle donnerait des ``kt`` 0,44 % plus bas.
- **``H0`` mensuel** : moyenne des ``H0`` journaliers de **tous** les jours
  civils du mois (et non la valeur au « jour moyen » de Klein 1977, D&B
  table 1.6.1). Années bissextiles : ``n`` va de 1 à 366, ``B`` garde le
  dénominateur 365 (comme D&B et pvlib).

Fonctions pures, sans I/O ni dépendance SQL : la migration 0041 et les tests
les appellent directement. Unités : ``H0`` et ``GHI`` en kWh/m²/jour.

Références bibliographiques :

[1] Duffie J.A., Beckman W.A., Blair N. 2020. *Solar Engineering of Thermal
    Processes, Photovoltaics and Wind*, 5ᵉ éd., Wiley. § 1.4, 1.6 et 1.10
    (éq. 1.4.1, 1.6.1, 1.6.10, 1.10.3 ; tables 1.6.1 et 1.10.1).
    ISBN 978-1-119-54028-1.

[2] Spencer J.W. 1971. "Fourier series representation of the position of the
    Sun." *Search* 2(5), 172.

[3] Cooper P.I. 1969. "The absorption of radiation in solar stills."
    *Solar Energy* 12(3) (référence telle que citée par [1]).

[4] Kopp G., Lean J.L. 2011. "A new, lower value of total solar irradiance:
    Evidence and climate significance." *Geophysical Research Letters* 38,
    L01706. DOI : 10.1029/2010GL045777.

[5] Union astronomique internationale 2015. Résolution B3, « On recommended
    nominal conversion constants for selected solar and planetary
    properties » (constante solaire nominale 1361 W/m²).
"""

from __future__ import annotations

import calendar
import math
from collections.abc import Mapping
from datetime import date
from functools import lru_cache
from typing import Literal, TypedDict

# === Constantes module ====================================================

GRANDEUR_CODE_KT: str = "kt"
"""Code naturel de la grandeur dans ``grandeurs_referentiel`` (id 2)."""

VERSION_FORMULE_KT: int = 1
"""Version de formule courante (fiche ``kt.md`` § 9)."""

CONSTANTE_SOLAIRE_W_M2: float = 1361.0
"""Constante solaire retenue (Kopp & Lean 2011 ; UAI 2015 B3), en W/m²."""

CONSTANTE_SOLAIRE_DUFFIE_BECKMAN_W_M2: float = 1367.0
"""Valeur WRC utilisée par Duffie & Beckman (table 1.10.1), en W/m²."""

ModeleSolaire = Literal["spencer", "cooper"]
"""``spencer`` : D&B éq. 1.6.1b + 1.4.1b ; ``cooper`` : éq. 1.6.1a + 1.4.1a."""

MODELE_DEFAUT: ModeleSolaire = "spencer"
"""Modèle de déclinaison et d'excentricité retenu en version 1."""

HEURES_PAR_JOUR: float = 24.0
"""Durée du jour solaire (h) : ``H0 = (24/π)·G`` en Wh/m² pour ``G`` en W/m²."""


# === Géométrie solaire (fonctions pures) ==================================


def angle_journalier(rang_jour: int) -> float:
    """Angle journalier de Spencer ``B = 2π(n − 1)/365``, en radians (D&B éq. 1.4.2)."""
    return 2.0 * math.pi * (rang_jour - 1) / 365.0


def declinaison(rang_jour: int, modele: ModeleSolaire = MODELE_DEFAUT) -> float:
    """Déclinaison solaire ``δ`` du jour de rang ``n``, en radians.

    - ``spencer`` (D&B éq. 1.6.1b, Spencer 1971) : erreur < 0,035° ;
    - ``cooper`` (D&B éq. 1.6.1a, Cooper 1969) :
      ``δ = 23,45° · sin(360° · (284 + n)/365)``.
    """
    if modele == "cooper":
        return math.radians(23.45 * math.sin(2.0 * math.pi * (284 + rang_jour) / 365.0))
    b = angle_journalier(rang_jour)
    return (
        0.006918
        - 0.399912 * math.cos(b)
        + 0.070257 * math.sin(b)
        - 0.006758 * math.cos(2.0 * b)
        + 0.000907 * math.sin(2.0 * b)
        - 0.002697 * math.cos(3.0 * b)
        + 0.00148 * math.sin(3.0 * b)
    )


def facteur_excentricite(rang_jour: int, modele: ModeleSolaire = MODELE_DEFAUT) -> float:
    """Correction d'excentricité ``E0 = (r0/r)²`` du jour de rang ``n`` (sans dimension).

    - ``spencer`` (D&B éq. 1.4.1b, Spencer 1971) : précision ±0,01 % ;
    - ``cooper`` (D&B éq. 1.4.1a) : ``E0 = 1 + 0,033 · cos(360° · n/365)``.
    """
    if modele == "cooper":
        return 1.0 + 0.033 * math.cos(2.0 * math.pi * rang_jour / 365.0)
    b = angle_journalier(rang_jour)
    return (
        1.000110
        + 0.034221 * math.cos(b)
        + 0.001280 * math.sin(b)
        + 0.000719 * math.cos(2.0 * b)
        + 0.000077 * math.sin(2.0 * b)
    )


def angle_horaire_coucher(latitude_rad: float, declinaison_rad: float) -> float:
    """Angle horaire du coucher ``ωs`` (D&B éq. 1.6.10), en radians.

    ``cos ωs = −tan φ tan δ``, borné à ``[−1, 1]`` : ``ωs = 0`` en nuit
    polaire, ``ωs = π`` en jour polaire (sans effet entre les tropiques).
    """
    cos_ws = -math.tan(latitude_rad) * math.tan(declinaison_rad)
    return math.acos(max(-1.0, min(1.0, cos_ws)))


def h0_rang(
    latitude_deg: float,
    rang_jour: int,
    *,
    constante_solaire: float = CONSTANTE_SOLAIRE_W_M2,
    modele: ModeleSolaire = MODELE_DEFAUT,
) -> float:
    """``H0`` du jour de rang ``n`` (1 à 366) à la latitude donnée, en kWh/m²/jour.

    D&B éq. 1.10.3 : ``(24/π)·Gsc·E0·(cos φ cos δ sin ωs + ωs sin φ sin δ)``,
    ``ωs`` en radians ; division par 1000 pour passer de Wh à kWh.
    """
    phi = math.radians(latitude_deg)
    delta = declinaison(rang_jour, modele)
    ws = angle_horaire_coucher(phi, delta)
    terme_cos = math.cos(phi) * math.cos(delta) * math.sin(ws)
    geometrie = terme_cos + ws * math.sin(phi) * math.sin(delta)
    return (
        HEURES_PAR_JOUR
        / math.pi
        * constante_solaire
        * facteur_excentricite(rang_jour, modele)
        * geometrie
        / 1000.0
    )


def h0_journalier(
    latitude_deg: float,
    jour: date,
    *,
    constante_solaire: float = CONSTANTE_SOLAIRE_W_M2,
    modele: ModeleSolaire = MODELE_DEFAUT,
) -> float:
    """``H0`` d'un jour civil à la latitude donnée, en kWh/m²/jour."""
    return h0_rang(
        latitude_deg,
        jour.timetuple().tm_yday,
        constante_solaire=constante_solaire,
        modele=modele,
    )


@lru_cache(maxsize=65_536)
def _h0_mensuel(
    latitude_deg: float,
    bissextile: bool,
    mois: int,
    constante_solaire: float,
    modele: ModeleSolaire,
) -> float:
    """Moyenne des ``H0`` journaliers d'un mois ; ne dépend de l'année que par le bissextile."""
    annee = 2000 if bissextile else 2001
    premier = date(annee, mois, 1).timetuple().tm_yday
    nb_jours = calendar.monthrange(annee, mois)[1]
    somme = math.fsum(
        h0_rang(latitude_deg, n, constante_solaire=constante_solaire, modele=modele)
        for n in range(premier, premier + nb_jours)
    )
    return somme / nb_jours


def h0_mensuel(
    latitude_deg: float,
    annee: int,
    mois: int,
    *,
    constante_solaire: float = CONSTANTE_SOLAIRE_W_M2,
    modele: ModeleSolaire = MODELE_DEFAUT,
) -> float:
    """``H0`` moyen d'un mois civil : moyenne des ``H0`` de tous ses jours, kWh/m²/jour."""
    if not 1 <= mois <= 12:
        raise ValueError(f"Mois hors de [1, 12] : {mois!r}.")
    return _h0_mensuel(
        float(latitude_deg), calendar.isleap(annee), mois, float(constante_solaire), modele
    )


# === Indice de clarté (fonctions pures) ===================================


def kt_mensuel(ghi_moyen: float, h0_moyen: float) -> float:
    """``kt`` d'un mois : ``GHI_moyen / H0_moyen`` (= ``Σ GHI / Σ H0`` sur ses jours)."""
    if h0_moyen <= 0.0:
        raise ValueError(f"H0 non positif ({h0_moyen!r}) : kt non défini.")
    return ghi_moyen / h0_moyen


def kt_annuel(
    ghi_mensuels: Mapping[int, float], h0_mensuels: Mapping[int, float], annee: int
) -> float:
    """``kt`` d'une année : ``Σ_m GHI_m·n_m / Σ_m H0_m·n_m`` sur ses 12 mois.

    Args:
        ghi_mensuels : ``{mois: GHI moyen journalier}`` (kWh/m²/jour), 12 mois.
        h0_mensuels : ``{mois: H0 moyen journalier}`` (kWh/m²/jour), 12 mois.
        annee : année civile (nombre de jours de février).

    Raises:
        ValueError : si un mois manque (complétude stricte) ou si ``Σ H0 ≤ 0``.
    """
    mois_attendus = set(range(1, 13))
    if set(ghi_mensuels) != mois_attendus or set(h0_mensuels) != mois_attendus:
        raise ValueError(f"Année {annee} incomplète : les 12 mois sont requis.")
    jours = {m: calendar.monthrange(annee, m)[1] for m in range(1, 13)}
    somme_ghi = math.fsum(ghi_mensuels[m] * jours[m] for m in range(1, 13))
    somme_h0 = math.fsum(h0_mensuels[m] * jours[m] for m in range(1, 13))
    if somme_h0 <= 0.0:
        raise ValueError(f"Σ H0 non positive ({somme_h0!r}) en {annee} : kt non défini.")
    return somme_ghi / somme_h0


class LigneKt(TypedDict):
    """Une valeur de ``kt`` prête pour ``grandeurs_metier``."""

    periode_type: str  # "mensuel" ou "annuel"
    annee: int
    mois: int | None
    valeur: float


def calculer_kt(
    ghi_mensuel: Mapping[tuple[int, int], float],
    latitude_deg: float,
    *,
    constante_solaire: float = CONSTANTE_SOLAIRE_W_M2,
    modele: ModeleSolaire = MODELE_DEFAUT,
) -> list[LigneKt]:
    """``kt`` mensuel de chaque mois fourni, et annuel des années complètes.

    Args:
        ghi_mensuel : ``{(annee, mois): GHI moyen journalier}`` en kWh/m²/jour.
        latitude_deg : latitude du lieu, en degrés (positive au nord).

    Returns:
        Lignes triées par année : les mois de l'année puis, si ses 12 mois
        sont présents (complétude stricte), la ligne annuelle.
    """
    lignes: list[LigneKt] = []
    for annee in sorted({a for a, _ in ghi_mensuel}):
        ghi_annee = {m: v for (a, m), v in ghi_mensuel.items() if a == annee}
        h0_annee = {
            m: h0_mensuel(
                latitude_deg, annee, m, constante_solaire=constante_solaire, modele=modele
            )
            for m in ghi_annee
        }
        for mois in sorted(ghi_annee):
            lignes.append(
                {
                    "periode_type": "mensuel",
                    "annee": annee,
                    "mois": mois,
                    "valeur": kt_mensuel(ghi_annee[mois], h0_annee[mois]),
                }
            )
        if len(ghi_annee) == 12:
            lignes.append(
                {
                    "periode_type": "annuel",
                    "annee": annee,
                    "mois": None,
                    "valeur": kt_annuel(ghi_annee, h0_annee, annee),
                }
            )
    return lignes
