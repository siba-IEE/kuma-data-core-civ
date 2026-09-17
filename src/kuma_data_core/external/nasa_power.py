"""Client HTTP synchrone pour l'API NASA POWER.

Fournit les fonctions ``fetch_daily`` et ``fetch_hourly`` retournant
des objets pydantic typés ``NasaPowerResponse``. Conçu pour réutilisation
directe par l'ingestion persistée Conakry GHI - pas de réécriture
prévue.

Endpoints utilisés (communauté Renewable Energy par défaut) :

- Daily  : https://power.larc.nasa.gov/api/temporal/daily/point
- Hourly : https://power.larc.nasa.gov/api/temporal/hourly/point

Limites paramètres NASA POWER (cf. doc officielle) : 20 max sur daily,
15 max sur hourly. Pas de garde-fou applicatif - sera ajouté
si besoin observé.

Sentinelle valeur manquante : ``-999.0`` (header NASA POWER
``fill_value``). Le client expose cette valeur comme constante
``SENTINELLE_VALEUR_MANQUANTE`` et fournit l'utilitaire
``calculer_indice_ciel_clair`` qui la respecte.

Gestion d'erreurs (cf. ``kuma_data_core.exceptions``) :

- HTTP non-2xx : ``NasaPowerHttpError`` (+ sous-type
  ``NasaPowerRateLimitError`` pour 429).
- Payload JSON invalide ou non conforme schéma pydantic :
  ``NasaPowerPayloadError``.
- Timeout réseau : ``NasaPowerTimeoutError``.

Le comportement rate limit a été observé empiriquement ; aucun retry
automatique n'est implémenté dans ce client.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from kuma_data_core.exceptions import (
    NasaPowerHttpError,
    NasaPowerPayloadError,
    NasaPowerRateLimitError,
    NasaPowerTimeoutError,
)
from kuma_data_core.external._http_retry import (
    RETRY_BACKOFF_SECONDES,
    HttpRetryHttpError,
    HttpRetryRateLimitError,
    HttpRetryTimeoutError,
    executer_get_avec_retry,
)

# === Constantes ============================================================

BASE_URL: str = "https://power.larc.nasa.gov/api/temporal"
"""URL racine de l'API NASA POWER. Les endpoints daily/hourly/monthly
sont des sous-chemins."""

DEFAULT_COMMUNITY: str = "RE"
"""Communauté NASA POWER par défaut : Renewable Energy. Cohérent avec
le focus solaire."""

DEFAULT_TIMEOUT: float = 30.0
"""Timeout HTTP par défaut (latence P95 < 30 s)."""

SENTINELLE_VALEUR_MANQUANTE: float = -999.0
"""Valeur sentinelle utilisée par NASA POWER pour les données
manquantes (cf. header ``fill_value`` de la réponse)."""

# Note : le retry vit canoniquement dans ``external/_http_retry.py`` ;
# le wrapper local ``_executer_get_avec_retry`` ci-dessous ne fait que
# le brancher au défaut ``RETRY_BACKOFF_SECONDES``.


# === Schémas pydantic ======================================================


class _ConfigPermissive:
    """Configuration pydantic permissive : ignore les champs inattendus du payload."""

    model_config = ConfigDict(extra="ignore")


class NasaPowerGeometry(_ConfigPermissive, BaseModel):
    type: Literal["Point"]
    coordinates: tuple[float, float, float]


class NasaPowerApiInfo(_ConfigPermissive, BaseModel):
    version: str
    name: str


class NasaPowerHeader(_ConfigPermissive, BaseModel):
    """En-tête de la réponse NASA POWER.

    ``sources`` peut être absent ou de structure variable selon
    l'endpoint ; typage souple en ``list[str | dict[str, str]] | None``.
    """

    title: str
    api: NasaPowerApiInfo
    fill_value: float
    time_standard: str | None = None
    start: str
    end: str
    sources: list[str | dict[str, str]] | None = None


class NasaPowerParameterMeta(_ConfigPermissive, BaseModel):
    units: str
    longname: str


class NasaPowerProperties(_ConfigPermissive, BaseModel):
    """Conteneur des valeurs temporelles par paramètre.

    Structure : ``{nom_parametre: {clé_date: valeur}}``.

    - Clé date pour daily : ``"YYYYMMDD"``.
    - Clé date pour hourly : ``"YYYYMMDDHH"``.
    - Valeurs : ``float``. La sentinelle ``-999.0`` indique une donnée
      manquante (cf. ``SENTINELLE_VALEUR_MANQUANTE``).
    """

    parameter: dict[str, dict[str, float]]


class NasaPowerResponse(_ConfigPermissive, BaseModel):
    """Réponse complète NASA POWER (GeoJSON Feature enrichi)."""

    type: Literal["Feature"]
    geometry: NasaPowerGeometry
    properties: NasaPowerProperties
    header: NasaPowerHeader
    parameters: dict[str, NasaPowerParameterMeta]
    messages: list[str] = Field(default_factory=list)


# === Utilitaires ==========================================================


def calculer_indice_ciel_clair(
    allsky: float,
    clrsky: float,
    *,
    sentinelle: float = SENTINELLE_VALEUR_MANQUANTE,
) -> float | None:
    """Calcule l'indice de ciel clair ``K = ALLSKY / CLRSKY``.

    Indicateur de masquage nuageux : ``K = 1`` indique un ciel
    parfaitement clair, ``K = 0`` un masquage total. Sert également
    à détecter les anomalies ``GHI > CLRSKY`` (valeurs ``K > 1``,
    physiquement attendues uniquement en cas d'effet d'enhancement
    nuageux ponctuel et marginal).

    Retourne ``None`` si l'une des deux valeurs est la sentinelle
    NASA POWER ou si ``clrsky`` est nul (évite la division par zéro).

    Ne confond pas avec l'indice de clarté ``Kt = GHI / I_0_extraterrestre``
    qui est demandable directement à NASA POWER via le paramètre
    ``ALLSKY_KT``.
    """
    if allsky == sentinelle or clrsky == sentinelle:
        return None
    if clrsky == 0.0:
        return None
    return allsky / clrsky


# === Fonctions de fetch ====================================================


def _format_date_yyyymmdd(d: date) -> str:
    """Formate une date au format ``YYYYMMDD`` (paramètres ``start``/``end``)."""
    return d.strftime("%Y%m%d")


def _construire_url_et_params(
    *,
    endpoint: str,
    latitude: float,
    longitude: float,
    parameters: Sequence[str],
    start_str: str,
    end_str: str,
    community: str,
    time_standard: str | None = None,
) -> tuple[str, dict[str, str]]:
    """Construit l'URL complète et les query params pour un appel NASA POWER."""
    url = f"{BASE_URL}/{endpoint}/point"
    query_params: dict[str, str] = {
        "parameters": ",".join(parameters),
        "community": community,
        "latitude": str(latitude),
        "longitude": str(longitude),
        "start": start_str,
        "end": end_str,
        "format": "JSON",
    }
    if time_standard is not None:
        query_params["time-standard"] = time_standard
    return url, query_params


