"""Helper HTTP avec retry transverse partagé.

Module utilitaire privé exposant un helper ``executer_get_avec_retry``
applicable à tout client httpx synchrone. Le retry couvre les exceptions
transitoires (HTTP 429, HTTP 503, ``httpx.TimeoutException``,
``httpx.RemoteProtocolError``) avec backoff exponentiel (défaut 1s, 4s,
16s).

Pattern « convert exceptions at boundaries » : le helper lève des
exceptions génériques ``HttpRetryTimeoutError``, ``HttpRetryRateLimitError``,
``HttpRetryHttpError`` que les modules consommateurs traduisent en
exceptions domaine-spécifiques (``NasaPower*Error``, ``Pvgis*Error``,
etc.) via try/except + raise from.

Couvre un scénario CI observé (migration 041 SARAH-3) :
disconnect serveur PVGIS intermittent depuis les runners GitHub Actions
manifesté comme ``httpx.RemoteProtocolError``. Inclus dans le catch
retry au même titre que ``httpx.TimeoutException`` (deux symptômes de
panne réseau transitoire).

Le périmètre retry est strictement limité aux 2 classes d'exception
explicitement listées (``TimeoutException``, ``RemoteProtocolError``)
plus les statuts HTTP 429 et 503. Un catch plus large
(``httpx.NetworkError``, ``ConnectError``) masquerait des erreurs non
transitoires (DNS, TLS) avec 21 s de retry inutile - élargissement
ciblé si nouveaux symptômes observés.
"""

from __future__ import annotations

import time

import httpx

# === Exceptions génériques exposées par le helper =========================


class HttpRetryError(Exception):
    """Base des erreurs levées à l'épuisement du retry transverse.

    Les modules consommateurs catchent cette hiérarchie et la traduisent
    en exceptions domaine-spécifiques via ``raise X from exc``.
    """


class HttpRetryTimeoutError(HttpRetryError):
    """Échec persistant de communication réseau après épuisement du retry.

    Couvre les timeouts (``httpx.TimeoutException``) et les disconnects
    serveur (``httpx.RemoteProtocolError``) répétés au-delà du nombre de
    retries configurés.
    """

    def __init__(self, *, url: str, timeout_seconds: float) -> None:
        super().__init__(
            f"Echec reseau persistant apres epuisement retry "
            f"(url={url}, timeout={timeout_seconds}s)"
        )
        self.url = url
        self.timeout_seconds = timeout_seconds


class HttpRetryHttpError(HttpRetryError):
    """Statut HTTP retryable (typiquement 503) persistant après retry."""

    def __init__(self, *, status_code: int, url: str, body: str) -> None:
        super().__init__(f"HTTP {status_code} persistant apres epuisement retry (url={url})")
        self.status_code = status_code
        self.url = url
        self.body = body


class HttpRetryRateLimitError(HttpRetryHttpError):
    """HTTP 429 (rate limit) persistant après épuisement du retry."""


# === Constantes module ====================================================

RETRY_BACKOFF_SECONDES: tuple[float, ...] = (1.0, 4.0, 16.0)
"""Backoffs exponentiels (1s, 4s, 16s) appliqués entre les tentatives
de retry. Total : 1 appel initial + 3 retries = 4 tentatives max."""

RETRY_STATUTS_HTTP: tuple[int, ...] = (429, 503)
"""Statuts HTTP retryables : 429 (rate limit) et 503 (service
indisponible). Autres statuts >= 400 sont terminaux (retour immédiat
de la response, gestion par le caller)."""


# === Helper public-module =================================================


def executer_get_avec_retry(
    *,
    client: httpx.Client,
    url: str,
    query_params: dict[str, str],
    timeout: float,
    retry_backoff_seconds: tuple[float, ...] = RETRY_BACKOFF_SECONDES,
    retry_statuts_http: tuple[int, ...] = RETRY_STATUTS_HTTP,
) -> httpx.Response:
    """Effectue un GET HTTPX avec retry exponentiel sur exceptions transitoires.

    Stratégie et périmètre du retry détaillés dans le docstring de module.
    Les statuts non retryables sont renvoyés immédiatement (gestion caller).

    ``retry_backoff_seconds`` est exposé pour les tests unitaires (passage de
    ``(0.0, 0.0, 0.0)`` pour éviter les sleeps).
    """
    nb_retries = len(retry_backoff_seconds)
    for tentative, backoff in enumerate([0.0, *retry_backoff_seconds]):
        if backoff > 0:
            time.sleep(backoff)
        try:
            response = client.get(url, params=query_params)
        except (httpx.TimeoutException, httpx.RemoteProtocolError) as exc:
            if tentative == nb_retries:
                # Url depuis l'exception si disponible, sinon l'url passée en
                # paramètre : httpx lève RuntimeError si .request n'est pas
                # défini (cas RemoteProtocolError).
                try:
                    url_effectif = str(exc.request.url)
                except RuntimeError:
                    url_effectif = url
                raise HttpRetryTimeoutError(
                    url=url_effectif,
                    timeout_seconds=timeout,
                ) from exc
            continue

        if response.status_code not in retry_statuts_http:
            return response

        if tentative == nb_retries:
            url_complete = str(response.request.url)
            if response.status_code == 429:
                raise HttpRetryRateLimitError(
                    status_code=response.status_code,
                    url=url_complete,
                    body=response.text,
                )
            raise HttpRetryHttpError(
                status_code=response.status_code,
                url=url_complete,
                body=response.text,
            )

    # Garde-fou type : la boucle termine toujours par return ou raise.
    raise RuntimeError("Boucle retry epuisee sans retour ni raise (incoherence interne)")
