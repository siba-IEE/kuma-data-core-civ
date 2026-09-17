"""Helpers de conversion passe-plat horaire.

Logique de transformation des réponses du client externe
(``external.nasa_power.fetch_hourly``) vers le format Kuma cohérent
(:class:`api.v1.schemas.horaire.ResultatHoraire`).

Trois conversions :

- Clés temporelles ``YYYYMMDDHH`` -> ``datetime`` ISO 8601 (fuseau UTC,
  naïf).
- Sentinelles ``-999.0`` -> ``None`` (uniforme : nocturne / NRT
  indisponible / autre).
- Mapping ``grandeur_code`` Kuma <-> code paramètre amont +
  détermination unité cible.

La logique de conversion est interne au projet ; le mapping vers les
codes de la source amont n'est pas exposé au consommateur final.
"""

from __future__ import annotations

from datetime import date, datetime

from kuma_data_core.api.v1.schemas.horaire import ResultatHoraire
from kuma_data_core.external.nasa_power import SENTINELLE_VALEUR_MANQUANTE

# === Mapping grandeur Kuma -> (code amont, unité cible) ===================

_MAPPING_GRANDEUR: dict[str, tuple[str, str]] = {
    "ghi": ("ALLSKY_SFC_SW_DWN", "Wh/m²"),
    "dni": ("ALLSKY_SFC_SW_DNI", "Wh/m²"),
    "dhi": ("ALLSKY_SFC_SW_DIFF", "Wh/m²"),
    "t2m": ("T2M", "°C"),
    "rh2m": ("RH2M", "%"),
    "kt": ("ALLSKY_KT", "sans dimension"),
    "vent_2m": ("WS2M", "m/s"),
    "vent_10m": ("WS10M", "m/s"),
    "precipitation": ("PRECTOTCORR", "mm/h"),
}
"""Mapping interne : grandeur Kuma -> (code amont, unité cible Kuma).

Interne au projet, ne fuite pas au consommateur. Les unités cible
reflètent la convention horaire (par exemple Wh/m² pour les
irradiances horaires, vs kWh/m²/jour pour le daily existant).
"""


# === Helpers publics ======================================================


def code_parametre_amont(grandeur: str) -> str:
    """Renvoie le code paramètre amont pour une grandeur Kuma.

    Raises:
        KeyError : si ``grandeur`` n'est pas dans le mapping (contrôlé
            par Pydantic Literal en amont).
    """
    return _MAPPING_GRANDEUR[grandeur][0]


def unite_cible(grandeur: str) -> str:
    """Renvoie l'unité cible Kuma pour une grandeur horaire."""
    return _MAPPING_GRANDEUR[grandeur][1]


def parser_cle_horaire(cle: str) -> datetime:
    """Parse une clé horaire amont ``YYYYMMDDHH`` en ``datetime`` (UTC naïf).

    Args:
        cle : chaîne de 10 caractères au format ``YYYYMMDDHH``
            (ex. ``"2024060112"`` = 2024-06-01 12:00 UTC).

    Returns:
        ``datetime`` naïf (fuseau UTC implicite, pas de tzinfo).

    Raises:
        ValueError : si ``cle`` ne respecte pas le format attendu.
    """
    if len(cle) != 10 or not cle.isdigit():
        raise ValueError(f"cle horaire invalide : {cle!r} (attendu YYYYMMDDHH 10 chiffres)")
    return datetime(
        year=int(cle[0:4]),
        month=int(cle[4:6]),
        day=int(cle[6:8]),
        hour=int(cle[8:10]),
    )


def convertir_valeurs_amont_en_resultats(
    valeurs_par_cle: dict[str, float],
    grandeur: str,
) -> list[ResultatHoraire]:
    """Convertit le dict ``{YYYYMMDDHH: float}`` amont en liste ResultatHoraire.

    Applique uniformément :

    - Clés ``YYYYMMDDHH`` -> ``datetime`` (UTC naïf).
    - Sentinelle ``-999.0`` -> ``None`` (uniforme : pas de
      différenciation nocturne / NRT / autre en v1).
    - Unité cible dérivée du mapping interne.
    - Statut éditorial uniforme ``passe_plat_non_valide``.

    Les résultats sont triés chronologiquement par ``instant``.
    """
    unite = unite_cible(grandeur)
    resultats: list[ResultatHoraire] = []
    for cle in sorted(valeurs_par_cle):
        instant = parser_cle_horaire(cle)
        valeur_amont = valeurs_par_cle[cle]
        valeur: float | None = None if valeur_amont == SENTINELLE_VALEUR_MANQUANTE else valeur_amont
        resultats.append(
            ResultatHoraire(
                instant=instant,
                valeur=valeur,
                unite=unite,
            )
        )
    return resultats


def filtrer_resultats_par_plage(
    resultats: list[ResultatHoraire],
    periode_debut: date,
    periode_fin: date,
) -> list[ResultatHoraire]:
    """Filtre les résultats horaires sur la fenêtre [periode_debut, periode_fin].

    La borne haute est inclusive sur le jour entier (jusqu'à 23h59 du
    ``periode_fin``).
    """
    return [r for r in resultats if periode_debut <= r.instant.date() <= periode_fin]
