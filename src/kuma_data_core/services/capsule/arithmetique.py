"""Les deux dérivées arithmétiques de la ressource, et le calage.

Rien d'optique ici : ni transposition au plan des modules, ni Perez. La
« transposition » du moteur est un rééchelonnage mensuel par ratios, pure
arithmétique. Ce module reproduit fidèlement les formules de la vue TypeScript
(``calage.ts``, ``ressource-v2.ts``, ``transposition.ts`` du moteur), validées
sur les valeurs contre le golden Tokounou.
"""

from __future__ import annotations

from typing import Any

# Jours par mois, année non bissextile (miroir de JOURS_PAR_MOIS du moteur).
JOURS_PAR_MOIS: tuple[int, ...] = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

# Tolérance du contrôle de cohérence de la HEP annuelle (moteur).
TOLERANCE_HEP_ANNUELLE = 0.01


class CalageIncompletError(ValueError):
    """Le calage ne couvre pas les 12 mois exactement une fois."""


def climatologie_source_hep(mois: list[int], ghi: list[float]) -> list[float]:
    """HEP source mensuelle (12 valeurs) dérivée de la séquence horaire.

    Pour chaque mois, la moyenne horaire du GHI x 24 / 1000, la HEP propre de
    la séquence brute (miroir de ``climatologieSourceDepuisSequence``).
    """
    sommes = [0.0] * 12
    comptes = [0] * 12
    for m, g in zip(mois, ghi, strict=True):
        if not 1 <= m <= 12:
            raise ValueError(f"mois hors bornes dans la séquence : {m}")
        sommes[m - 1] += g
        comptes[m - 1] += 1
    resultat: list[float] = []
    for i in range(12):
        if comptes[i] == 0:
            raise ValueError(f"aucun pas horaire pour le mois {i + 1}")
        resultat.append((sommes[i] / comptes[i]) * (24 / 1000))
    return resultat


def facteurs_calage(saisons: list[dict[str, Any]]) -> list[float]:
    """Facteur k de chaque mois (index 0 pour janvier), k = 1 / (1 + biais).

    Les saisons doivent couvrir les 12 mois exactement une fois (miroir de
    ``facteursCalageParMois``).
    """
    par_mois: list[float | None] = [None] * 12
    for saison in saisons:
        k = 1 / (1 + saison["biais"])
        for mois in saison["mois"]:
            if not 1 <= mois <= 12:
                raise CalageIncompletError(
                    f"mois hors bornes dans la saison {saison['nom']} : {mois}"
                )
            if par_mois[mois - 1] is not None:
                raise CalageIncompletError(f"mois {mois} couvert par plusieurs saisons")
            par_mois[mois - 1] = k
    for i, k in enumerate(par_mois):
        if k is None:
            raise CalageIncompletError(f"mois {i + 1} couvert par aucune saison")
    return [k for k in par_mois if k is not None]


def caler_climatologie(climatologie_hep: list[float], saisons: list[dict[str, Any]]) -> list[float]:
    """Climatologie calée : HEP_cal(m) = HEP_clim(m) x k_saison(m)."""
    if len(climatologie_hep) != 12:
        raise ValueError(f"12 valeurs mensuelles attendues, {len(climatologie_hep)} reçues")
    facteurs = facteurs_calage(saisons)
    return [hep * facteurs[i] for i, hep in enumerate(climatologie_hep)]


def hep_annuelle(climatologie_hep: list[float]) -> float:
    """HEP annuelle, moyenne des 12 mois **pondérée par les jours du mois**."""
    numerateur = sum(hep * JOURS_PAR_MOIS[i] for i, hep in enumerate(climatologie_hep))
    return numerateur / sum(JOURS_PAR_MOIS)


def hep_annuelle_reconstituee(
    climatologie_hep: list[float], saisons: list[dict[str, Any]] | None
) -> float:
    """HEP annuelle reconstituée : la HEP pondérée-jours de la climatologie calée.

    Sans calage (capsule brute), la climatologie brute fait foi. Le moteur ne
    l'utilise pas au dimensionnement ; il la **vérifie** (garde d'intégrité,
    ``TOLERANCE_HEP_ANNUELLE``).
    """
    calee = caler_climatologie(climatologie_hep, saisons) if saisons else climatologie_hep
    return hep_annuelle(calee)
