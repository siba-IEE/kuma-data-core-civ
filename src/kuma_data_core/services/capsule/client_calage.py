"""Client serveur à serveur du service de calage (kuma-calage).

En mode EN LIGNE, l'émetteur de capsule appelle kuma-calage pour un point et en
extrait le référentiel de calage (les saisons et leurs biais) à cuire dans la
ressource. La loi ne sort jamais de kuma-calage ; seuls ses résultats (les
facteurs par saison) entrent dans la capsule, et seulement en ligne.

Le jeton dédié voyage en Bearer, l'appel se fait sous TLS en production. Ce
module ne fait que l'appel et l'extraction ; l'orchestration décide quand
l'appeler (jamais pour une capsule brute).
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any


class CalageIndisponibleError(RuntimeError):
    """kuma-calage n'a pas répondu, ou a refusé le jeton."""


def couverture(
    base_url: str, jeton: str, lat: float, lon: float, *, timeout: float = 10.0
) -> dict[str, Any]:
    """Appelle ``GET /couverture?lat&lon`` de kuma-calage et rend la réponse."""
    url = f"{base_url.rstrip('/')}/couverture?lat={lat}&lon={lon}"
    requete = urllib.request.Request(url, headers={"Authorization": f"Bearer {jeton}"})
    try:
        with urllib.request.urlopen(requete, timeout=timeout) as reponse:
            resultat: dict[str, Any] = json.load(reponse)
            return resultat
    except Exception as e:
        # Toute panne réseau ou HTTP devient une indisponibilité portée.
        raise CalageIndisponibleError(f"kuma-calage injoignable : {e}") from e


def referentiel_calage(reponse_couverture: dict[str, Any]) -> dict[str, Any]:
    """Extrait le référentiel de calage (saisons et biais) de la réponse.

    C'est le seul morceau du calage qui entre dans la ressource : les saisons du
    GHI et leur biais, la forme que le moteur applique à la climatologie. Ni la
    loi, ni les résidus, ni le verdict de couverture ne descendent ici.
    """
    ghi = reponse_couverture.get("ghi")
    if not isinstance(ghi, dict) or "saisons" not in ghi:
        raise CalageIndisponibleError("réponse kuma-calage sans saisons de calage")
    return {"saisons": ghi["saisons"]}
