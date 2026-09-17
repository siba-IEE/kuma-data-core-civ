"""Contrôle qualité algorithmique des séries horaires.

Implémente le socle BSRN (§4.1-§4.3), seuils sourcés verbatim de
*BSRN Global Network recommended QC tests V2.0* (Long & Dutton). Les
tests d'aberration temporelle (§4.4, hors jeu BSRN canonique) sont
différés.

Deux niveaux :

- **Fonctions pures** (sans I/O ni pvlib) : les tests BSRN, qui
  prennent en entrée la géométrie solaire déjà calculée (μ₀, SZA, Sₐ).
- **Runner** ``executer_qc_horaire`` : lit les lignes horaires d'un jeu
  de séries, calcule la géométrie solaire via ``pvlib`` (UTC), applique
  les tests et renvoie un verdict par ligne. Le commit est au caller.

Doctrine d'attribution (§5) :

- Échec d'un seuil **« physiquement impossible »** (test dur) → ligne
  **non validée** : statut conservé ``brut`` + trace en
  ``commentaire_editorial``.
- Sinon → ``valide_auto``, niveau ``B``. Les échecs **« souples »**
  (seuil « extrêmement rare », fermeture, ratio diffus) sont **flaggés**
  en commentaire sans déclasser (la valeur reste plausible-mais-suspecte).

Référence : Long C.N., Dutton E.G., *BSRN Global Network recommended QC
tests V2.0* ; constante solaire S₀ = 1366,1 W/m² (défaut pvlib
``get_extra_radiation``).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

import pandas as pd  # type: ignore[import-untyped]
import pvlib  # type: ignore[import-untyped]
from sqlalchemy import text
from sqlalchemy.orm import Session

VERSION_DOCTRINE_QC: str = "v1"
"""Version de la doctrine QC appliquée (tracée par ligne et au log batch)."""

S0_W_PAR_M2: float = 1366.1
"""Constante solaire à distance moyenne (W/m²), défaut pvlib.