def _executer_get_avec_retry(
    *,
    client: httpx.Client,
    url: str,
    query_params: dict[str, str],
    timeout: float,
    retry_backoff_seconds: tuple[float, ...] = RETRY_BACKOFF_SECONDES,
) -> httpx.Response:
    """Wrapper local sur le helper partagé ``external/_http_retry.py``.

    Rôle : rétrocompat tests (les tests T-RETRY importent ce symbole depuis
    ce module) + conversion aux frontières des exceptions génériques
    ``HttpRetry*Error`` vers les exceptions NASA POWER via ``raise ... from exc``.
    """
    try:
        return executer_get_avec_retry(
            client=client,
            url=url,
            query_params=query_params,
            timeout=timeout,
            retry_backoff_seconds=retry_backoff_seconds,
        )
    except HttpRetryRateLimitError as exc:
        raise NasaPowerRateLimitError(
            status_code=exc.status_code,
            url=exc.url,
            body=exc.body,
        ) from exc
    except HttpRetryHttpError as exc:
        raise NasaPowerHttpError(
            status_code=exc.status_code,
            url=exc.url,
            body=exc.body,
        ) from exc
    except HttpRetryTimeoutError as exc:
        raise NasaPowerTimeoutError(
            url=exc.url,
            timeout_seconds=exc.timeout_seconds,
        ) from exc


