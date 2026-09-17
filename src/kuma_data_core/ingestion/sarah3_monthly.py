"""Ingestion PVGIS-SARAH3 ICDR mensuel -> ``mesures_ressource_mensuelles``.

Client + ingestion combinés pour le seul usage SARAH-3 ICDR courant.
Pendant SARAH-3 du module ``nasa_power_monthly.py``, ciblant la nouvelle
table ``mesures_ressource_mensuelles``.

API source : PVGIS non-interactive MRcalc (Monthly Radiation),
endpoint v5.3, Commission européenne JRC. Accès libre intégral sans
authentification (rate limit 30 req/s par IP, trivial pour 6 calls).

Endpoint : ``https://re.jrc.ec.europa.eu/api/v5_3/MRcalc``.

Paramètres :

- ``lat``, ``lon`` : coordonnées WGS84 en degrés décimaux.
- ``raddatabase=PVGIS-SARAH3`` : base de données SARAH-3 ICDR.
- ``startyear`` / ``endyear`` : bornes inclusives.
- ``horirrad=1`` : irradiation horizontale globale (GHI) requise.
- ``outputformat=json`` : format de réponse structuré (recommandé).

Structure de réponse JSON pressentie (validation empirique au premier
appel) :

```
{
  "inputs": {...},
  "outputs": {
    "monthly": [
      {"year": 2021, "month": 1, "H(h)_m": 179.97},
      ...
    ]
  },
  "meta": {...}
}
```

Champ ``H(h)_m`` : irradiation horizontale globale **cumulée mensuelle**
en kWh/m^2/mois (somme sur le mois entier, indice ``_m`` = pas de
temps monthly). Le pipeline convertit en kWh/m^2/jour (moyenne
quotidienne) par division par le nombre exact de jours du mois via
``calendar.monthrange`` pour aligner sur ``unite_code='kwh_par_m2_jour'``
des séries brutes Kuma et permettre la comparaison directe avec NASA
POWER. Validation empirique 2026-05 : ratio cumul-SARAH3 / cumul-NASA
≈ 1.02 à 1.09 (ordre de grandeur identique = cumul mensuel).

Variable d'environnement ``KUMA_SKIP_SARAH3_INGESTION`` (truthy) court-
circuite l'appel réseau (séries seedées, 0 mesure). Cohérence opérationnelle
CI avec ``KUMA_SKIP_NASA_POWER_INGESTION``.

Ingestion **live uniquement** dans cette instance : le repli offline sur
seed committé et son canari de dérive amont (patron de l'instance Guinée)
sont retirés tant qu'aucune donnée n'est versée pour la Côte d'Ivoire.
"""

from __future__ import annotations

import calendar
import os
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.editorial.niveaux_confiance import (
    calculer_niveau_confiance_derive,
)
from kuma_data_core.exceptions import (
    PvgisHttpError,
    PvgisRateLimitError,
    PvgisTimeoutError,
)
from kuma_data_core.external._http_retry import (
    HttpRetryHttpError,
    HttpRetryRateLimitError,
    HttpRetryTimeoutError,
    executer_get_avec_retry,
)

PVGIS_MRCALC_URL: str = "https://re.jrc.ec.europa.eu/api/v5_3/MRcalc"
"""URL endpoint PVGIS MRcalc (Monthly Radiation) v5.3.

Version v5.3 retenue (v5.2 était disponible en alternative, mais v5.3
est la plus récente et la legacy sans version est dépréciée depuis le
25 septembre 2024).
"""

PVGIS_RADDATABASE_SARAH3: str = "PVGIS-SARAH3"
"""Identifiant de la base de données SARAH-3 côté PVGIS.

Couverture : Europe, Afrique, Asie. Chaîne de retrieval MAGICSOL CM
SAF / EUMETSAT (Heliosat modifié + gnu-MAGIC + SPECMAGIC).
"""

DEFAULT_TIMEOUT: float = 30.0