Sₐ = S₀ / AU² (ajustée distance Terre-Soleil) est calculée par le runner
via ``pvlib.irradiance.get_extra_radiation`` ; cette constante documente
la valeur de base S₀ retenue."""

# Grandeurs radiatives shortwave soumises aux bornes BSRN + tests croisés.
_GRANDEURS_RADIATIVES: frozenset[str] = frozenset({"ghi", "dhi", "dni"})

VerdictPlausibilite = Literal["ok", "rare", "impossible"]


# === Plausibilité physique par variable (BSRN §4.1) =======================


def _borne_haute_ghi(sa: float, mu0: float, *, rare: bool) -> float:
    """Borne haute GHI : Sₐ·1,5·μ₀^1.2 + 100 (possible) / Sₐ·1,2·μ₀^1.2 + 50 (rare)."""
    if rare:
        return sa * 1.2 * math.pow(mu0, 1.2) + 50.0
    return sa * 1.5 * math.pow(mu0, 1.2) + 100.0


def _borne_haute_dhi(sa: float, mu0: float, *, rare: bool) -> float:
    """Borne haute DHI : Sₐ·0,95·μ₀^1.2 + 50 (possible) / Sₐ·0,75·μ₀^1.2 + 30 (rare)."""
    if rare:
        return sa * 0.75 * math.pow(mu0, 1.2) + 30.0
    return sa * 0.95 * math.pow(mu0, 1.2) + 50.0


def _borne_haute_dni(sa: float, mu0: float, *, rare: bool) -> float:
    """Borne haute DNI : Sₐ (possible) / Sₐ·0,95·μ₀^0.2 + 10 (rare)."""
    if rare:
        return sa * 0.95 * math.pow(mu0, 0.2) + 10.0
    return sa


def plausibilite_radiative(
    grandeur: str, valeur: float, sa: float, mu0: float
) -> VerdictPlausibilite:
    """Verdict de plausibilité BSRN d'une grandeur radiative (ghi/dhi/dni).

    Renvoie ``"impossible"`` si hors borne physiquement possible (rejet),
    ``"rare"`` si dans le possible mais hors extrêmement rare (flag),
    ``"ok"`` sinon. μ₀ = 0 la nuit réduit les bornes hautes à l'offset.
    """
    min_possible, min_rare = -4.0, -2.0
    if grandeur == "ghi":
        max_possible = _borne_haute_ghi(sa, mu0, rare=False)
        max_rare = _borne_haute_ghi(sa, mu0, rare=True)
    elif grandeur == "dhi":
        max_possible = _borne_haute_dhi(sa, mu0, rare=False)
        max_rare = _borne_haute_dhi(sa, mu0, rare=True)
    elif grandeur == "dni":
        max_possible = _borne_haute_dni(sa, mu0, rare=False)
        max_rare = _borne_haute_dni(sa, mu0, rare=True)
    else:  # pragma: no cover - garde-fou
        raise ValueError(f"Grandeur radiative inconnue : {grandeur!r}")

    if valeur < min_possible or valeur > max_possible:
        return "impossible"
    if valeur < min_rare or valeur > max_rare:
        return "rare"
    return "ok"


def plausibilite_non_radiative(grandeur: str, valeur: float) -> VerdictPlausibilite:
    """Verdict de plausibilité des variables non radiatives (t2m, rh2m, kt).

    Bornes physiques larges (non BSRN-shortwave) : RH2M ∈ [0, 100] %,
    T2M ∈ [-90, 60] °C, KT ∈ [0, 1] (marge d'enhancement à 1,2). Hors
    borne → ``"impossible"``. Pas de niveau « rare » distinct ici.
    """
    if grandeur == "rh2m":
        return "ok" if 0.0 <= valeur <= 100.0 else "impossible"
    if grandeur == "t2m":
        return "ok" if -90.0 <= valeur <= 60.0 else "impossible"
    if grandeur == "kt":
        return "ok" if 0.0 <= valeur <= 1.2 else "impossible"
    return "ok"


# === Tests de cohérence croisée (BSRN §4.2-§4.3) ==========================


def tolerance_fermeture(sza_deg: float) -> float | None:
    """Tolérance du test de fermeture par bande de zénith (BSRN).

    ±8 % pour SZA < 75°, ±15 % pour 75° ≤ SZA < 93°, non applicable
    au-delà (renvoie ``None``).
    """
    if sza_deg < 75.0:
        return 0.08
    if sza_deg < 93.0:
        return 0.15
    return None


def fermeture_ok(ghi: float, dhi: float, dni: float, mu0: float, sza_deg: float) -> bool | None:
    """Test de fermeture BSRN : Global / (DHI + DNI·μ₀) à ±tol de 1,0.

    Renvoie ``None`` si non applicable (Sum SW ≤ 50 W/m² ou SZA ≥ 93°),
    ``True`` si cohérent, ``False`` si hors tolérance.
    """
    sum_sw = dhi + dni * mu0
    if sum_sw <= 50.0:
        return None
    tol = tolerance_fermeture(sza_deg)
    if tol is None:
        return None
    return abs(ghi / sum_sw - 1.0) <= tol


def ratio_diffus_ok(dhi: float, ghi: float, sza_deg: float) -> bool | None:
    """Test du ratio diffus BSRN : DHI / GHI < 1,05 (SZA<75°) / 1,10 (75-93°).

    Renvoie ``None`` si non applicable (GHI ≤ 50 W/m² ou SZA ≥ 93°).
    """
    if ghi <= 50.0:
        return None
    if sza_deg < 75.0:
        seuil = 1.05
    elif sza_deg < 93.0:
        seuil = 1.10
    else:
        return None
    return (dhi / ghi) < seuil


# === Verdict par ligne ====================================================


@dataclass(frozen=True)
class VerdictLigne:
    """Verdict QC d'une ligne horaire (résultat du runner)."""

    row_id: int
    statut_cible: str  # "valide_auto" (validée) ou "brut" (rejetée)
    niveau: str  # "B" uniforme (le QC ne crée pas de A)
    flags: tuple[str, ...] = field(default_factory=tuple)  # échecs souples tracés
    motif_rejet: str | None = None  # test dur échoué si statut_cible == "brut"

    def commentaire(self) -> str:
        """Commentaire éditorial à inscrire (tracé doctrine + verdict)."""
        if self.motif_rejet is not None:
            return f"[QC {VERSION_DOCTRINE_QC}] rejet : {self.motif_rejet}"
        if self.flags:
            return f"[QC {VERSION_DOCTRINE_QC}] valide_auto ; flags : {', '.join(self.flags)}"
        return f"[QC {VERSION_DOCTRINE_QC}] valide_auto"


@dataclass(frozen=True)
class MesureHoraire:
    """Une ligne horaire à évaluer (entrée du runner, par instant)."""

    row_id: int
    grandeur: str  # ghi / dhi / dni / t2m / rh2m / kt
    valeur: float


def evaluer_instant(
    mesures: Sequence[MesureHoraire],
    sa: float,
    mu0: float,
    sza_deg: float,
) -> list[VerdictLigne]:
    """Évalue toutes les lignes d'un même instant (géométrie solaire fournie).

    Applique la plausibilité par variable, puis les tests croisés
    (fermeture, ratio diffus) sur les composantes radiatives présentes.
    Renvoie un :class:`VerdictLigne` par ligne d'entrée.
    """
    par_grandeur: dict[str, MesureHoraire] = {m.grandeur: m for m in mesures}

    # Tests croisés (une fois par instant, si les 3 radiatives sont là).
    ferm: bool | None = None
    ratio: bool | None = None
    if {"ghi", "dhi", "dni"} <= par_grandeur.keys():
        ghi = par_grandeur["ghi"].valeur
        dhi = par_grandeur["dhi"].valeur
        dni = par_grandeur["dni"].valeur
        ferm = fermeture_ok(ghi, dhi, dni, mu0, sza_deg)
        ratio = ratio_diffus_ok(dhi, ghi, sza_deg)

    verdicts: list[VerdictLigne] = []
    for m in mesures:
        if m.grandeur in _GRANDEURS_RADIATIVES:
            plaus = plausibilite_radiative(m.grandeur, m.valeur, sa, mu0)
        else:
            plaus = plausibilite_non_radiative(m.grandeur, m.valeur)

        if plaus == "impossible":
            verdicts.append(
                VerdictLigne(
                    row_id=m.row_id,
                    statut_cible="brut",
                    niveau="B",
                    motif_rejet=f"plausibilite {m.grandeur} hors borne physique",
                )
            )
            continue

        flags: list[str] = []
        if plaus == "rare":
            flags.append(f"{m.grandeur} extremement rare")
        # Les échecs de fermeture / ratio flaggent les radiatives impliquées.
        if m.grandeur in _GRANDEURS_RADIATIVES and ferm is False:
            flags.append("fermeture hors tolerance")
        if m.grandeur == "dhi" and ratio is False:
            flags.append("ratio diffus eleve")

        verdicts.append(
            VerdictLigne(
                row_id=m.row_id,
                statut_cible="valide_auto",
                niveau="B",
                flags=tuple(flags),
            )
        )
    return verdicts


# === Runner (pvlib + SQL) =================================================


def executer_qc_horaire(
    session: Session,
    serie_ids_par_grandeur: dict[str, int],
    latitude: float,
    longitude: float,
) -> list[VerdictLigne]:
    """Applique le QC BSRN aux lignes horaires courantes d'un jeu de séries.

    Lit les lignes ``valide_au IS NULL`` des séries fournies, calcule la
    géométrie solaire (``pvlib``, UTC) par instant, applique
    :func:`evaluer_instant`, et renvoie un verdict par ligne. **Sans
    effet de bord SQL** : le caller (migration) applique les verdicts.

    Args:
        session : session SQLAlchemy active.
        serie_ids_par_grandeur : mapping ``{grandeur: serie_id}`` des
            séries horaires à évaluer (ex. ``{"ghi": 421, ...}``).
        latitude, longitude : coordonnées WGS84 de la localité (UTC pour
            la position solaire).

    Returns:
        Liste de :class:`VerdictLigne`, un par ligne horaire courante.
        Liste vide si aucune ligne.
    """
    grandeur_par_serie = {sid: g for g, sid in serie_ids_par_grandeur.items()}
    rows = session.execute(
        text(
            """
            SELECT id, serie_id, instant_mesure, valeur
            FROM mesures_ressource_horaires
            WHERE serie_id = ANY(:ids) AND valide_au IS NULL
            ORDER BY instant_mesure
            """
        ),
        {"ids": list(serie_ids_par_grandeur.values())},
    ).all()
    if not rows:
        return []

    mesures_par_instant: dict[datetime, list[MesureHoraire]] = {}
    for r in rows:
        instant = r.instant_mesure.astimezone(UTC)
        grandeur = grandeur_par_serie[int(r.serie_id)]
        mesures_par_instant.setdefault(instant, []).append(
            MesureHoraire(row_id=int(r.id), grandeur=grandeur, valeur=float(r.valeur))
        )

    # Géométrie solaire vectorisée sur les instants uniques (UTC).
    instants = sorted(mesures_par_instant)
    times = pd.DatetimeIndex(instants)
    zenith_values = pvlib.solarposition.get_solarposition(times, latitude, longitude)[
        "zenith"
    ].to_numpy()
    sa_values = pvlib.irradiance.get_extra_radiation(times, solar_constant=S0_W_PAR_M2).to_numpy()

    verdicts: list[VerdictLigne] = []
    for i, instant in enumerate(instants):
        sza_deg = float(zenith_values[i])
        mu0 = max(0.0, math.cos(math.radians(sza_deg)))
        sa = float(sa_values[i])
        verdicts.extend(evaluer_instant(mesures_par_instant[instant], sa, mu0, sza_deg))
    return verdicts