def _fetch_payload_brut(
    *,
    url: str,
    query_params: dict[str, str],
    timeout: float,
    httpx_client: httpx.Client | None,
) -> dict[str, Any]:
    """Exécute l'appel HTTP NASA POWER (avec retry) et renvoie le payload JSON brut.

    Étape « fetch » isolée de :func:`_executer_requete` (avant parsing Pydantic),
    pour exposer le payload **brut** au seam offline-seed
    (cf. ``ingestion/nasa_power_daily.py``). Le parsing est délégué à
    :func:`parser_reponse_nasa`.

    Délègue le retry sur 429/503/timeout à ``_executer_get_avec_retry``, puis
    gère localement les statuts >= 400 terminaux et le ``response.json()``.

    Toutes les erreurs sont remontées comme sous-types de ``NasaPowerError``.
    """
    client_fourni = httpx_client is not None
    client = httpx_client if httpx_client is not None else httpx.Client(timeout=timeout)
    try:
        response = _executer_get_avec_retry(
            client=client,
            url=url,
            query_params=query_params,
            timeout=timeout,
        )

        url_complete = str(response.request.url)

        if response.status_code >= 400:
            raise NasaPowerHttpError(
                status_code=response.status_code, url=url_complete, body=response.text
            )

        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            raise NasaPowerPayloadError(
                message="Réponse non parsable en JSON",
                url=url_complete,
                body=response.text,
            ) from exc

        return payload
    finally:
        if not client_fourni:
            client.close()


def parser_reponse_nasa(payload: dict[str, Any], *, url: str = "") -> NasaPowerResponse:
    """Parse et valide un payload JSON NASA POWER en ``NasaPowerResponse``.

    Étape « parse » isolée de :func:`_executer_requete`, appliquée uniformément
    aux deux chemins du seam offline-seed (live et seed committé) : le payload
    committé est re-validé par le **même schéma** → fidélité, parsing exercé en
    CI. ``url`` n'est utilisé que pour enrichir le message d'erreur.
    """
    try:
        return NasaPowerResponse.model_validate(payload)
    except ValidationError as exc:
        raise NasaPowerPayloadError(
            message=f"Payload ne respecte pas le schéma NasaPowerResponse : {exc}",
            url=url,
            body=str(payload)[:500],
        ) from exc


def _executer_requete(
    *,
    url: str,
    query_params: dict[str, str],
    timeout: float,
    httpx_client: httpx.Client | None,
) -> NasaPowerResponse:
    """Exécute l'appel HTTP avec retry transverse puis parse la réponse.

    Composition de :func:`_fetch_payload_brut` (fetch) et
    :func:`parser_reponse_nasa` (parse). Comportement inchangé : si
    ``httpx_client`` est fourni (tests ``httpx.MockTransport``), il est utilisé
    tel quel ; sinon un client temporaire est créé. Toutes les erreurs sont
    remontées comme sous-types de ``NasaPowerError``.
    """
    payload = _fetch_payload_brut(
        url=url, query_params=query_params, timeout=timeout, httpx_client=httpx_client
    )
    return parser_reponse_nasa(payload, url=url)