_VARIABLE_ENV_SKIP_INGESTION: str = "KUMA_SKIP_SARAH3_INGESTION"
"""Variable d'environnement court-circuitant l'ingestion réseau.

Truthy values : '1', 'true', 'yes' (case-insensitive). Distincte de
KUMA_SKIP_NASA_POWER_INGESTION pour permettre de couper l'une sans
l'autre (utile lors de l'investigation d'un drift API ciblée sur une
source).
"""


def _ingestion_doit_etre_skip() -> bool:
    """Lit la variable d'environnement et retourne True si elle est truthy."""
    valeur = os.environ.get(_VARIABLE_ENV_SKIP_INGESTION, "").strip().lower()
    return valeur in ("1", "true", "yes")


def _fetch_sarah3_monthly_raw(
    *,
    latitude: float,
    longitude: float,
    annee_debut: int,
    annee_fin: int,
    timeout: float,
    httpx_client: httpx.Client | None,
) -> dict[str, Any]:
    """Appelle l'API PVGIS MRcalc et retourne le payload JSON brut.

    Args:
        latitude: latitude WGS84.
        longitude: longitude WGS84.
        annee_debut: première année incluse.
        annee_fin: dernière année incluse.
        timeout: timeout HTTP en secondes.
        httpx_client: client httpx injectable (tests via MockTransport).

    Returns:
        Le payload JSON brut (dict structuré ``inputs``/``outputs``/
        ``meta``).

    Raises:
        RuntimeError: statut HTTP non-2xx ou JSON non parsable.
    """
    query_params: dict[str, str] = {
        "lat": str(latitude),
        "lon": str(longitude),
        "raddatabase": PVGIS_RADDATABASE_SARAH3,
        "startyear": str(annee_debut),
        "endyear": str(annee_fin),
        "horirrad": "1",
        "outputformat": "json",
    }

    client_fourni = httpx_client is not None
    client = httpx_client if httpx_client is not None else httpx.Client(timeout=timeout)
    try:
        try:
            response = executer_get_avec_retry(
                client=client,
                url=PVGIS_MRCALC_URL,
                query_params=query_params,
                timeout=timeout,
            )
        except HttpRetryRateLimitError as exc:
            raise PvgisRateLimitError(
                status_code=exc.status_code,
                url=exc.url,
                body=exc.body,
            ) from exc
        except HttpRetryHttpError as exc:
            raise PvgisHttpError(
                status_code=exc.status_code,
                url=exc.url,
                body=exc.body,
            ) from exc
        except HttpRetryTimeoutError as exc:
            raise PvgisTimeoutError(
                url=exc.url,
                timeout_seconds=exc.timeout_seconds,
            ) from exc

        if response.status_code >= 400:
            raise PvgisHttpError(
                status_code=response.status_code,
                url=str(response.request.url),
                body=response.text,
            )
        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"PVGIS MRcalc reponse non parsable en JSON sur "
                f"lat={latitude}, lon={longitude}. Body: {response.text[:500]}"
            ) from exc
    finally:
        if not client_fourni:
            client.close()

    return payload