def fetch_daily(
    *,
    latitude: float,
    longitude: float,
    parameters: Sequence[str],
    start: date,
    end: date,
    community: str = DEFAULT_COMMUNITY,
    timeout: float = DEFAULT_TIMEOUT,
    httpx_client: httpx.Client | None = None,
) -> NasaPowerResponse:
    """Récupère des séries journalières NASA POWER pour un point.

    Args:
        latitude: latitude WGS84 en degrés décimaux (positif Nord).
        longitude: longitude WGS84 en degrés décimaux (positif Est).
        parameters: codes NASA POWER à demander (max 20 selon doc).
        start: date de début (incluse).
        end: date de fin (incluse).
        community: communauté NASA POWER (``RE`` par défaut).
        timeout: timeout HTTP en secondes.
        httpx_client: client httpx injectable (utilisé en tests avec
            ``httpx.MockTransport``). Si ``None``, un client temporaire
            est créé.

    Returns:
        ``NasaPowerResponse`` parsé et validé.

    Raises:
        NasaPowerTimeoutError: timeout réseau.
        NasaPowerRateLimitError: HTTP 429.
        NasaPowerHttpError: autre HTTP non-2xx.
        NasaPowerPayloadError: JSON invalide ou non conforme schéma.
    """
    url, query_params = _construire_url_et_params(
        endpoint="daily",
        latitude=latitude,
        longitude=longitude,
        parameters=parameters,
        start_str=_format_date_yyyymmdd(start),
        end_str=_format_date_yyyymmdd(end),
        community=community,
    )
    return _executer_requete(
        url=url, query_params=query_params, timeout=timeout, httpx_client=httpx_client
    )