def _extraire_valeurs_mensuelles(
    payload: dict[str, Any],
) -> list[tuple[int, int, float]]:
    """Extrait les valeurs mensuelles ``(annee, mois, valeur)`` du payload PVGIS.

    Structure attendue :

    ```
    payload["outputs"]["monthly"] = [
        {"year": 2021, "month": 1, "H(h)_m": 179.97},
        ...
    ]
    ```

    Le champ ``H(h)_m`` représente l'irradiation horizontale globale
    **cumulée mensuelle** en kWh/m^2/mois (somme sur le mois entier).
    Cette fonction convertit en moyenne quotidienne kWh/m^2/jour par
    division par le nombre exact de jours du mois (``calendar.monthrange``,
    gère les années bissextiles), afin d'aligner sur l'``unite_code``
    ``'kwh_par_m2_jour'`` des séries Kuma et permettre la comparaison
    directe inter-source.

    Args:
        payload: payload JSON renvoyé par PVGIS MRcalc.

    Returns:
        Liste de tuples ``(annee, mois, valeur_kwh_par_m2_jour)``.

    Raises:
        RuntimeError: si la structure attendue est absente.
    """
    try:
        monthly = payload["outputs"]["monthly"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(
            f"PVGIS MRcalc payload ne contient pas outputs.monthly. "
            f"Cles racines : {list(payload.keys()) if isinstance(payload, dict) else type(payload)}"
        ) from exc

    if not isinstance(monthly, list):
        raise RuntimeError(f"PVGIS MRcalc outputs.monthly n'est pas une liste : {type(monthly)}")

    valeurs: list[tuple[int, int, float]] = []
    for entry in monthly:
        if not isinstance(entry, dict):
            continue
        annee = entry.get("year")
        mois = entry.get("month")
        cumul_mensuel = entry.get("H(h)_m")
        if annee is None or mois is None or cumul_mensuel is None:
            continue
        nombre_jours = calendar.monthrange(int(annee), int(mois))[1]
        valeur_quotidienne = float(cumul_mensuel) / nombre_jours
        valeurs.append((int(annee), int(mois), valeur_quotidienne))

    return valeurs


def ingerer_serie_sarah3_monthly(
    *,
    session: Session,
    code_serie: str,
    latitude: float,
    longitude: float,
    annee_debut: int,
    annee_fin: int,
    timeout: float = DEFAULT_TIMEOUT,
    httpx_client: httpx.Client | None = None,
) -> int:
    """Ingère une série SARAH-3 ICDR mensuelle dans ``mesures_ressource_mensuelles``.

    Args:
        session : session SQLAlchemy active.
        code_serie : code naturel de la série dans ``series_metadonnees``
            (ex. ``gin_conakry_ghi_sarah3_2021_2025``). Doit exister.
        latitude, longitude : coordonnées WGS84.
        annee_debut, annee_fin : bornes inclusives (ex. 2021 / 2025).
        timeout : timeout HTTP en secondes.
        httpx_client : client httpx injectable.

    Returns:
        Nombre de lignes effectivement insérées.

        Retourne ``0`` si la variable d'env
        ``KUMA_SKIP_SARAH3_INGESTION`` est truthy.

    Raises:
        RuntimeError : si ``code_serie`` n'existe pas ou si la réponse
            API est mal formée.
    """
    if _ingestion_doit_etre_skip():
        return 0

    row = session.execute(
        text(
            """
            SELECT
                sm.id AS serie_id,
                sm.methode_collecte,
                s.fiabilite AS fiabilite_source
            FROM series_metadonnees sm
            JOIN sources s ON s.id = sm.source_id
            WHERE sm.code = :code
            """
        ),
        {"code": code_serie},
    ).first()
    if row is None:
        raise RuntimeError(
            f"Serie {code_serie!r} introuvable dans series_metadonnees. "
            f"Verifier que la migration de seed 1-7a a bien ete appliquee."
        )

    serie_id: int = int(row.serie_id)
    methode_collecte: str | None = row.methode_collecte
    fiabilite_source: str | None = row.fiabilite_source

    niveau_derive = calculer_niveau_confiance_derive(
        methode_collecte=methode_collecte,
        fiabilite_source=fiabilite_source,
    )

    payload = _fetch_sarah3_monthly_raw(
        latitude=latitude,
        longitude=longitude,
        annee_debut=annee_debut,
        annee_fin=annee_fin,
        timeout=timeout,
        httpx_client=httpx_client,
    )
    valeurs_mensuelles = _extraire_valeurs_mensuelles(payload)

    if not valeurs_mensuelles:
        return 0

    lignes_a_inserer: list[dict[str, object]] = [
        {
            "serie_id": serie_id,
            "annee": annee,
            "mois": mois,
            "valeur": valeur,
            "niveau_confiance_derive": niveau_derive,
        }
        for annee, mois, valeur in valeurs_mensuelles
    ]

    session.execute(
        text(
            """
            INSERT INTO mesures_ressource_mensuelles
                (serie_id, annee, mois, valeur, niveau_confiance_derive)
            VALUES
                (:serie_id, :annee, :mois, :valeur, :niveau_confiance_derive)
            """
        ),
        lignes_a_inserer,
    )
    session.flush()
    return len(lignes_a_inserer)