def fetch_daily_raw(
    *,
    latitude: float,
    longitude: float,
    parameters: Sequence[str],
    start: date,
    end: date,
    community: str = DEFAULT_COMMUNITY,
    timeout: float = DEFAULT_TIMEOUT,
    httpx_client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Récupère le payload JSON **brut** des séries journalières NASA POWER.

    Identique à :func:`fetch_daily` mais renvoie le payload JSON **avant**
    parsing Pydantic. Alimente le seam offline-seed : le payload
    brut est committé puis re-validé via :func:`parser_reponse_nasa` (parsing
    exercé en CI, fidélité). Comportement réseau (retry, erreurs) identique à
    :func:`fetch_daily`.

    Raises:
        NasaPowerTimeoutError, NasaPowerRateLimitError, NasaPowerHttpError,
        NasaPowerPayloadError (JSON non parsable).
    """
    url, query_params = _construire_url_et_params(
        endpoint="daily",
        latitude=latitude,
        longitude=longitude,
        parameters=parameters,
        start_str=_format_date_yyyymmdd(start),
        end_str=_format_date_yyyymmdd(end),
        community=community,
    )
    return _fetch_payload_brut(
        url=url, query_params=query_params, timeout=timeout, httpx_client=httpx_client
    )


def _format_annee_yyyy(annee: int) -> str:
    """Formate une année au format ``YYYY`` (paramètres ``start``/``end`` monthly)."""
    return f"{annee:04d}"


def fetch_monthly(
    *,
    latitude: float,
    longitude: float,
    parameters: Sequence[str],
    annee_debut: int,
    annee_fin: int,
    community: str = DEFAULT_COMMUNITY,
    timeout: float = DEFAULT_TIMEOUT,
    httpx_client: httpx.Client | None = None,
) -> NasaPowerResponse:
    """Récupère des séries mensuelles NASA POWER pour un point.

    Endpoint : ``https://power.larc.nasa.gov/api/temporal/monthly/point``.
    Les paramètres ``start`` et ``end`` sont des années (format
    ``YYYY``, 4 chiffres). La réponse retourne pour chaque paramètre
    un dictionnaire dont les clés sont des chaînes ``YYYYMM`` pour
    chaque mois ; certaines réponses incluent en plus une clé
    ``YYYY13`` représentant la moyenne annuelle, à filtrer côté caller
    si seules les valeurs mensuelles sont attendues.

    Supporte l'extension temporelle 1991-2020 de la fenêtre
    climatologique.

    Args:
        latitude: latitude WGS84 en degrés décimaux (positif Nord).
        longitude: longitude WGS84 en degrés décimaux (positif Est).
        parameters: codes NASA POWER à demander (max 20 selon doc).
        annee_debut: première année incluse (ex. 1991).
        annee_fin: dernière année incluse (ex. 2020).
        community: communauté NASA POWER (``RE`` par défaut).
        timeout: timeout HTTP en secondes.
        httpx_client: client httpx injectable.

    Returns:
        ``NasaPowerResponse`` parsé et validé. Les clés de
        ``properties.parameter[<nom>]`` sont au format ``YYYYMM``
        (et éventuellement ``YYYY13`` pour la moyenne annuelle).

    Raises:
        NasaPowerTimeoutError, NasaPowerRateLimitError,
        NasaPowerHttpError, NasaPowerPayloadError.
    """
    url, query_params = _construire_url_et_params(
        endpoint="monthly",
        latitude=latitude,
        longitude=longitude,
        parameters=parameters,
        start_str=_format_annee_yyyy(annee_debut),
        end_str=_format_annee_yyyy(annee_fin),
        community=community,
    )
    return _executer_requete(
        url=url, query_params=query_params, timeout=timeout, httpx_client=httpx_client
    )


def fetch_monthly_raw(
    *,
    latitude: float,
    longitude: float,
    parameters: Sequence[str],
    annee_debut: int,
    annee_fin: int,
    community: str = DEFAULT_COMMUNITY,
    timeout: float = DEFAULT_TIMEOUT,
    httpx_client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Récupère le payload JSON **brut** des séries mensuelles NASA POWER.

    Identique à :func:`fetch_monthly` mais renvoie le payload JSON **avant**
    parsing Pydantic. Alimente le seam offline-seed monthly : le
    payload brut est committé puis re-validé via :func:`parser_reponse_nasa`
    (parsing exercé en CI, fidélité). Comportement réseau (retry, erreurs)
    identique à :func:`fetch_monthly`.

    Raises:
        NasaPowerTimeoutError, NasaPowerRateLimitError, NasaPowerHttpError,
        NasaPowerPayloadError (JSON non parsable).
    """
    url, query_params = _construire_url_et_params(
        endpoint="monthly",
        latitude=latitude,
        longitude=longitude,
        parameters=parameters,
        start_str=_format_annee_yyyy(annee_debut),
        end_str=_format_annee_yyyy(annee_fin),
        community=community,
    )
    return _fetch_payload_brut(
        url=url, query_params=query_params, timeout=timeout, httpx_client=httpx_client
    )


def fetch_hourly(
    *,
    latitude: float,
    longitude: float,
    parameters: Sequence[str],
    start: date,
    end: date,
    community: str = DEFAULT_COMMUNITY,
    timeout: float = DEFAULT_TIMEOUT,
    time_standard: str = "UTC",
    httpx_client: httpx.Client | None = None,
) -> NasaPowerResponse:
    """Récupère des séries horaires NASA POWER pour un point.

    Les paramètres ``start`` et ``end`` sont des dates (granularité jour) :
    NASA POWER renvoie toutes les heures comprises entre ``start 00:00``
    et ``end 23:00`` (UTC ou LST selon ``time_standard``). Constat
    empirique : le format YYYYMMDDHH initialement testé est rejeté par
    l'endpoint avec HTTP 422 ; YYYYMMDD est la forme acceptée.

    Args:
        latitude: latitude WGS84 en degrés décimaux (positif Nord).
        longitude: longitude WGS84 en degrés décimaux (positif Est).
        parameters: codes NASA POWER à demander (max 15 selon doc pour
            la granularité horaire).
        start: date de début (incluse, toutes heures à partir de 00:00).
        end: date de fin (incluse, toutes heures jusqu'à 23:00).
        community: communauté NASA POWER (``RE`` par défaut).
        timeout: timeout HTTP en secondes.
        time_standard: ``"UTC"`` (par défaut) ou ``"LST"`` (Local
            Solar Time).
        httpx_client: client httpx injectable.

    Returns:
        ``NasaPowerResponse`` parsé et validé. Les clés de
        ``properties.parameter[<nom>]`` sont au format ``YYYYMMDDHH``.

    Raises:
        NasaPowerTimeoutError, NasaPowerRateLimitError,
        NasaPowerHttpError, NasaPowerPayloadError.
    """
    url, query_params = _construire_url_et_params(
        endpoint="hourly",
        latitude=latitude,
        longitude=longitude,
        parameters=parameters,
        start_str=_format_date_yyyymmdd(start),
        end_str=_format_date_yyyymmdd(end),
        community=community,
        time_standard=time_standard,
    )
    return _executer_requete(
        url=url, query_params=query_params, timeout=timeout, httpx_client=httpx_client
    )
